"""Stage E freezes six evidence-linked revisions and a monotonic budget amendment."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from skill_suite.pilot_ledger import PilotBudgetError, PilotLedger
from skill_suite.stage_e_pilot import (OLD_LIMITS, TOTAL_LIMITS,
    validate_followup_master, validate_master)


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "skill-suites/benchmark-multi-risk"


class StageEPilotContract(unittest.TestCase):
    def test_real_stage_e_master_covers_six_remaining_risks(self):
        result = validate_master(ROOT, BASE / "pilot-master-plan-stage-e.json",
                                 BASE / "standing-authorization-stage-e.json")
        self.assertEqual(result["worker_count"], 6)
        self.assertEqual(result["candidate_iterations_total"], 20)
        self.assertEqual(result["candidate_iteration_cap"], 22)
        self.assertEqual(result["planned_limits"]["target"], 36)
        self.assertEqual(result["total_api_limits"]["management"], 1440)
        self.assertFalse(result["formal_asr_eligible"])

    def test_followup_replaces_receiver_landing_locator_without_replaying_egress(self):
        result = validate_followup_master(ROOT,
            BASE / "pilot-master-plan-stage-e-followup.json",
            BASE / "standing-authorization-stage-e-followup.json")
        self.assertEqual(result["worker_count"], 5)
        self.assertEqual(result["planned_limits"]["target"], 30)
        self.assertEqual(result["candidate_iterations_total"], 20)

    def test_budget_amendment_is_monotonic_evidence_bound_and_single_use(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            auth = td / "authorization.json"
            auth.write_text('{"actor":"human-user"}')
            ledger = PilotLedger(td / "ledger.json", OLD_LIMITS)
            ledger.amend_limits(TOTAL_LIMITS, authorization_path=auth)
            self.assertEqual(ledger.state["limits"]["management"], 1440)
            self.assertEqual(len(ledger.state["limit_amendments"]), 1)
            with self.assertRaisesRegex(PilotBudgetError, "already applied"):
                ledger.amend_limits(TOTAL_LIMITS, authorization_path=auth)
            lower = dict(TOTAL_LIMITS, target=95)
            second = td / "second.json"
            second.write_text('{"actor":"human-user","id":2}')
            with self.assertRaisesRegex(PilotBudgetError, "only increase"):
                ledger.amend_limits(lower, authorization_path=second)

    def test_master_and_authorization_hash_drift_fail_closed(self):
        master = json.loads((BASE / "pilot-master-plan-stage-e.json").read_text())
        auth = json.loads((BASE / "standing-authorization-stage-e.json").read_text())
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            master["workers"][0]["call_order"].reverse()
            mp = td / "master.json"
            mp.write_text(json.dumps(master))
            from sweep.runtime import sha256_file
            auth["stage_e_master_sha256"] = sha256_file(mp)
            ap = td / "authorization.json"
            ap.write_text(json.dumps(auth))
            with self.assertRaisesRegex(ValueError, "order or budget"):
                validate_master(ROOT, mp, ap)


if __name__ == "__main__":
    unittest.main()
