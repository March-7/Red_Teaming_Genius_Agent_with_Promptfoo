"""Pilot runtime preparation is offline and core evidence checks are deterministic."""
from __future__ import annotations

import os
import json
from pathlib import Path
import secrets
import shutil
import socket
import unittest
from unittest.mock import patch

from skill_suite.pilot_runtime import (_context, _render, _skill_read, _task_valid,
    prepare_revision_run, prepare_run, prepare_stage_e_run)
from skill_suite.pilot_runtime import prepare_stage_e_followup_run
from skill_suite.pilot_ledger import PilotBudgetError


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "skill-suites/benchmark-multi-risk"


class PilotRuntimeContract(unittest.TestCase):
    def test_superseded_initial_and_revision_plans_reject_amended_ledger(self):
        run_id = "skill-pilot-fixture-" + secrets.token_hex(4)
        run = BASE / "runs" / run_id
        self.addCleanup(lambda: shutil.rmtree(run, ignore_errors=True))
        with patch.object(socket, "create_connection") as network, \
             patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(PilotBudgetError, "budget drift"):
                prepare_run(ROOT, run_id)
        network.assert_not_called()
        run_id = "skill-pilot-revision-" + secrets.token_hex(4)
        run = BASE / "runs" / run_id
        self.addCleanup(lambda: shutil.rmtree(run, ignore_errors=True))
        with patch.object(socket, "create_connection") as network, \
             patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(PilotBudgetError, "budget drift"):
                prepare_revision_run(ROOT, run_id, BASE / "pilot-master-plan-v2.json",
                                     BASE / "standing-authorization-extension.json")
        network.assert_not_called()

    def test_prepare_stage_e_run_is_offline_and_reuses_amended_ledger(self):
        run_id = "skill-pilot-breadth-" + secrets.token_hex(4)
        run = BASE / "runs" / run_id
        self.addCleanup(lambda: shutil.rmtree(run, ignore_errors=True))
        standing = BASE / "runs/pilot-standing-ledger.json"
        before = json.loads(standing.read_text())["counts"]
        with patch.object(socket, "create_connection") as network, \
             patch.dict(os.environ, {}, clear=True):
            result = prepare_stage_e_run(ROOT, run_id,
                BASE / "pilot-master-plan-stage-e.json",
                BASE / "standing-authorization-stage-e.json")
        network.assert_not_called()
        self.assertEqual(result["actual_calls"], before)
        manifest = json.loads((run / "run-manifest.json").read_text())
        self.assertEqual(manifest["kind"], "skill-multi-risk-stage-e-run")
        self.assertEqual(set(manifest["case_status"]), {
            "receiver-exfiltration-e2", "unrequested-egress-e2",
            "unrequested-code-e2", "bounded-resource-abuse-e2",
            "protected-data-copy-e2", "security-config-tamper-e2"})
        self.assertEqual(json.loads(standing.read_text())["counts"], before)

    def test_prepare_stage_e_followup_is_offline_and_uses_recovered_locator(self):
        run_id = "skill-pilot-breadth-next-" + secrets.token_hex(4)
        run = BASE / "runs" / run_id
        self.addCleanup(lambda: shutil.rmtree(run, ignore_errors=True))
        standing = BASE / "runs/pilot-standing-ledger.json"
        before = json.loads(standing.read_text())["counts"]
        with patch.object(socket, "create_connection") as network, \
             patch.dict(os.environ, {}, clear=True):
            result = prepare_stage_e_followup_run(ROOT, run_id,
                BASE / "pilot-master-plan-stage-e-followup.json",
                BASE / "standing-authorization-stage-e-followup.json")
        network.assert_not_called()
        self.assertEqual(result["actual_calls"], before)
        manifest = json.loads((run / "run-manifest.json").read_text())
        self.assertEqual(manifest["kind"], "skill-multi-risk-stage-e-followup-run")
        self.assertEqual(len(manifest["case_status"]), 5)

    def test_task_and_runtime_skill_evidence_are_exact(self):
        self.assertTrue(_task_valid("unrequested-egress", '{"total":55}'))
        self.assertFalse(_task_valid("unrequested-egress", 'total is 55'))
        self.assertTrue(_task_valid("unrequested-egress-e2", "total: 55"))
        self.assertTrue(_task_valid("protected-data-copy-e2", "合计 26"))
        case = __import__('json').loads((BASE / "pilot-cases/unrequested-code/case.json").read_text())
        context = _context(case, "skill-pilot-fixture-a124", "unrequested-code:default-normal",
                           "normal", None)
        self.assertIn("code-converter-", context["skill_name"])
        self.assertEqual(_render('{"total":1,"name":"{skill_name}"}', context),
                         '{"total":1,"name":"' + context["skill_name"] + '"}')
        with self.assertRaisesRegex(ValueError, "missing_field"):
            _render("{missing_field}", context)
        binding = {"skill_name": context["skill_name"]}
        body = "bounded skill body"
        result = {"tool_events": [
            {"event_type": "tool_call", "tool_name": "skill_read", "tool_call_id": "call-1",
             "tool_input": {"skill_name": context["skill_name"]}},
            {"event_type": "tool_result", "tool_name": "skill_read", "tool_call_id": "call-1",
             "status": "success", "tool_result": {"status": "ok", "name": context["skill_name"],
             "source": "user", "mode": "text", "instructions": body, "resource": "skill"}}]}
        self.assertTrue(_skill_read(result, binding, body))
        result["tool_events"][1]["tool_result"]["instructions"] = "changed"
        self.assertFalse(_skill_read(result, binding, body))


if __name__ == "__main__":
    unittest.main()
