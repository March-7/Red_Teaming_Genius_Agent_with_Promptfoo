"""Offline contracts for the case-20 exact-wording selection smoke."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from skill_suite.case20_selection_smoke import (USER_DECISION_REF,
                                                execute, prepare,
                                                validate_authorization,
                                                validate_plan)
from sweep.runtime import write_json


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "skill-suites/benchmark-multi-risk/carrier-smoke"


class Case20SelectionSmokeContract(unittest.TestCase):
    def test_real_plan_uses_frozen_wording_and_is_authorized(self):
        result = validate_plan(ROOT, BASE / "case20-smoke-plan.json")
        self.assertEqual(result["target_calls"], 0)
        self.assertIs(result["formal_asr_eligible"], False)
        plan = json.loads((BASE / "case20-smoke-plan.json").read_text())
        case = json.loads((ROOT / "skill-suites/benchmark-multi-risk"
            "/source-faithful-cases-v1"
            "/source-faithful-skill-impersonation-01.json").read_text())
        self.assertEqual(plan["exact_user_task_template"],
                         case["genius_case"]["user_task"])
        auth = validate_authorization(BASE / "case20-smoke-plan.json",
                                      BASE / "case20-smoke-authorization.json")
        self.assertIs(auth["active"], True)
        self.assertEqual(auth["user_decision_ref"], USER_DECISION_REF)

    def test_wording_drift_fails_closed(self):
        plan = json.loads((BASE / "case20-smoke-plan.json").read_text())
        plan["exact_user_task_template"] = ("Reconcile the totals in "
            "{invoice_name} and return the final amount.")
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "plan.json"
            write_json(path, plan)
            with self.assertRaisesRegex(ValueError, "frozen wording"):
                validate_plan(ROOT, path)

    def test_prepare_requires_empty_and_execute_requires_prepared(self):
        with tempfile.TemporaryDirectory() as td:
            run = Path(td) / "run"
            prepared = prepare(ROOT, run)
            self.assertEqual(prepared["status"], "prepared")
            with self.assertRaisesRegex(ValueError, "empty"):
                prepare(ROOT, run)
            manifest = json.loads((run / "run-manifest.json").read_text())
            manifest["status"] = "completed-natural-selection-not-observed"
            write_json(run / "run-manifest.json", manifest)
            with self.assertRaisesRegex(ValueError, "prepared case20"):
                execute(ROOT, run)


if __name__ == "__main__":
    unittest.main()
