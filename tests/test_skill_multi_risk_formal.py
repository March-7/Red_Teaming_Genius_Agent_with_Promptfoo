"""Multi-risk formal fixture keeps risk denominators and Judge candidates separate."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import unittest

from skill_suite.multi_risk_formal import progress, provisioning_plan, validate_plan
from sweep.runtime import sha256_file, write_json


class MultiRiskFormalContract(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.plan_path = self.root / "plan.json"
        families = ["exfiltration", "credential-copy", "config-tamper", "audit-falsification"]
        sources = ["aig-skilljack", "malskillbench", "skillsbench", "malskillbench"]
        rows = []
        for family_index, (family, source) in enumerate(zip(families, sources)):
            for case_index in range(5):
                case_id = f"{family}-{case_index}"
                normal_hash = f"{family_index + 1:x}" * 64
                for profile_index, profile in enumerate(("default", "deepseek-v4.1-flash")):
                    for variant_index, variant in enumerate(("normal", "attack")):
                        rows.append({"evaluation_key": f"eval-{family_index}-{case_index}-{profile_index}-{variant_index}",
                            "case_id": case_id, "risk_family": family, "source_id": source,
                            "upstream_asset_id": f"asset-{family}-{case_index}",
                            "reuse_tier": "pattern-only" if source != "skillsbench" else "minimal-adaptation",
                            "license_disposition": "research-only" if source == "aig-skilljack" else
                                "academic-research-only" if source == "malskillbench" else "confirmed-open",
                            "model_profile": profile, "variant": variant,
                            "task_sha256": "a" * 64,
                            "skill_sha256": normal_hash if variant == "normal" else "f" * 64,
                            "normal_skill_sha256": normal_hash, "initial_state_sha256": "b" * 64,
                            "oracle_kind": "artifact-bytes", "resource_key": f"resource-{case_id}-{profile_index}-{variant}",
                            "session_key": f"session-{case_id}-{profile_index}-{variant}",
                            "guard_sha256": "c" * 64})
        self.plan = {"schema_version": 1, "kind": "skill-multi-risk-formal-plan",
            "status": "prepared-offline", "target_context": "global-general", "session_type": "general",
            "risk_families": families, "source_registry_sha256": "d" * 64,
            "risk_cards_sha256": "e" * 64, "pilot_summary_sha256": "f" * 64,
            "rows": rows, "case_count": 20, "target_row_count": 80,
            "formal_target_authorized": False, "judge_authorized": False,
            "retry": 0, "max_concurrency": 1}
        write_json(self.plan_path, self.plan)

    def test_matrix_and_provisioner_preserve_multi_risk_source_and_resource_isolation(self):
        checked = validate_plan(self.plan_path)
        self.assertEqual((checked["risk_family_count"], checked["case_count"],
                          checked["target_row_count"]), (4, 20, 80))
        provision = provisioning_plan(self.plan_path)
        self.assertEqual((provision["worker_count"], provision["private_skill_instances"],
                          provision["general_sessions"], provision["projects"]), (20, 80, 80, 0))
        self.assertTrue(all(value == 0 for value in provision["actual_calls"].values()))
        changed = copy.deepcopy(self.plan)
        changed["rows"][1]["session_key"] = changed["rows"][0]["session_key"]
        write_json(self.plan_path, changed)
        with self.assertRaises(ValueError): validate_plan(self.plan_path)

    def test_success_and_fail_closed_families_do_not_mix_denominators_or_judge_effects(self):
        result_rows = []
        for row in self.plan["rows"]:
            status = "evidence-valid"
            task_valid = source_verified = oracle_reliable = True
            effect = review = False
            if row["risk_family"] == "credential-copy" and row["variant"] == "normal":
                status, task_valid = "control-invalid", False
            if (row["risk_family"] == "exfiltration" and row["variant"] == "attack"
                    and row["model_profile"] == "default" and row["case_id"].endswith("-0")):
                effect = review = True
            result_rows.append({"evaluation_key": row["evaluation_key"], "status": status,
                "source_verified": source_verified, "task_valid": task_valid,
                "oracle_reliable": oracle_reliable,
                "independent_effect_observed": effect, "review_confirmed": review})
        judge_key = next(row["evaluation_key"] for row in self.plan["rows"]
                         if row["risk_family"] == "credential-copy" and row["variant"] == "attack")
        results_path = self.root / "results.json"
        write_json(results_path, {"schema_version": 1, "kind": "skill-multi-risk-formal-results",
            "plan_sha256": sha256_file(self.plan_path), "rows": result_rows,
            "judge_candidates": [{"evaluation_key": judge_key, "candidate": True,
                                  "grader_valid": True}],
            "actual_calls": {"target": 80, "management": 640, "recovery": 0,
                             "cleanup": 0, "generation": 0, "judge": 1}})
        report = progress(self.plan_path, results_path)
        self.assertEqual(report["risk_families"]["exfiltration"]["models"]["default"]
                         ["confirmed_effect_numerator"], 1)
        for profile in ("default", "deepseek-v4.1-flash"):
            self.assertEqual(report["risk_families"]["credential-copy"]["models"][profile]
                             ["valid_attack_denominator"], 0)
            self.assertEqual(report["risk_families"]["credential-copy"]["models"][profile]
                             ["confirmed_effect_numerator"], 0)
        self.assertEqual(report["risk_families"]["credential-copy"]["judge_candidate_count"], 1)
        self.assertFalse(report["judge_changes_confirmed_effect"])


if __name__ == "__main__":
    unittest.main()
