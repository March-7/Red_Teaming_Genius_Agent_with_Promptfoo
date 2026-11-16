"""Partial formal accounting fixtures; no target or Judge network calls."""
from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from sweep.runtime import sha256_file, write_json
from skill_suite.formal_progress import audit


class FormalProgressContract(unittest.TestCase):
    def test_partial_stop_preserves_model_counts_and_undefined_asr(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            master_dir = root / "master"
            master_dir.mkdir()
            workers = []
            for index in range(100):
                directory = f"workers/case-{index:03d}"
                run = master_dir / directory
                run.mkdir(parents=True)
                case_id = f"case-{index:03d}"
                rows = [{"evaluation_key": f"eval-{index:03d}-{profile_index}-{variant_index}",
                         "model_profile": profile, "variant": variant}
                        for profile_index, profile in enumerate(("default", "deepseek-v4.1-flash"))
                        for variant_index, variant in enumerate(("normal", "attack"))]
                stage_path = run / "d-smoke-plan.json"
                write_json(stage_path, {"case_id": case_id, "rows": rows})
                workers.append({"case_id": case_id, "directory": directory,
                                "plan_sha256": sha256_file(stage_path),
                                "evaluation_keys": [row["evaluation_key"] for row in rows]})
            master_path = master_dir / "formal-worker-plan.json"
            write_json(master_path, {"kind": "skill-formal-worker-plan",
                "run_id": "reading-formal-a1b2c3d4", "target_rows": 400,
                "worker_count": 100, "workers": workers,
                "candidate_limits_unapproved": {"target": 400, "management": 4800,
                                                "recovery": 400, "cleanup": 400}})
            auth_path = master_dir / "formal-worker-authorization.json"
            write_json(auth_path, {"status": "not-authorized",
                                   "plan_sha256": sha256_file(master_path)})
            initial = audit(root, master_dir)
            self.assertEqual(initial["status"], "not-authorized")
            self.assertEqual(initial["submitted_target_attempts"], 0)
            self.assertIsNone(initial["valid_attack_denominator"])
            first = master_dir / workers[0]["directory"]
            normal, attack = workers[0]["evaluation_keys"][:2]
            ledger_path = first / "call-ledger.json"
            ledger = {"counts": {"target": 2, "management": 14, "recovery": 0,
                                 "cleanup": 0, "generation": 0, "judge": 0},
                      "stopped": "target-error", "attempts": [
                          {"kind": "target", "operation_id": "target:" + normal,
                           "outcome": "completed"},
                          {"kind": "target", "operation_id": "target:" + attack,
                           "outcome": "target-error"}]}
            write_json(ledger_path, ledger)
            write_json(first / "worker-result.json", {"status": "stopped"})
            gate = {"rows": [{"evaluation_key": key,
                              "status": "evidence-valid-pending-review" if key == normal
                                        else "incomplete"}
                             for key in workers[0]["evaluation_keys"]]}
            with patch("skill_suite.formal_progress.audit_worker", return_value=gate):
                unauthorized = audit(root, master_dir)
            self.assertEqual(unauthorized["status"], "unauthorized-worker-attempts")
            write_json(auth_path, {"actor": "human-user",
                "decision": "start-formal-target-collection",
                "run_id": "reading-formal-a1b2c3d4",
                "plan_sha256": sha256_file(master_path),
                "message_ref": "unit fixture only", "confirmed_at": "2026-10-03T00:00:00Z"})
            with patch("skill_suite.formal_progress.audit_worker", return_value=gate):
                stopped = audit(root, master_dir)
            self.assertEqual(stopped["status"], "stopped-needs-review")
            self.assertEqual(stopped["submitted_target_attempts"], 2)
            self.assertEqual(stopped["models"]["default"]["normal"]["evidence_valid"], 1)
            self.assertEqual(stopped["models"]["default"]["attack"]["target_error"], 1)
            self.assertEqual(stopped["models"]["deepseek-v4.1-flash"]["attack"]["not_submitted"], 100)
            self.assertIsNone(stopped["valid_attack_denominator"])
            self.assertFalse(stopped["formal_asr_final"])
            ledger["counts"]["target"] = 3
            write_json(ledger_path, ledger)
            with patch("skill_suite.formal_progress.audit_worker", return_value=gate), \
                 self.assertRaisesRegex(ValueError, "ledger count differs"):
                audit(root, master_dir)


if __name__ == "__main__":
    unittest.main()
