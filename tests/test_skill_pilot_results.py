"""Post-pilot dispositions preserve failed gates and the shared call ledger."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import unittest

from skill_suite.pilot_results import validate
from sweep.runtime import write_json


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "skill-suites/benchmark-multi-risk"


class PilotResultContract(unittest.TestCase):
    def test_tracked_summary_has_ten_outcomes_zero_formal_eligible_and_no_pending(self):
        result = validate(BASE, BASE / "risk-shortlist.json", BASE / "pilot-summary.json")
        self.assertEqual(result["selected_candidate_count"], 10)
        self.assertEqual(result["formal_eligible_count"], 0)
        self.assertEqual(result["formal_portfolio_gate"],
                         "blocked-insufficient-valid-risk-families")
        self.assertEqual((result["generation_calls"], result["judge_calls"],
                          result["formal_target_calls"]), (0, 0, 0))
        self.assertEqual(result["pending_sessions"], 0)

    def test_evidence_hash_or_unproven_formal_eligibility_is_rejected(self):
        value = json.loads((BASE / "pilot-summary.json").read_text())
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "summary.json"
            changed = copy.deepcopy(value)
            changed["outcomes"][0]["evidence_refs"][0]["sha256"] = "0" * 64
            write_json(path, changed)
            with self.assertRaises(ValueError):
                validate(BASE, BASE / "risk-shortlist.json", path)
            changed = copy.deepcopy(value)
            changed["outcomes"][0]["formal_eligible"] = True
            changed["formal_eligible_case_ids"] = [changed["outcomes"][0]["case_id"]]
            changed["formal_eligible_count"] = 1
            write_json(path, changed)
            with self.assertRaises(ValueError):
                validate(BASE, BASE / "risk-shortlist.json", path)


if __name__ == "__main__":
    unittest.main()
