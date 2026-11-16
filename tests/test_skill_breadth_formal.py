"""Breadth formal freezes fourteen reviewed cases across seven valid risks."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from skill_suite.breadth_formal import prepare, validate


ROOT = Path(__file__).resolve().parents[1]


class BreadthFormalContract(unittest.TestCase):
    def test_builder_is_offline_balanced_and_user_review_pending(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "cases"
            plan = Path(td) / "plan.json"
            result = prepare(ROOT, out, plan)
            self.assertEqual((result["risk_family_count"], result["case_count"],
                              result["target_row_count"], result["reviewed_cases"]),
                             (7, 14, 56, 14))
            self.assertEqual(result["source_cases"],
                {"skillsbench": 7, "malskillbench": 4, "aig-skilljack": 3})
            self.assertEqual(result["user_review_status"], "pending")
            self.assertEqual(result["network_calls"], 0)

    def test_hidden_target_and_source_drift_fail_closed(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "cases"
            plan = Path(td) / "plan.json"
            prepare(ROOT, out, plan)
            index = json.loads((out / "index.json").read_text())
            path = out / index["cases"][0]["file"]
            case = json.loads(path.read_text())
            task = path.parent / case["task"]["file"]
            task.write_text(task.read_text() + " Archived by workflow")
            with self.assertRaisesRegex(ValueError, "task, Skill carrier"):
                validate(ROOT, out, plan)


if __name__ == "__main__":
    unittest.main()
