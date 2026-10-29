"""Runtime-only package gate removes download/test prerequisites but remains strict on trace binding."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import tempfile
import unittest

from skill_suite.package_gate_live import _runtime_evidence
from skill_suite.package_runtime_only import (prepare_run, validate_plan)
from skill_suite.package_runtime_only_results import validate as validate_results
from skill_suite.registry import ResourceRegistry


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "skill-suites/benchmark-multi-risk/package-capability-gate"
PLAN = BASE / "runtime-plan.json"
AUTH = BASE / "runtime-authorization-request.json"
PRIOR = BASE / "runs/package-runtime-20261007-b5285a32"
RESULTS = BASE / "runtime-summary.json"


class PackageRuntimeOnlyContract(unittest.TestCase):
    def test_registry_accepts_actual_package_skill_id_shape(self):
        with tempfile.TemporaryDirectory() as td:
            registry = ResourceRegistry(Path(td) / "resource-registry.jsonl", "run-1")
            registry.record("reference-runtime-a1b2c3d4@org_acce841a9bd0", "skill",
                            "reference-runtime-a1b2c3d4", "created",
                            owner_run_id="run-1", shared=False)
            self.assertEqual(registry.rows[-1]["resource_id"],
                             "reference-runtime-a1b2c3d4@org_acce841a9bd0")

    def test_plan_is_offline_and_defers_sessions_until_metadata_passes(self):
        result = validate_plan(ROOT, PLAN)
        self.assertEqual(result["network_calls"], 0)
        self.assertEqual(result["target_calls"], 0)
        plan = json.loads(PLAN.read_text())
        self.assertEqual(plan["call_order"].index("create-two-sessions"),
                         plan["call_order"].index("read-sharing") + 1)
        self.assertIn("package-download", plan["excluded_actions"])
        self.assertIn("package-test", plan["excluded_actions"])

    def test_prepare_requires_fresh_runtime_only_authorization(self):
        value = json.loads(AUTH.read_text())
        value.update(status="not-authorized", actor=None, decision=None,
                     message_ref=None, effective_date=None)
        with tempfile.TemporaryDirectory() as td:
            auth = Path(td) / "auth.json"
            auth.write_text(json.dumps(value))
            with self.assertRaisesRegex(ValueError, "fresh human"):
                prepare_run(ROOT, "package-runtime-a124b5c6", PLAN, auth, PRIOR)

    def test_active_fixture_carries_prior_counts_and_exact_resource_caps(self):
        value = json.loads(AUTH.read_text())
        value.update(status="active", actor="human-user",
            decision="start-package-runtime-only-gate",
            message_ref="fixture-confirmation", effective_date="2026-10-07")
        with tempfile.TemporaryDirectory() as td:
            auth = Path(td) / "auth.json"
            auth.write_text(json.dumps(value))
            run_id = "package-runtime-fixture-a124"
            run = BASE / "runs" / run_id
            self.addCleanup(lambda: shutil.rmtree(run, ignore_errors=True))
            result = prepare_run(ROOT, run_id, PLAN, auth, PRIOR)
            self.assertEqual(result["actual_calls"]["management"], 43)
            manifest = json.loads((run / "run-manifest.json").read_text())
            self.assertEqual(manifest["limits"]["cleanup"], 15)

    def test_trace_requires_skill_read_bound_entrypoint_nonce_and_asset_digest(self):
        name, nonce, digest = "reference-runtime-a124", "a124b5c6", "d" * 64
        raw = {"tool_events": [
            {"event_type": "tool_call", "tool_name": "skill_read",
             "tool_call_id": "read-1", "tool_input": {"skill_name": name}},
            {"event_type": "tool_result", "tool_name": "skill_read",
             "tool_call_id": "read-1", "status": "success",
             "tool_result": {"name": name, "source": "user", "mode": "shell"}},
            {"event_type": "tool_call", "tool_name": "execute_shell_command",
             "tool_call_id": "run-1",
             "tool_input": {"command": "python3 /skills/a/scripts/example.py"}},
            {"event_type": "tool_result", "tool_name": "execute_shell_command",
             "tool_call_id": "run-1", "status": "success",
             "tool_result": {"stdout": json.dumps(
                 {"nonce": nonce, "asset_sha256": digest})}},
        ]}
        evidence = _runtime_evidence(raw, skill_name=name, nonce=nonce,
            asset_sha256=digest, mode="shell", entrypoint_path="scripts/example.py")
        self.assertTrue(evidence["skill_read_verified"])
        self.assertTrue(evidence["package_entrypoint_bound"])
        self.assertTrue(evidence["nonce_verified"])
        self.assertTrue(evidence["asset_sha256_verified"])
        changed = json.loads(json.dumps(raw))
        changed["tool_events"][2]["tool_input"]["command"] = "python3 other.py"
        evidence = _runtime_evidence(changed, skill_name=name, nonce=nonce,
            asset_sha256=digest, mode="shell", entrypoint_path="scripts/example.py")
        self.assertFalse(evidence["package_entrypoint_bound"])

    def test_real_runtime_summary_preserves_capability_and_formal_boundary(self):
        result = validate_results(ROOT, RESULTS)
        self.assertTrue(result["package_runtime_supported"])
        self.assertTrue(result["package_asset_runtime_supported"])
        self.assertFalse(result["source_byte_readback_complete"])
        self.assertFalse(result["formal_package_track_ready"])
        self.assertEqual(result["target_calls"], 2)
        self.assertEqual(result["formal_target_calls"], 0)

    def test_runtime_summary_rejects_trace_or_formal_overclaim(self):
        value = json.loads(RESULTS.read_text())
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "summary.json"
            value["models"][0]["runtime_evidence"]["nonce_verified"] = False
            value["capabilities"]["formal_package_track_ready"] = True
            path.write_text(json.dumps(value))
            with self.assertRaisesRegex(ValueError, "boundary drift|trace evidence drift"):
                validate_results(ROOT, path)


if __name__ == "__main__":
    unittest.main()
