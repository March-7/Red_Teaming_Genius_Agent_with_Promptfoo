"""Source-complete taxonomy, dual screening, and supersession contracts."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from skill_suite.dual_gate_taxonomy import (
    validate_all, validate_catalogue, validate_screening, validate_trajectories)
from skill_suite.multi_risk_bundle import verify
from sweep.runtime import write_json


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "skill-suites/benchmark-multi-risk"


class DualGateTaxonomyContract(unittest.TestCase):
    def test_real_catalogue_and_dual_screening_are_complete_and_offline(self):
        result = validate_all(ROOT, BASE)
        self.assertEqual((result["source_count"], result["raw_entry_count"],
                          result["taxonomy_cell_count"]), (12, 274, 108))
        self.assertEqual(result["family_count"], 75)
        self.assertEqual(result["counts"]["observed_success"], 0)
        self.assertEqual(result["counts"]["source_faithful_testable"], 23)
        self.assertEqual(result["counts"]["b_only"], 23)
        self.assertEqual(result["trajectory_count"], 23)
        self.assertEqual(result["new_online_calls"],
                         {"target": 0, "generation": 0, "judge": 0})

    def test_dropped_raw_category_and_unproved_success_fail_closed(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            catalogue_path = td / "catalogue.json"
            catalogue = json.loads((BASE / "source-category-catalogue.json").read_text())
            catalogue["sources"][0]["entries"].pop()
            catalogue["sources"][0]["raw_entry_count"] -= 1
            catalogue["raw_entry_count"] -= 1
            write_json(catalogue_path, catalogue)
            with self.assertRaisesRegex(ValueError, "boundary drift|coverage drift"):
                validate_catalogue(ROOT, catalogue_path, BASE / "source-registry.json",
                    BASE / "source-inventory.jsonl", BASE / "source-inventory-summary.json")

            screening_path = td / "screening.json"
            screening = json.loads((BASE / "dual-gate-screening.json").read_text())
            screening["families"][0]["success_evidence"] = "observed-success"
            screening["families"][0]["success_evidence_refs"] = []
            write_json(screening_path, screening)
            family_map = json.loads((BASE / "risk-family-map.json").read_text())
            with self.assertRaisesRegex(ValueError, "immutable evidence"):
                validate_screening(ROOT, screening_path, BASE / "risk-family-map.json",
                    {"family_ids": {row["family_id"] for row in family_map["families"]}})

    def test_trajectory_cannot_contain_executable_payload(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "trajectories.json"
            value = json.loads((BASE / "dual-gate-trajectories.json").read_text())
            value["trajectories"][0]["executable_payload"] = True
            write_json(path, value)
            screening = json.loads((BASE / "dual-gate-screening.json").read_text())
            testable = set(screening["quadrants"]["a_and_b"] + screening["quadrants"]["b_only"])
            observed = set(screening["quadrants"]["a_and_b"] + screening["quadrants"]["a_only"])
            with self.assertRaisesRegex(ValueError, "safe review example"):
                validate_trajectories(ROOT, path, BASE / "dual-gate-screening.json",
                    {"testable_ids": testable, "observed_ids": observed})

    def test_tracked_breadth_bundle_is_superseded(self):
        with self.assertRaisesRegex(ValueError, "source-complete rescreen"):
            verify(BASE / "formal-start-bundle-breadth-v1")


if __name__ == "__main__":
    unittest.main()
