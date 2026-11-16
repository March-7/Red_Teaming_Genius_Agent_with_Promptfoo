"""Offline contracts for the carrier smoke plan, authorization, and runner."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from skill_suite.carrier_smoke import (SMOKE_IDS, SMOKE_LIMITS, USER_DECISION_REF,
                                       prepare, run_smoke, summarize,
                                       validate_authorization, validate_plan)
from sweep.runtime import write_json


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "skill-suites/benchmark-multi-risk/carrier-smoke"


class CarrierSmokeContract(unittest.TestCase):
    def test_real_plan_and_authorization_are_valid_and_bound(self):
        result = validate_plan(ROOT, BASE / "smoke-plan.json")
        self.assertEqual(result["smokes"], list(SMOKE_IDS))
        self.assertEqual((result["target_calls"], result["management_calls"],
                          result["cleanup_calls"]), (0, 0, 0))
        self.assertIs(result["formal_asr_eligible"], False)
        auth = validate_authorization(BASE / "smoke-plan.json",
                                      BASE / "smoke-authorization.json")
        self.assertIs(auth["active"], True)
        self.assertEqual(auth["user_decision_ref"], USER_DECISION_REF)
        self.assertEqual(auth["limits"], SMOKE_LIMITS)

    def test_authorization_rejects_drifted_plan_or_ref(self):
        plan = json.loads((BASE / "smoke-plan.json").read_text())
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "plan.json"
            write_json(path, plan)
            auth = json.loads((BASE / "smoke-authorization.json").read_text())
            auth["plan_file"] = str(path)
            auth_path = Path(td) / "auth.json"
            write_json(auth_path, auth)
            # wrong hash for the copied plan
            self.assertRaisesRegex(ValueError, "authorization drift",
                                   validate_authorization, path, auth_path)
            auth2 = dict(auth, plan_sha256=__import__("hashlib").sha256(
                path.read_bytes()).hexdigest(), user_decision_ref="other")
            write_json(auth_path, auth2)
            self.assertRaisesRegex(ValueError, "authorization drift",
                                   validate_authorization, path, auth_path)

    def test_run_smoke_requires_a_prepared_run_and_rejects_reuse(self):
        with tempfile.TemporaryDirectory() as td:
            run = Path(td) / "run"
            with self.assertRaises(OSError):
                run_smoke(ROOT, run, "text-skill")
            prepared = prepare(ROOT, run)
            self.assertEqual(prepared["status"], "prepared")
            manifest = json.loads((run / "run-manifest.json").read_text())
            manifest["smoke_statuses"] = {"text-skill": "completed"}
            write_json(run / "run-manifest.json", manifest)
            with self.assertRaisesRegex(ValueError, "already recorded"):
                run_smoke(ROOT, run, "text-skill")
            # summarize reads statuses without network
            summary = summarize(ROOT, run)
            self.assertEqual(summary["smokes"][0]["status"], "not-run")
            self.assertIs(summary["formal_asr_eligible"], False)

    def test_prepare_rejects_reused_or_drifted_code(self):
        with tempfile.TemporaryDirectory() as td:
            run = Path(td) / "run"
            first = prepare(ROOT, run)
            self.assertEqual(first["status"], "prepared")
            with self.assertRaisesRegex(ValueError, "empty carrier smoke run"):
                prepare(ROOT, run)
            manifest = json.loads((run / "run-manifest.json").read_text())
            manifest["code_hashes"] = {"skill_suite/carrier_smoke.py": "0" * 64}
            write_json(run / "run-manifest.json", manifest)
            with self.assertRaisesRegex(ValueError, "source or code drift"):
                summarize(ROOT, run)


if __name__ == "__main__":
    unittest.main()
