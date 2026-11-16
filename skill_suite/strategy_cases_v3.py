"""Validate the v3 strategy case contracts (offline, before user review)."""
from __future__ import annotations

import json
from pathlib import Path
import re

from sweep.runtime import sha256_file

CASES = Path("skill-suites/benchmark-multi-risk/source-faithful-cases-v1")
V2 = CASES / "v3-strategy-cases"
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


def validate_v3_case(path: Path, v1_case: dict) -> dict:
    case = json.loads(path.read_text())
    _exact(case, {"schema_version", "kind", "case_id", "v1_case_id",
        "family_id", "status", "strategy", "provenance", "language",
        "genius_case", "oracle_ref", "review", "target_calls",
        "generation_calls", "judge_calls"}, "v3 strategy case")
    provenance = _exact(case["provenance"], {"source", "attacker_model",
        "attempt", "reviewer"}, "v3 provenance")
    if (provenance["source"] not in
            {"attacker-glm-5.3-flash", "attacker-abliterated-glm-5.3",
             "hand-designed-v2-retain"}
            or provenance["reviewer"] != "codex-evidence-review"):
        raise ValueError("v3 provenance drift")
    if (case["schema_version"] != 1
            or case["kind"] != "genius-source-faithful-strategy-case-v3"
            or case["status"] != "offline-designed-awaiting-user-review"
            or case["family_id"] != v1_case["family_id"]
            or case["v1_case_id"] != v1_case["case_id"]
            or case["case_id"] != v1_case["case_id"].replace(
                "source-faithful-", "strategy-v3-")
            or any(case[key] != 0 for key in
                   ("target_calls", "generation_calls", "judge_calls"))
            or case["language"] != "chinese-task-and-instructions"):
        raise ValueError("v2 case identity or boundary drift")
    strategy = _exact(case["strategy"], {"strategy_id", "upstream_ref", "note"},
                      "v2 strategy")
    if (strategy["strategy_id"] not in STRATEGY_IDS
            or not strategy["upstream_ref"] or not strategy["note"]):
        raise ValueError("v2 strategy reference drift")
    genius = case["genius_case"]
    allowed = {"title_zh", "skill_name_template", "carrier", "activation",
        "user_task_zh", "skill_instructions_zh", "resource_templates",
        "model_matrix", "payload_status",
        # optional per-design keys:
        "encoded_directive_template", "benign_instructions_zh"}
    if not isinstance(genius, dict) or not set(genius) <= allowed:
        raise ValueError("v2 genius case has missing or unknown fields")
    for required in allowed - {"encoded_directive_template",
                               "benign_instructions_zh"}:
        if required not in genius:
            raise ValueError("v2 genius case missing required field "
                             + required)
    v1g = v1_case["genius_case"]
    if (genius["skill_name_template"] != v1g["skill_name_template"]
            or genius["carrier"] != v1g["carrier"]
            or genius["activation"] != v1g["activation"]
            or genius["resource_templates"] != v1g["resource_templates"]
            or genius["model_matrix"] != MODELS
            or genius["payload_status"] != "strategy-text-no-executable-payload"):
        raise ValueError("v2 carrier identity drift (only text may change)")
    if "encoded_directive_template" in genius:
        if not isinstance(genius["encoded_directive_template"], str):
            raise ValueError("v2 encoded directive must be a string")
    for field in ("user_task_zh", "skill_instructions_zh"):
        text = genius[field]
        if (not isinstance(text, str) or len(text) < 30
                or FORBIDDEN.search(text)):
            raise ValueError(f"v2 {field} empty, too short, or "
                             "evaluation-aware")
    if FORBIDDEN.search(genius["skill_name_template"]):
        raise ValueError("v2 skill name is evaluation-aware")
    if "benign_instructions_zh" in genius and (
            not isinstance(genius["benign_instructions_zh"], str)
            or FORBIDDEN.search(genius["benign_instructions_zh"])):
        raise ValueError("v2 benign instructions invalid")
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
            "strategy": strategy["strategy_id"]}


def validate_v3_index() -> dict:
    index = json.loads((V2 / "index.json").read_text())
    _exact(index, {"schema_version", "kind", "status", "case_count",
        "attacker_model", "accepted_attacker_proposals", "v2_fallbacks",
        "rejected_proposals", "delivery_fix", "oracle_invariance",
        "language", "cases", "target_calls", "generation_calls",
        "judge_calls", "user_review_status"}, "v3 index")
    if (index["schema_version"] != 1
            or index["kind"] != "genius-source-faithful-strategy-cases-v3-index"
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
        _exact(ref, {"case_id", "family_id", "source", "file", "sha256"},
               "v3 case ref")
        path = V2 / ref["file"]
        if (not path.is_file()
                or sha256_file(path) != ref["sha256"]):
            raise ValueError("v2 case file missing or changed")
        result = validate_v3_case(path, v1_by_family[ref["family_id"]])
        if (result["family_id"] != ref["family_id"]
                or result["case_id"] != ref["case_id"]):
            raise ValueError("v3 case ref identity drift")
        results.append(result)
    if len({r["case_id"] for r in results}) != 23:
        raise ValueError("v2 must cover 23 distinct families")

    if index["accepted_attacker_proposals"] + index["v2_fallbacks"] != 23:
        raise ValueError("v3 provenance split must cover 23 cases")
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
    print(json.dumps(validate_v3_index(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
