"""Offline contracts for the v3 strategy case set (attacker-proposed)."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from skill_suite.strategy_cases_v3 import validate_v3_case
from sweep.runtime import write_json


ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "skill-suites/benchmark-multi-risk/source-faithful-cases-v1"
V3 = CASES / "v3-strategy-cases"


class StrategyCasesV3Contract(unittest.TestCase):
    def test_real_v3_index_valid_and_attacker_split_covers_23(self):
        from skill_suite.strategy_cases_v3 import validate_v3_index
        result = validate_v3_index()
        self.assertEqual(result["case_count"], 23)
        self.assertEqual((result["target_calls"],
                          result["generation_calls"],
                          result["judge_calls"]), (0, 0, 0))
        index = json.loads((V3 / "index.json").read_text())
        self.assertEqual(index["accepted_attacker_proposals"]
                         + index["v2_fallbacks"], 23)

    def test_all_23_cases_preserve_v1_identity_invariants(self):
        v1_index = json.loads((CASES / "index.json").read_text())
        for ref in v1_index["cases"]:
            v1 = json.loads((CASES / ref["file"]).read_text())
            v3 = json.loads(
                (V3 / ref["file"].replace("source-faithful-",
                                          "strategy-v3-")).read_text())
            g1, g3 = v1["genius_case"], v3["genius_case"]
            self.assertEqual(g3["carrier"], g1["carrier"])
            self.assertEqual(g3["skill_name_template"],
                             g1["skill_name_template"])
            self.assertEqual(g3["resource_templates"],
                             g1["resource_templates"])
            self.assertEqual(g3["model_matrix"], g1["model_matrix"])

    def test_provenance_and_carrier_drift_fail_closed(self):
        v1_index = json.loads((CASES / "index.json").read_text())
        ref = next(r for r in v1_index["cases"]
                   if r["family_id"] == "role-hijack")
        v1 = json.loads((CASES / ref["file"]).read_text())
        v3 = json.loads(
            (V3 / "strategy-v3-role-hijack-01.json").read_text())
        v3["provenance"]["source"] = "unknown-source"
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "case.json"
            write_json(path, v3)
            with self.assertRaisesRegex(ValueError, "provenance"):
                validate_v3_case(path, v1)
        v3["provenance"]["source"] = "attacker-glm-5.3-flash"
        # role-hijack v1 carrier IS text-skill; use a package family for drift
        v3["genius_case"]["carrier"] = "package-script"
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "case.json"
            write_json(path, v3)
            with self.assertRaisesRegex(ValueError, "carrier identity drift"):
                validate_v3_case(path, v1)

    def test_attacker_proposals_have_no_evaluation_awareness(self):
        import re
        FORBIDDEN = re.compile(
            r"测试|攻击|评测|试验|红队|payload|\btest\b|attack|probe"
            r"|evaluation", re.IGNORECASE)
        index = json.loads((V3 / "index.json").read_text())
        for ref in index["cases"]:
            case = json.loads((V3 / ref["file"]).read_text())
            g = case["genius_case"]
            self.assertIsNone(FORBIDDEN.search(g["user_task_zh"]),
                              ref["case_id"])
            self.assertIsNone(FORBIDDEN.search(g["skill_instructions_zh"]),
                              ref["case_id"])


if __name__ == "__main__":
    unittest.main()
