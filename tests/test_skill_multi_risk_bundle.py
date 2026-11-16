"""A formal bundle needs real pilot eligibility and remains non-executable."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import unittest

from skill_suite.multi_risk_bundle import prepare, reject_execution, verify
from tests.test_skill_multi_risk_formal import MultiRiskFormalContract
from sweep.runtime import sha256_file, write_json


class MultiRiskBundleContract(unittest.TestCase):
    def setUp(self):
        self.fixture = MultiRiskFormalContract("test_matrix_and_provisioner_preserve_multi_risk_source_and_resource_isolation")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root
        self.plan_path = self.fixture.plan_path
        self.pilot = self.root / "pilot.json"
        self.sources = self.root / "sources.json"
        self.cards = self.root / "cards.json"
        self.cases = self.root / "cases.json"
        self.reviews = self.root / "reviews.json"
        write_json(self.sources, {"kind": "fixture-source-registry"})
        write_json(self.cards, {"kind": "fixture-risk-cards"})
        write_json(self.cases, {"kind": "skill-multi-risk-formal-case-index",
            "status": "reviewed-frozen", "case_count": 20,
            "formal_target_authorized": False})
        write_json(self.reviews, {"kind": "skill-multi-risk-formal-review-index",
            "reviewed_count": 20, "accepted_count": 20})
        write_json(self.pilot, {"kind": "genius-skill-multi-risk-pilot-summary",
            "formal_portfolio_gate": "passed",
            "formal_eligible_risk_families": self.fixture.plan["risk_families"]})
        plan = json.loads(self.plan_path.read_text())
        plan.update(source_registry_sha256=sha256_file(self.sources),
                    risk_cards_sha256=sha256_file(self.cards),
                    pilot_summary_sha256=sha256_file(self.pilot))
        write_json(self.plan_path, plan)
        self.budget = {"target": 80, "management": 800, "recovery": 80,
                       "cleanup": 80, "generation": 0, "judge": 40, "retry": 0}

    def test_bundle_binds_all_sources_and_rejects_unapproved_execution(self):
        output = self.root / "bundle"
        result = prepare(self.plan_path, self.pilot, self.sources, self.cards,
                         self.cases, self.reviews, output, budget=self.budget)
        self.assertTrue(result["verified"])
        self.assertEqual((result["risk_family_count"], result["target_row_count"]), (4, 80))
        with self.assertRaisesRegex(ValueError, "not authorized"):
            reject_execution(output)
        self.assertEqual(verify(output)["target_calls"], 0)

    def test_current_zero_eligible_shape_and_authorization_drift_fail_closed(self):
        blocked = copy.deepcopy(json.loads(self.pilot.read_text()))
        blocked.update(formal_portfolio_gate="blocked-insufficient-valid-risk-families",
                       formal_eligible_risk_families=[])
        write_json(self.pilot, blocked)
        plan = json.loads(self.plan_path.read_text())
        plan["pilot_summary_sha256"] = sha256_file(self.pilot)
        write_json(self.plan_path, plan)
        with self.assertRaisesRegex(ValueError, "pilot-eligible"):
            prepare(self.plan_path, self.pilot, self.sources, self.cards,
                    self.cases, self.reviews, self.root / "blocked", budget=self.budget)
        write_json(self.pilot, {"kind": "genius-skill-multi-risk-pilot-summary",
            "formal_portfolio_gate": "passed",
            "formal_eligible_risk_families": self.fixture.plan["risk_families"]})
        plan = json.loads(self.plan_path.read_text())
        plan["pilot_summary_sha256"] = sha256_file(self.pilot)
        write_json(self.plan_path, plan)
        output = self.root / "bundle"
        prepare(self.plan_path, self.pilot, self.sources, self.cards,
                self.cases, self.reviews, output, budget=self.budget)
        write_json(output / "formal-start-authorization.json", {"actor": "human-user"})
        with self.assertRaisesRegex(ValueError, "not-authorized"):
            verify(output)

    def test_stage_e_supersession_rejects_previously_valid_bundle(self):
        output = self.root / "bundle"
        prepare(self.plan_path, self.pilot, self.sources, self.cards,
                self.cases, self.reviews, output, budget=self.budget)
        from sweep.runtime import sha256_file
        write_json(output / "supersession.json", {
            "schema_version": 1, "kind": "skill-formal-bundle-supersession",
            "status": "superseded-for-stage-e",
            "prior_bundle_sha256": sha256_file(output / "formal-start-bundle.json"),
            "replacement_stage": "stage-e-ten-risk-prevalidation",
            "stage_master_sha256": "a" * 64,
            "stage_authorization_sha256": "b" * 64,
            "formal_target_calls": 0, "judge_calls": 0})
        with self.assertRaisesRegex(ValueError, "superseded for stage E"):
            verify(output)


if __name__ == "__main__":
    unittest.main()
