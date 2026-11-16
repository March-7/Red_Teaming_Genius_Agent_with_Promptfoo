"""The real portfolio contains 20 reviewed cases and a balanced 80-row matrix."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from skill_suite.formal_portfolio import prepare, validate


ROOT = Path(__file__).resolve().parents[1]


class FormalPortfolioContract(unittest.TestCase):
    def test_real_builder_is_offline_balanced_and_reviewed(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "cases"
            plan = Path(td) / "plan.json"
            result = prepare(ROOT, out, plan)
            self.assertEqual((result["risk_family_count"], result["case_count"],
                              result["target_row_count"], result["reviewed_cases"]),
                             (4, 20, 80, 20))
            self.assertEqual(result["source_cases"],
                {"malskillbench": 5, "aig-skilljack": 5, "skillsbench": 10})
            self.assertEqual(result["network_calls"], 0)
            self.assertFalse(result["formal_target_authorized"])

    def test_task_and_source_balance_drift_fail_closed(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "cases"
            plan = Path(td) / "plan.json"
            prepare(ROOT, out, plan)
            index_path = out / "index.json"
            index = json.loads(index_path.read_text())
            case_path = out / index["cases"][0]["file"]
            case = json.loads(case_path.read_text())
            task_path = case_path.parent / case["task"]["file"]
            task_path.write_text(task_path.read_text() + " changed")
            with self.assertRaisesRegex(ValueError, "task, Skill carrier"):
                validate(ROOT, out, plan)


if __name__ == "__main__":
    unittest.main()
