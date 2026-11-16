"""Stage E reports all ten selected risks and a seven-risk breadth gate."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from skill_suite.stage_e_results import build, validate


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "skill-suites/benchmark-multi-risk"
INITIAL = BASE / "runs" / "skill-pilot-breadth-20261005-8bbf1796"
FOLLOWUP = BASE / "runs" / "skill-pilot-breadth-next-20261005-48e9e6f7"


class StageEResultsContract(unittest.TestCase):
    def test_real_stage_e_receipts_cover_all_ten_risks(self):
        with tempfile.TemporaryDirectory() as td:
            output = Path(td) / "summary.json"
            result = build(ROOT, INITIAL, FOLLOWUP, output)
            self.assertEqual((result["selected_risk_count"], result["eligible_risk_count"],
                              result["blocked_risk_count"]), (10, 7, 3))
            self.assertEqual((result["breadth_formal_case_count"],
                              result["breadth_formal_target_rows"]), (14, 56))
            self.assertEqual(result["actual_calls"]["target"], 72)
            self.assertEqual(result["actual_calls"]["judge"], 0)

    def test_eligible_evidence_and_hash_drift_fail_closed(self):
        with tempfile.TemporaryDirectory() as td:
            output = Path(td) / "summary.json"
            build(ROOT, INITIAL, FOLLOWUP, output)
            value = json.loads(output.read_text())
            selected = next(row for row in value["outcomes"] if row["formal_eligible"])
            selected["attack_valid_models"].pop()
            output.write_text(json.dumps(value))
            with self.assertRaisesRegex(ValueError, "evidence incomplete"):
                validate(ROOT, output)


if __name__ == "__main__":
    unittest.main()
