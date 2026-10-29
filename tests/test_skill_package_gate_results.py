"""Package gate preserves partial support, prerequisite blockers, and scope deviation."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from skill_suite.package_gate_results import validate


ROOT = Path(__file__).resolve().parents[1]
SUMMARY = ROOT / "skill-suites/benchmark-multi-risk/package-capability-gate/summary.json"


class PackageGateResultsContract(unittest.TestCase):
    def test_real_summary_is_blocked_without_target_or_package_runtime_claim(self):
        result = validate(ROOT, SUMMARY)
        self.assertEqual(result["status"], "blocked-prerequisite")
        self.assertTrue(result["private_zip_control_plane"])
        self.assertFalse(result["package_runtime"])
        self.assertFalse(result["formal_package_track_ready"])
        self.assertEqual(result["target_calls"], 0)
        self.assertFalse(result["resource_cap_compliant"])
        self.assertEqual(result["unresolved_session_attempts"], 1)

    def test_runtime_or_resource_overclaim_fails_closed(self):
        value = json.loads(SUMMARY.read_text())
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "summary.json"
            value["capabilities"]["package_runtime"] = True
            value["resources"]["resource_cap_compliant"] = True
            path.write_text(json.dumps(value))
            with self.assertRaisesRegex(ValueError, "boundary drift"):
                validate(ROOT, path)

    def test_historical_global_snapshot_must_be_monotonic(self):
        value = json.loads(SUMMARY.read_text())
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "summary.json"
            value["global_calls"]["target"] = 10_000
            path.write_text(json.dumps(value))
            with self.assertRaisesRegex(ValueError, "global ledger drift"):
                validate(ROOT, path)


if __name__ == "__main__":
    unittest.main()
