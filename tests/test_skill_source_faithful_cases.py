"""Offline 23-family case blueprint contracts."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from skill_suite.source_faithful_cases import (validate_anchor_evidence,
                                               validate_case, validate_index)
from sweep.runtime import write_json


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "skill-suites/benchmark-multi-risk"


def _anchor_fixture():
    index = json.loads((BASE / "source-faithful-cases-v1/index.json").read_text())
    results = [{"case_id": ref["case_id"], "family_id": ref["family_id"],
                "carrier": "text-skill", "source_id": "skillleakbench"}
               for ref in index["cases"]]
    inventory = {}
    for line in (BASE / "source-inventory.jsonl").read_text().splitlines():
        if line.strip():
            row = json.loads(line)
            inventory[(row["source_id"], row["path"])] = (row["content_hash"],
                                                          row["size_bytes"])
    registry_doc = json.loads((BASE / "source-registry.json").read_text())
    registry = {row["source_id"]: row for row in registry_doc["sources"]}
    evidence = json.loads(
        (BASE / "source-faithful-cases-v1/source-anchor-evidence.json").read_text())
    return results, inventory, registry, evidence


class SourceFaithfulCaseContract(unittest.TestCase):
    def test_real_index_has_one_attack_only_case_per_selected_family(self):
        result = validate_index(ROOT, BASE)
        self.assertEqual((result["case_count"], result["family_count"]), (23, 23))
        self.assertEqual(result["carrier_counts"], {"catalogue-selection": 1,
            "package-asset": 4, "package-script": 9, "text-skill": 9})
        self.assertEqual((result["target_calls"], result["generation_calls"],
                          result["judge_calls"]), (0, 0, 0))
        self.assertEqual(result["user_review_status"], "approved")

    def test_evaluation_aware_name_and_weakened_source_chain_fail(self):
        index = json.loads((BASE / "source-faithful-cases-v1/index.json").read_text())
        original = BASE / "source-faithful-cases-v1" / index["cases"][0]["file"]
        value = json.loads(original.read_text())
        selection = json.loads((BASE / "formal-category-selection.json").read_text())
        catalogue = json.loads((BASE / "source-category-catalogue.json").read_text())
        raw_keys = {entry["raw_key"] for source in catalogue["sources"]
                    for entry in source["entries"]}
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "case.json"
            value["genius_case"]["skill_name_template"] = "attack-test-{nonce}"
            write_json(path, value)
            with self.assertRaises(ValueError):
                validate_case(path, selection, raw_keys)
            value = json.loads(original.read_text())
            value["source_chain"]["effect"] = ""
            write_json(path, value)
            with self.assertRaisesRegex(ValueError, "complete source chain"):
                validate_case(path, selection, raw_keys)

    def test_real_anchor_evidence_covers_23_cases_with_inventory_hashes(self):
        results, inventory, registry, evidence = _anchor_fixture()
        evidence["anchors"] = sorted(evidence["anchors"], key=lambda a: a["case_id"])
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "anchor-evidence.json"
            write_json(path, evidence)
            validate_anchor_evidence(path, results, inventory, registry)

    def test_metadata_only_source_with_verbatim_quote_fails(self):
        results, inventory, registry, evidence = _anchor_fixture()
        anchor = next(a for a in evidence["anchors"]
                      if a["source_id"] == "skill-inject")
        anchor["upstream_anchor"] = {"kind": "taxonomy-definition",
                                     "summary": "copied injection text", "verbatim": True}
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "anchor-evidence.json"
            write_json(path, evidence)
            with self.assertRaisesRegex(ValueError, "metadata-only"):
                validate_anchor_evidence(path, results, inventory, registry)

    def test_tampered_inventory_hash_and_unpinned_fetch_fail(self):
        results, inventory, registry, evidence = _anchor_fixture()
        anchor = evidence["anchors"][0]
        anchor["inventory_check"]["stored_hash"] = "0" * 64
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "anchor-evidence.json"
            write_json(path, evidence)
            with self.assertRaisesRegex(ValueError, "inventory hash"):
                validate_anchor_evidence(path, results, inventory, registry)
        evidence = _anchor_fixture()[3]
        anchor = evidence["anchors"][0]
        anchor["fetch"]["pinned_commit"] = "0" * 40
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "anchor-evidence.json"
            write_json(path, evidence)
            with self.assertRaisesRegex(ValueError, "pinned to the registered"):
                validate_anchor_evidence(path, results, inventory, registry)


if __name__ == "__main__":
    unittest.main()
