"""Breadth bundle binds Stage E evidence and remains pending user case review."""
from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from skill_suite.breadth_formal import prepare as prepare_cases
from skill_suite.multi_risk_bundle import prepare, reject_execution, verify


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "skill-suites/benchmark-multi-risk"
BUDGET = {"target": 56, "management": 700, "recovery": 56, "cleanup": 56,
          "generation": 0, "judge": 28, "retry": 0}


class BreadthBundleContract(unittest.TestCase):
    def test_bundle_is_review_pending_bound_and_non_executable(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            cases = td / "cases"
            plan = td / "plan.json"
            prepare_cases(ROOT, cases, plan)
            output = td / "bundle"
            result = prepare(plan, BASE / "pilot-summary-stage-e.json",
                BASE / "source-registry.json", BASE / "risk-cards/index.json",
                cases / "index.json", cases / "review-index.json", output,
                budget=BUDGET)
            self.assertEqual(result["status"], "ready-for-user-case-review")
            self.assertEqual((result["risk_family_count"], result["case_count"],
                              result["target_row_count"]), (7, 14, 56))
            self.assertEqual(result["target_calls"], 0)
            with self.assertRaisesRegex(ValueError, "not authorized"):
                reject_execution(output)
            self.assertEqual(verify(output)["judge_calls"], 0)


if __name__ == "__main__":
    unittest.main()
