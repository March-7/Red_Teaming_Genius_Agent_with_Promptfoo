"""Multi-risk pilot cases are frozen, neutral, source-bound, and zero-call."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import unittest

from skill_suite.pilot_cases import validate_case, validate_index
from sweep.runtime import write_json


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "skill-suites/benchmark-multi-risk"
KWARGS = {"project_root": ROOT, "shortlist_path": BASE / "risk-shortlist.json",
    "card_index_path": BASE / "risk-cards/index.json",
    "capability_path": BASE / "capability-registry.json",
    "source_registry_path": BASE / "source-registry.json",
    "source_inventory_path": BASE / "source-inventory.jsonl",
    "source_inventory_summary_path": BASE / "source-inventory-summary.json",
    "relationship_summary_path": BASE / "relationships/summary.json"}


class PilotCaseContract(unittest.TestCase):
    def test_tracked_index_is_six_cases_with_zero_calls_and_bounded_plan(self):
        result = validate_index(BASE / "pilot-cases/index.json", **KWARGS)
        self.assertEqual(result["case_count"], 10)
        self.assertEqual(result["planned_limits"]["target"], 90)
        self.assertEqual(result["planned_limits"]["generation"], 0)
        self.assertEqual(result["planned_limits"]["judge"], 0)
        self.assertTrue(all(value == 0 for value in result["actual_calls"].values()))
        self.assertFalse(result["formal_asr_eligible"])

    def test_task_payload_budget_and_attack_only_carrier_drift_fail_closed(self):
        source_root = BASE / "pilot-cases/receiver-exfiltration"
        original = json.loads((source_root / "case.json").read_text())
        with tempfile.TemporaryDirectory() as temporary:
            case_root = Path(temporary)
            for path in source_root.iterdir():
                if path.is_file():
                    (case_root / path.name).write_bytes(path.read_bytes())
            case_path = case_root / "case.json"
            for mutate in (
                lambda value: value.update(legitimate_task_template=
                    value["legitimate_task_template"] + " protected_marker"),
                lambda value: value["limits"].update(target=10),
                lambda value: value["actual_calls"].update(target=1),
            ):
                changed = copy.deepcopy(original)
                mutate(changed)
                write_json(case_path, changed)
                with self.assertRaises(ValueError):
                    validate_case(case_path, **KWARGS)
            changed = copy.deepcopy(original)
            (case_root / "attack-skill.md").write_text("Unrelated instructions.\n")
            from sweep.runtime import sha256_file
            changed["skills"]["attack"]["sha256"] = sha256_file(case_root / "attack-skill.md")
            write_json(case_path, changed)
            with self.assertRaisesRegex(ValueError, "appended"):
                validate_case(case_path, **KWARGS)


if __name__ == "__main__":
    unittest.main()
