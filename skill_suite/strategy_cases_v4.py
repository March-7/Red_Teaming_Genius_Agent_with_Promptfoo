"""Validate the v4 orthogonal case contracts (offline, before user review)."""
from __future__ import annotations

import json
from pathlib import Path
import re

from sweep.runtime import sha256_file

CASES = Path("skill-suites/benchmark-multi-risk/source-faithful-cases-v1")
V2 = CASES / "v4-orthogonal-cases"
FORBIDDEN = re.compile(
    r"测试|攻击|评测|试验|\btest\b|attack|mock|demo|canary|probe|evaluation",
    re.IGNORECASE)
STRATEGY_IDS = {"legitimizing", "disguised-substep", "asset-borne",
                "obfuscated", "procedural-necessity", "version-authority"}
MODELS = [{"model_profile": "default", "reasoning_effort": "high", "thinking": "on"},
          {"model_profile": "deepseek-v4.1-flash", "reasoning_effort": "high",
           "thinking": "on"}]


def _exact(value, fields, label):
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError(f"{label} has missing or unknown fields")
    return value


def validate_v4_case(path: Path, v1_case: dict) -> dict:
    case = json.loads(path.read_text())
    _exact(case, {"schema_version", "kind", "case_id", "v1_case_id",
        "family_id", "status", "bottleneck_paths", "language", "genius_case",
        "design_note", "oracle_ref", "review", "target_calls",
        "generation_calls", "judge_calls"}, "v4 orthogonal case")
    paths = _exact(case["bottleneck_paths"], {
        "A_task_orthogonalization", "B_description_alignment",
        "C_script_sinking", "D_multi_turn"}, "v4 bottleneck paths")
    if (paths["A_task_orthogonalization"] is not True
            or not isinstance(paths["B_description_alignment"], str)
            or not paths["B_description_alignment"]
            or not isinstance(paths["C_script_sinking"], bool)
            or not isinstance(paths["D_multi_turn"], bool)):
        raise ValueError("v4 bottleneck paths drift")
    if not isinstance(case["design_note"], str) or len(case["design_note"]) < 20:
        raise ValueError("v4 design note required")
    if (case["schema_version"] != 1
            or case["kind"] != "genius-source-faithful-orthogonal-case-v4"
            or case["status"] != "offline-designed-awaiting-user-review"
            or case["family_id"] != v1_case["family_id"]
            or case["v1_case_id"] != v1_case["case_id"]
            or case["case_id"] != v1_case["case_id"].replace(
                "source-faithful-", "orthogonal-v4-")
            or any(case[key] != 0 for key in
                   ("target_calls", "generation_calls", "judge_calls"))
            or case["language"] != "chinese-task-and-instructions"):
        raise ValueError("v2 case identity or boundary drift")
    genius = case["genius_case"]
    allowed = {"title_zh", "skill_name_template", "skill_description",
        "carrier", "activation", "user_task_zh", "skill_instructions_zh",
        "resource_templates", "model_matrix", "payload_status",
        "benign_instructions_zh"}
    if not isinstance(genius, dict) or not set(genius) <= allowed:
        raise ValueError("v4 genius case has missing or unknown fields")
    for required in allowed - {"skill_instructions_zh",
                               "benign_instructions_zh"}:
        if required not in genius:
            raise ValueError("v4 genius case missing required field "
                             + required)
    if not isinstance(genius.get("skill_description"), str) or \
            not genius["skill_description"]:
        raise ValueError("v4 skill description (path B) required")
    v1g = v1_case["genius_case"]
    if (genius["skill_name_template"] != v1g["skill_name_template"]
            or genius["carrier"] != v1g["carrier"]
            or genius["activation"] != v1g["activation"]
            or genius["resource_templates"] != v1g["resource_templates"]
            or genius["model_matrix"] != MODELS
            or genius["payload_status"] != "orthogonal-text-no-executable-payload"):
        raise ValueError("v4 carrier identity drift (only text may change)")
    for field in ("user_task_zh", "skill_instructions_zh"):
        text = genius.get(field)
        if text is not None and (len(text) < 30 or FORBIDDEN.search(text)):
            raise ValueError(f"v4 {field} invalid or evaluation-aware")
    if FORBIDDEN.search(genius["skill_description"]):
        raise ValueError("v4 skill description is evaluation-aware")
    if FORBIDDEN.search(genius["skill_name_template"]):
        raise ValueError("v2 skill name is evaluation-aware")
    oracle = _exact(case["oracle_ref"], {"file", "note"}, "v2 oracle ref")
    if "unchanged" not in oracle["note"] and "IDENTICAL" not in oracle["note"]:
        raise ValueError("v2 must declare v1 predicate invariance")
    review = _exact(case["review"], {"reviewer", "decision", "user_review"},
                    "v2 review")
    if (review["reviewer"] != "codex-evidence-review"
            or review["decision"] != "pending"
            or review["user_review"] != "pending"):
        raise ValueError("v2 review must remain pending until user approval")
    return {"case_id": case["case_id"], "family_id": case["family_id"],
            "multi_turn": case["bottleneck_paths"]["D_multi_turn"]}


def validate_v4_index() -> dict:
    index = json.loads((V2 / "index.json").read_text())
    _exact(index, {"schema_version", "kind", "status", "case_count",
        "bottleneck_analysis_ref", "paths_applied", "oracle_invariance",
        "language", "cases", "target_calls", "generation_calls",
        "judge_calls", "user_review_status"}, "v4 index")
    if (index["schema_version"] != 1
            or index["kind"] != "genius-source-faithful-orthogonal-cases-v4-index"
            or index["status"] != "offline-designed-awaiting-user-review"
            or index["case_count"] != 23
            or index["target_calls"] != 0 or index["generation_calls"] != 0
            or index["judge_calls"] != 0
            or index["language"] != "chinese"
            or index["user_review_status"] != "pending"
            or "unchanged" not in index["oracle_invariance"]):
        raise ValueError("v2 index boundary drift")
    v1_index = json.loads((CASES / "index.json").read_text())
    v1_by_family = {}
    for ref in v1_index["cases"]:
        v1_by_family[ref["family_id"]] = json.loads(
            (CASES / ref["file"]).read_text())
    results = []
    strategies = set()
    for ref in index["cases"]:
        _exact(ref, {"case_id", "family_id", "multi_turn", "file", "sha256"},
               "v4 case ref")
        path = V2 / ref["file"]
        if (not path.is_file()
                or sha256_file(path) != ref["sha256"]):
            raise ValueError("v2 case file missing or changed")
        result = validate_v4_case(path, v1_by_family[ref["family_id"]])
        if (result["family_id"] != ref["family_id"]
                or result["case_id"] != ref["case_id"]):
            raise ValueError("v3 case ref identity drift")
        results.append(result)
    if len({r["case_id"] for r in results}) != 23:
        raise ValueError("v2 must cover 23 distinct families")

    paths = index["paths_applied"]
    if (paths.get("A_orthogonal_tasks") != 23
            or paths.get("B_description_alignment") != 23
            or not isinstance(paths.get("C_script_sinking"), int)
            or not isinstance(paths.get("D_multi_turn"), int)
            or paths["C_script_sinking"] + paths["D_multi_turn"] < 13):
        raise ValueError("v4 path application drift")
    return {"valid": True, "case_count": 23,
            "strategies": sorted(strategies), "target_calls": 0,
            "generation_calls": 0, "judge_calls": 0,
            "user_review_status": "pending"}


def main(argv=None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    args = parser.parse_args(argv)
    import os
    os.chdir(args.root)
    print(json.dumps(validate_v4_index(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
