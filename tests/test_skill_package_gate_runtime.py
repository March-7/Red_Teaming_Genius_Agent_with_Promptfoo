"""Package gate authorization and ledger reject online work before exact confirmation."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import unittest

from skill_suite.package_gate_runtime import (PackageGateBudgetError,
    PackageGateLedger, prepare_run, preview)
from sweep.runtime import sha256_file, write_json


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "skill-suites/benchmark-multi-risk/package-capability-gate"
PLAN = BASE / "plan.json"
AUTH = BASE / "authorization-request.json"


class PackageGateRuntimeContract(unittest.TestCase):
    def test_real_preview_is_zero_call_and_not_authorized(self):
        value = json.loads(AUTH.read_text())
        value.update(status="not-authorized", actor=None, decision=None,
                     message_ref=None, effective_date=None)
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "auth.json"
            write_json(path, value)
            result = preview(ROOT, PLAN, path)
            self.assertEqual(result["network_calls"], 0)
            self.assertEqual(result["credential_reads"], 0)
            self.assertEqual(result["online_authorization"], "not-authorized")
            self.assertEqual(result["target_calls"], 0)

    def test_prepare_rejects_empty_or_forged_authorization(self):
        value = json.loads(AUTH.read_text())
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "auth.json"
            value.update(status="not-authorized", actor=None, decision=None,
                         message_ref=None, effective_date=None)
            write_json(path, value)
            with self.assertRaisesRegex(ValueError, "fresh human"):
                prepare_run(ROOT, "package-reference-a124b5c6", PLAN, path)
            value.update(status="active", actor="human-user",
                         decision="start-package-skill-capability-gate",
                         message_ref="", effective_date="2026-10-07")
            write_json(path, value)
            with self.assertRaisesRegex(ValueError, "fresh human"):
                prepare_run(ROOT, "package-reference-a124b5c6", PLAN, path)

    def test_active_fixture_prepares_without_calls(self):
        value = json.loads(AUTH.read_text())
        value.update(status="active", actor="human-user",
            decision="start-package-skill-capability-gate",
            message_ref="fixture-human-confirmation", effective_date="2026-10-07")
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            path = td / "auth.json"
            write_json(path, value)
            run_id = "package-reference-fixture-a124"
            run = BASE / "runs" / run_id
            self.addCleanup(lambda: __import__("shutil").rmtree(run, ignore_errors=True))
            result = prepare_run(ROOT, run_id, PLAN, path)
            self.assertEqual(result["actual_calls"]["target"], 0)
            self.assertEqual(result["actual_calls"]["management"], 0)

    def test_stage_ledger_is_zero_retry_and_counts_recovery_as_management(self):
        with tempfile.TemporaryDirectory() as td:
            ledger = PackageGateLedger(Path(td) / "ledger.json")
            ledger.reserve("recovery", "recover:a")
            ledger.finish("recover:a", "completed")
            self.assertEqual(ledger.state["counts"]["recovery"], 1)
            self.assertEqual(ledger.state["counts"]["management"], 1)
            with self.assertRaisesRegex(PackageGateBudgetError, "already exists"):
                ledger.reserve("recovery", "recover:a")
            with self.assertRaisesRegex(PackageGateBudgetError, "retries"):
                ledger.reserve("retry", "retry:a")


if __name__ == "__main__":
    unittest.main()
