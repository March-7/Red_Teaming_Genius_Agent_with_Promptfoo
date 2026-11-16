"""Offline contracts for the v2 strategy case set."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from skill_suite.strategy_cases_v2 import (V2, validate_v2_case,
                                           validate_v2_index)
from sweep.runtime import write_json


ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "skill-suites/benchmark-multi-risk/source-faithful-cases-v1"


class StrategyCasesV2Contract(unittest.TestCase):
    def test_real_v2_index_valid_and_strategy_anchored(self):
        result = validate_v2_index()
        self.assertEqual(result["case_count"], 23)
        self.assertEqual((result["target_calls"], result["generation_calls"],
                          result["judge_calls"]), (0, 0, 0))
        self.assertEqual(result["user_review_status"], "pending")
        self.assertLessEqual(set(result["strategies"]),
            {"legitimizing", "disguised-substep", "asset-borne",
             "obfuscated", "procedural-necessity", "version-authority"})
        index = json.loads((V2 / "index.json").read_text())
        self.assertIn("skill-inject", json.dumps(index["strategy_sources"]))

    def test_carrier_drift_between_v1_and_v2_fails(self):
        index = json.loads((V2 / "index.json").read_text())
        v1_index = json.loads((CASES / "index.json").read_text())
        v1_by_family = {ref["family_id"]: json.loads(
            (CASES / ref["file"]).read_text()) for ref in v1_index["cases"]}
        ref = next(r for r in index["cases"]
                   if r["family_id"] == "artifact-leakage")
        case = json.loads((V2 / ref["file"]).read_text())
        case["genius_case"]["carrier"] = "text-skill"  # drift!
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "case.json"
            write_json(path, case)
            with self.assertRaisesRegex(ValueError, "carrier identity drift"):
                validate_v2_case(path, v1_by_family["artifact-leakage"])

    def test_evaluation_awareness_in_task_fails(self):
        index = json.loads((V2 / "index.json").read_text())
        v1_index = json.loads((CASES / "index.json").read_text())
        v1_by_family = {ref["family_id"]: json.loads(
            (CASES / ref["file"]).read_text()) for ref in v1_index["cases"]}
        ref = next(r for r in index["cases"]
                   if r["family_id"] == "ransomware")
        case = json.loads((V2 / ref["file"]).read_text())
        case["genius_case"]["user_task_zh"] = (
            "请使用技能完成归档测试，这是一个攻击评测样本。")
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "case.json"
            write_json(path, case)
            with self.assertRaisesRegex(ValueError, "evaluation-aware"):
                validate_v2_case(path, v1_by_family["ransomware"])

    def test_online_boundary_is_zero(self):
        for ref in json.loads((V2 / "index.json").read_text())["cases"]:
            case = json.loads((V2 / ref["file"]).read_text())
            self.assertEqual((case["target_calls"],
                              case["generation_calls"],
                              case["judge_calls"]), (0, 0, 0))


if __name__ == "__main__":
    unittest.main()
