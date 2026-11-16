"""The real revised pilot receipts gate four risk families without formal ASR."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import tempfile
import unittest

from skill_suite.revised_pilot_results import validate


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "skill-suites/benchmark-multi-risk"
RUNS = sorted((BASE / "runs").glob("skill-pilot-reference-20261005-*"))


class RevisedPilotResultsContract(unittest.TestCase):
    def test_real_revision_receipts_freeze_four_families(self):
        result = validate(ROOT, BASE / "pilot-summary-v2.json")
        self.assertEqual(result["formal_eligible_count"], 4)
        self.assertEqual(len(result["formal_eligible_risk_families"]), 4)
        self.assertEqual(result["actual_calls"]["target"], 48)
        self.assertEqual(result["actual_calls"]["judge"], 0)
        self.assertEqual(result["pending_sessions"], 0)

    def test_summary_hash_and_two_model_evidence_fail_closed(self):
        self.assertTrue(RUNS)
        with tempfile.TemporaryDirectory() as td:
            output = Path(td) / "summary.json"
            value = json.loads((BASE / "pilot-summary-v2.json").read_text())
            value["revision_outcomes"][0]["attack_valid_models"].pop()
            output.write_text(json.dumps(value))
            with self.assertRaisesRegex(ValueError, "evidence incomplete"):
                validate(ROOT, output)


if __name__ == "__main__":
    unittest.main()
