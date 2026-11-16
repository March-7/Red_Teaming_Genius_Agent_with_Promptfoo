"""Four-tier benchmark adaptation contracts use tracked source metadata only."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import unittest

from skill_suite.benchmark_adaptation import validate_manifest
from sweep.runtime import sha256_file, write_json


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "skill-suites/benchmark-multi-risk"
REGISTRY = BASE / "source-registry.json"
INVENTORY = BASE / "source-inventory.jsonl"
SUMMARY = BASE / "source-inventory-summary.json"


class BenchmarkAdaptationContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = [json.loads(line) for line in INVENTORY.read_text().splitlines() if line]

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def source_ref(self, source_id):
        row = next(row for row in self.rows if row["source_id"] == source_id)
        return {key: row[key] for key in ("path", "hash_algorithm", "content_hash")}

    def manifest(self, source_id, tier, *, output=True):
        target = self.root / "case.md"
        if output:
            target.write_text("Locally authored controlled instructions.\n")
        disposition = {row["source_id"]: row["license_disposition"]
                       for row in json.loads(REGISTRY.read_text())["sources"]}[source_id]
        differences = [] if tier in {"direct-reuse", "not-applicable"} else [{
            "field": "attack_pattern", "before_hash": self.source_ref(source_id)["content_hash"],
            "after_hash": sha256_file(target), "reason": "Map the risk pattern to a reversible Genius case"}]
        authorship = "adapted" if tier == "minimal-adaptation" else "local-original"
        files = [] if not output else [{"file": target.name, "sha256": sha256_file(target),
                                        "role": "candidate-skill", "authorship": authorship}]
        return {"schema_version": 1, "kind": "skill-benchmark-adaptation",
            "adaptation_id": "adaptation-a124", "source_id": source_id,
            "source_assets": [self.source_ref(source_id)], "reuse_tier": tier,
            "license_disposition": disposition,
            "source_content_copied": tier == "minimal-adaptation",
            "field_differences": differences, "adapted_files": files,
            "genius_case_generated": tier != "not-applicable",
            "applicability": "not-applicable" if tier == "not-applicable" else "candidate",
            "upstream_claim_only": True, "genius_finding": None}

    def check(self, value):
        path = self.root / "manifest.json"
        write_json(path, value)
        return validate_manifest(path, REGISTRY, INVENTORY, SUMMARY)

    def test_pattern_only_allows_local_case_but_rejects_source_copy_and_hash_drift(self):
        value = self.manifest("aig-skilljack", "pattern-only")
        self.assertEqual(self.check(value)["reuse_tier"], "pattern-only")
        changed = copy.deepcopy(value)
        changed["source_content_copied"] = True
        with self.assertRaises(ValueError): self.check(changed)
        changed = copy.deepcopy(value)
        changed["source_assets"][0]["content_hash"] = "0" * 64
        with self.assertRaises(ValueError): self.check(changed)

    def test_metadata_only_source_can_only_be_not_applicable(self):
        value = self.manifest("skill-inject", "not-applicable", output=False)
        self.assertFalse(self.check(value)["genius_ground_truth"])
        changed = self.manifest("skill-inject", "pattern-only")
        with self.assertRaisesRegex(ValueError, "ceiling"):
            self.check(changed)

    def test_minimal_adaptation_records_output_hash_and_field_difference(self):
        value = self.manifest("skillsbench", "minimal-adaptation")
        result = self.check(value)
        self.assertEqual(result["adapted_file_count"], 1)
        changed = copy.deepcopy(value)
        changed["field_differences"] = []
        with self.assertRaises(ValueError): self.check(changed)

    def test_not_applicable_cannot_leave_generated_files_or_case(self):
        value = self.manifest("malskillbench", "not-applicable", output=False)
        self.assertEqual(self.check(value)["adapted_file_count"], 0)
        changed = copy.deepcopy(value)
        changed["genius_case_generated"] = True
        with self.assertRaises(ValueError): self.check(changed)

    def test_direct_reuse_requires_byte_identical_sha256_source(self):
        target = self.root / "direct.md"
        target.write_text("Byte-identical fixture.\n")
        registry = json.loads(REGISTRY.read_text())
        source = next(row for row in registry["sources"] if row["source_id"] == "aig-skilljack")
        source.update(license_disposition="confirmed-open", content_reuse_ceiling="direct-reuse")
        registry_path = self.root / "registry.json"
        write_json(registry_path, registry)
        all_rows = [json.loads(line) for line in INVENTORY.read_text().splitlines() if line]
        selected = []
        for source_id in ("aig-skilljack", "skill-inject", "malskillbench", "skillsbench"):
            row = copy.deepcopy(next(row for row in all_rows if row["source_id"] == source_id))
            if source_id == "aig-skilljack":
                row.update(hash_algorithm="sha256", content_hash=sha256_file(target))
            selected.append(row)
        inventory = self.root / "inventory.jsonl"
        inventory.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in selected))
        summary = self.root / "summary.json"
        write_json(summary, {"schema_version": 1,
            "kind": "skill-benchmark-source-inventory-summary",
            "registry_file": str(registry_path), "registry_sha256": sha256_file(registry_path),
            "inventory_file": str(inventory), "inventory_sha256": sha256_file(inventory),
            "source_count": 12, "asset_count": 4, "sources": [],
            "scripts_executed": 0, "archives_expanded": 0,
            "network_actions": "none", "genius_ground_truth": False})
        source_row = selected[0]
        manifest = {"schema_version": 1, "kind": "skill-benchmark-adaptation",
            "adaptation_id": "direct-a124", "source_id": "aig-skilljack",
            "source_assets": [{key: source_row[key]
                               for key in ("path", "hash_algorithm", "content_hash")}],
            "reuse_tier": "direct-reuse", "license_disposition": "confirmed-open",
            "source_content_copied": True, "field_differences": [],
            "adapted_files": [{"file": target.name, "sha256": sha256_file(target),
                               "role": "candidate-skill", "authorship": "source-copy"}],
            "genius_case_generated": True, "applicability": "candidate",
            "upstream_claim_only": True, "genius_finding": None}
        manifest_path = self.root / "direct.json"
        write_json(manifest_path, manifest)
        self.assertEqual(validate_manifest(manifest_path, registry_path, inventory, summary)
                         ["reuse_tier"], "direct-reuse")
        target.write_text("Changed bytes.\n")
        with self.assertRaises(ValueError):
            validate_manifest(manifest_path, registry_path, inventory, summary)


if __name__ == "__main__":
    unittest.main()
