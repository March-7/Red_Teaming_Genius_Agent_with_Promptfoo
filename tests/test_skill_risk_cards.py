"""Risk cards require evidence, controls, independent oracles, and human-auditable gates."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import unittest

from skill_suite.risk_cards import validate_card, validate_index, validate_shortlist
from sweep.runtime import write_json


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "skill-suites/benchmark-multi-risk"
CAPABILITIES = BASE / "capability-registry.json"
SOURCES = BASE / "source-registry.json"
RELATIONSHIPS = BASE / "relationships/summary.json"


class RiskCardContract(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.card = json.loads((BASE / "risk-cards/receiver-exfiltration.json").read_text())

    def check(self, value):
        path = self.root / "card.json"
        write_json(path, value)
        return validate_card(path, CAPABILITIES, SOURCES, RELATIONSHIPS, ROOT)

    def test_tracked_index_has_six_evidence_selected_candidates(self):
        result = validate_index(BASE / "risk-cards/index.json", CAPABILITIES, SOURCES,
                                RELATIONSHIPS, ROOT)
        self.assertEqual(result["card_count"], 18)
        self.assertEqual(len(result["eligible_cards"]), 10)
        self.assertFalse(result["model_decides"])
        shortlist = validate_shortlist(BASE / "risk-shortlist.json",
            BASE / "risk-cards/index.json", CAPABILITIES, SOURCES, RELATIONSHIPS, ROOT)
        self.assertEqual(shortlist["selected_count"], 10)
        self.assertEqual(shortlist["source_ids"],
                         ["aig-skilljack", "malskillbench", "skillsbench"])
        calibration = json.loads((BASE / "risk-cards/legacy-note-write.json").read_text())
        self.assertEqual(self.check(calibration)["disposition"], "calibration-only")

    def test_missing_harm_control_or_oracle_rejects_eligibility(self):
        mutations = (
            lambda value: value.pop("material_harm"),
            lambda value: value["controls"].pop("positive"),
            lambda value: value["independent_oracle"].update(target_independent=False),
            lambda value: value["recovery"].update(run_owned_only=False),
        )
        for mutate in mutations:
            changed = copy.deepcopy(self.card)
            mutate(changed)
            with self.assertRaises(ValueError):
                self.check(changed)

    def test_model_recommendation_and_unavailable_capability_cannot_pass(self):
        changed = copy.deepcopy(self.card)
        changed["model_role"]["model_decides"] = True
        with self.assertRaisesRegex(ValueError, "model"):
            self.check(changed)
        changed = copy.deepcopy(self.card)
        changed["required_capabilities"][-1] = "payment-transfer"
        changed["capability_evidence"][-1] = {"capability_id": "payment-transfer",
            "use": "Unavailable transfer path", "pilot_positive_control_required": True}
        with self.assertRaisesRegex(ValueError, "hard gate"):
            self.check(changed)


if __name__ == "__main__":
    unittest.main()
