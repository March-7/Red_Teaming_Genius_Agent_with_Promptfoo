"""Offline contracts for the v4 strategy case set (attacker-proposed)."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from skill_suite.strategy_cases_v4 import validate_v4_case
from sweep.runtime import write_json


ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "skill-suites/benchmark-multi-risk/source-faithful-cases-v1"
V4 = CASES / "v4-orthogonal-cases"


class StrategyCasesV4Contract(unittest.TestCase):
    def test_real_v4_index_valid_and_attacker_split_covers_23(self):
        from skill_suite.strategy_cases_v4 import validate_v4_index
        result = validate_v4_index()
        self.assertEqual(result["case_count"], 23)
        self.assertEqual((result["target_calls"],
                          result["generation_calls"],
                          result["judge_calls"]), (0, 0, 0))
        index = json.loads((V4 / "index.json").read_text())
        self.assertEqual(index["paths_applied"]["A_orthogonal_tasks"], 23)
        self.assertEqual(index["paths_applied"]["B_description_alignment"], 23)

    def test_all_23_cases_preserve_v1_identity_invariants(self):
        v1_index = json.loads((CASES / "index.json").read_text())
        for ref in v1_index["cases"]:
            v1 = json.loads((CASES / ref["file"]).read_text())
            v4 = json.loads(
                (V4 / ref["file"].replace("source-faithful-",
                                          "orthogonal-v4-")).read_text())
            g1, g3 = v1["genius_case"], v4["genius_case"]
            self.assertEqual(g3["carrier"], g1["carrier"])
            self.assertEqual(g3["skill_name_template"],
                             g1["skill_name_template"])
            self.assertEqual(g3["resource_templates"],
                             g1["resource_templates"])
            self.assertEqual(g3["model_matrix"], g1["model_matrix"])

    def test_bottleneck_paths_and_carrier_drift_fail_closed(self):
        v1_index = json.loads((CASES / "index.json").read_text())
        ref = next(r for r in v1_index["cases"]
                   if r["family_id"] == "role-hijack")
        v1 = json.loads((CASES / ref["file"]).read_text())
        v4 = json.loads(
            (V4 / "orthogonal-v4-role-hijack-01.json").read_text())
        v4["bottleneck_paths"]["A_task_orthogonalization"] = False
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "case.json"
            write_json(path, v4)
            with self.assertRaisesRegex(ValueError, "bottleneck paths drift"):
                validate_v4_case(path, v1)
        v4["bottleneck_paths"]["A_task_orthogonalization"] = True
        v4["genius_case"]["carrier"] = "package-script"
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "case.json"
            write_json(path, v4)
            with self.assertRaisesRegex(ValueError, "carrier identity drift"):
                validate_v4_case(path, v1)

    def test_attacker_proposals_have_no_evaluation_awareness(self):
        import re
        FORBIDDEN = re.compile(
            r"测试|攻击|评测|试验|红队|payload|\btest\b|attack|probe"
            r"|evaluation", re.IGNORECASE)
        index = json.loads((V4 / "index.json").read_text())
        for ref in index["cases"]:
            case = json.loads((V4 / ref["file"]).read_text())
            g = case["genius_case"]
            self.assertIsNone(FORBIDDEN.search(g["user_task_zh"]),
                              ref["case_id"])
            instructions = g.get("skill_instructions_zh")
            if instructions is not None:
                self.assertIsNone(FORBIDDEN.search(instructions),
                                  ref["case_id"])


if __name__ == "__main__":
    unittest.main()
