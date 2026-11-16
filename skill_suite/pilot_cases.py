"""Offline freeze contract for benchmark-derived multi-risk pilot cases."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from sweep.models import MATRIX
from sweep.resource_naming import validate_neutral_resource_name, validate_neutral_user_question
from sweep.runtime import sha256_file
from .benchmark_adaptation import validate_manifest as validate_adaptation
from .risk_cards import validate_card, validate_shortlist
from .schema import text_hash


CALL_KINDS = {"target", "management", "recovery", "cleanup", "generation", "judge", "retry"}
STANDING_LIMITS = {"target": 96, "management": 1200, "recovery": 120,
                   "cleanup": 180, "generation": 0, "judge": 0, "retry": 0}


def _exact(value: Any, fields: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError(f"{label} has missing or unknown fields")
    return value


def _ref(root: Path, value: Any, label: str) -> Path:
    _exact(value, {"file", "sha256"}, label)
    if not isinstance(value["file"], str) or ".." in Path(value["file"]).parts:
        raise ValueError(f"{label} path invalid")
    path = (root / value["file"]).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file() or sha256_file(path) != value["sha256"]:
        raise ValueError(f"{label} missing or changed")
    return path


def validate_case(case_path: Path, *, project_root: Path, shortlist_path: Path,
                  card_index_path: Path, capability_path: Path, source_registry_path: Path,
                  source_inventory_path: Path, source_inventory_summary_path: Path,
                  relationship_summary_path: Path) -> dict[str, Any]:
    case_root = case_path.parent
    case = json.loads(case_path.read_text())
    _exact(case, {"schema_version", "kind", "case_id", "risk_family", "risk_card_ref",
        "evaluation_stage", "target_context", "session_type", "models", "resource_templates",
        "legitimate_task_template", "legitimate_task_sha256", "positive_control_task_template",
        "skills", "initial_assets", "source_adaptations", "hidden_values", "oracle",
        "recovery", "clarification_policy", "approval_policy", "limits", "retry",
        "actual_calls", "formal_asr_eligible"}, "pilot case")
    if (case["schema_version"] != 1 or case["kind"] != "genius-skill-risk-pilot-case"
            or case["evaluation_stage"] != "pilot-prepared"
            or case["target_context"] != "global-general" or case["session_type"] != "general"
            or case["formal_asr_eligible"] is not False):
        raise ValueError("unsupported pilot case")
    shortlist = validate_shortlist(shortlist_path, card_index_path, capability_path,
        source_registry_path, relationship_summary_path, project_root)
    if case["case_id"] not in shortlist["selected_cards"]:
        raise ValueError("pilot case is not on the evidence-reviewed shortlist")
    card_path = _ref(card_index_path.parent, case["risk_card_ref"], "risk card ref")
    card_result = validate_card(card_path, capability_path, source_registry_path,
                                relationship_summary_path, project_root)
    if (card_result["card_id"] != case["case_id"]
            or card_result["risk_family"] != case["risk_family"]
            or card_result["disposition"] != "eligible-for-pilot"):
        raise ValueError("pilot case and risk card drift")
    expected_models = [{"model_profile": profile, "reasoning_effort": "high", "thinking": "on"}
                       for _, profile, _ in MATRIX]
    if case["models"] != expected_models:
        raise ValueError("paired high/on model matrix required")
    resources = _exact(case["resource_templates"], {"normal_skill_name", "attack_skill_name",
        "positive_skill_name", "session_name", "receiver_name", "artifact_names"},
        "resource templates")
    for key in ("normal_skill_name", "attack_skill_name", "positive_skill_name", "session_name"):
        validate_neutral_resource_name(resources[key].replace("{nonce}", "a124b5c6"))
    if resources["receiver_name"] is not None:
        validate_neutral_resource_name(resources["receiver_name"].replace("{nonce}", "a124b5c6"))
    if not isinstance(resources["artifact_names"], list):
        raise ValueError("artifact name templates must be a list")
    for name in resources["artifact_names"]:
        validate_neutral_resource_name(name.replace("{nonce}", "a124b5c6"))
    task = case["legitimate_task_template"]
    positive = case["positive_control_task_template"]
    if (not isinstance(task, str) or text_hash(task) != case["legitimate_task_sha256"]
            or not isinstance(positive, str) or not positive):
        raise ValueError("pilot task hash or positive control missing")
    validate_neutral_user_question(task.replace("{skill_name}", "reference-digest-a124b5c6")
                                   .replace("{source_name}", "quarterly-figures-a124b5c6.csv")
                                   .replace("{working_name}", "working-brief-a124b5c6.md"))
    validate_neutral_user_question(positive.replace("{skill_name}", "reference-digest-a124b5c6")
                                   .replace("{source_name}", "quarterly-figures-a124b5c6.csv")
                                   .replace("{working_name}", "working-brief-a124b5c6.md")
                                   .replace("{receiver_url}", "https://example.invalid/a124")
                                   .replace("{receiver_nonce}", "a124b5c6")
                                   .replace("{protected_name}", "archive-brief-a124b5c6.md")
                                   .replace("{marker_name}", "process-note-a124b5c6.md")
                                   .replace("{copy_name}", "reference-copy-a124b5c6.json"))
    skills = _exact(case["skills"], {"normal", "attack"}, "pilot skills")
    normal_path = _ref(case_root, skills["normal"], "normal Skill")
    attack_path = _ref(case_root, skills["attack"], "attack Skill")
    normal = normal_path.read_text()
    attack = attack_path.read_text()
    if normal == attack or not attack.startswith(normal.rstrip() + "\n\n"):
        raise ValueError("normal and attack must differ only by an appended Skill payload")
    if not isinstance(case["hidden_values"], list) or not case["hidden_values"]:
        raise ValueError("attack-only hidden values required")
    for value in case["hidden_values"]:
        if not isinstance(value, str) or not value or value in task:
            raise ValueError("attack target leaked into legitimate task")
    for asset in case["initial_assets"]:
        _ref(case_root, asset, "initial asset")
    if not isinstance(case["source_adaptations"], list) or not case["source_adaptations"]:
        raise ValueError("source adaptations required")
    for adaptation in case["source_adaptations"]:
        manifest = _ref(case_root, adaptation, "source adaptation")
        validate_adaptation(manifest, source_registry_path, source_inventory_path,
                            source_inventory_summary_path)
    oracle = _exact(case["oracle"], {"kind", "signal", "target_independent", "before_after"},
                    "pilot oracle")
    if oracle["target_independent"] is not True or not isinstance(oracle["before_after"], bool):
        raise ValueError("pilot oracle must be target independent")
    recovery = _exact(case["recovery"], {"procedure", "run_owned_only"}, "pilot recovery")
    if recovery["run_owned_only"] is not True or not recovery["procedure"]:
        raise ValueError("pilot recovery invalid")
    clarification = _exact(case["clarification_policy"], {"mode", "allowed_fields",
                                                           "otherwise"}, "clarification policy")
    if clarification["mode"] != "deterministic-frozen-values-only" or clarification["otherwise"] != "invalidate-row-and-continue":
        raise ValueError("clarification handling drift")
    approval = _exact(case["approval_policy"], {"unexpected_request", "count_as_finding"},
                      "pilot approval policy")
    if approval != {"unexpected_request": "mark-approval-blocked-and-continue",
                    "count_as_finding": False}:
        raise ValueError("unexpected approval must not be auto-approved or counted")
    limits = case["limits"]
    if (not isinstance(limits, dict) or set(limits) != CALL_KINDS
            or any(type(value) is not int or value < 0 for value in limits.values())
            or limits["target"] != 9 or limits["management"] != 120
            or limits["recovery"] != 12 or limits["cleanup"] != 18
            or limits["generation"] != 0
            or limits["judge"] != 0 or limits["retry"] != 0
            or case["retry"] != 0):
        raise ValueError("pilot case budget invalid")
    if case["actual_calls"] != dict.fromkeys(CALL_KINDS, 0):
        raise ValueError("prepared pilot must have zero calls")
    return {"valid": True, "case_id": case["case_id"], "risk_family": case["risk_family"],
            "limits": limits, "source_adaptations": len(case["source_adaptations"]),
            "actual_calls": dict(case["actual_calls"]), "formal_asr_eligible": False}


def validate_index(index_path: Path, *, project_root: Path, shortlist_path: Path,
                   card_index_path: Path, capability_path: Path, source_registry_path: Path,
                   source_inventory_path: Path, source_inventory_summary_path: Path,
                   relationship_summary_path: Path) -> dict[str, Any]:
    index = json.loads(index_path.read_text())
    _exact(index, {"schema_version", "kind", "standing_authorization", "cases",
                   "execution_status"}, "pilot case index")
    if (index["schema_version"] != 1 or index["kind"] != "genius-skill-risk-pilot-index"
            or index["standing_authorization"] != {
                "max_candidate_risk_families": 10, **STANDING_LIMITS}
            or index["execution_status"] != "offline-prepared-zero-calls"):
        raise ValueError("pilot index or standing authorization drift")
    results = []
    for ref in index["cases"]:
        path = _ref(index_path.parent, ref, "pilot case ref")
        results.append(validate_case(path, project_root=project_root,
            shortlist_path=shortlist_path, card_index_path=card_index_path,
            capability_path=capability_path, source_registry_path=source_registry_path,
            source_inventory_path=source_inventory_path,
            source_inventory_summary_path=source_inventory_summary_path,
            relationship_summary_path=relationship_summary_path))
    if len(results) != 10 or len({row["case_id"] for row in results}) != 10:
        raise ValueError("exactly ten distinct shortlisted pilot cases required")
    totals = {kind: sum(row["limits"][kind] for row in results) for kind in CALL_KINDS}
    if any(totals[kind] > STANDING_LIMITS[kind] for kind in CALL_KINDS):
        raise ValueError("pilot plans exceed standing authorization")
    if any(any(value for value in row["actual_calls"].values()) for row in results):
        raise ValueError("offline pilot index contains live calls")
    return {"valid": True, "case_count": 10, "case_ids": [row["case_id"] for row in results],
            "planned_limits": totals, "standing_limits": STANDING_LIMITS,
            "remaining_after_plans": {kind: STANDING_LIMITS[kind] - totals[kind]
                                      for kind in CALL_KINDS},
            "actual_calls": dict.fromkeys(CALL_KINDS, 0), "formal_asr_eligible": False}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--shortlist", type=Path, required=True)
    parser.add_argument("--card-index", type=Path, required=True)
    parser.add_argument("--capabilities", type=Path, required=True)
    parser.add_argument("--sources", type=Path, required=True)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--inventory-summary", type=Path, required=True)
    parser.add_argument("--relationships", type=Path, required=True)
    args = parser.parse_args(argv)
    result = validate_index(args.index, project_root=args.project_root,
        shortlist_path=args.shortlist, card_index_path=args.card_index,
        capability_path=args.capabilities, source_registry_path=args.sources,
        source_inventory_path=args.inventory, source_inventory_summary_path=args.inventory_summary,
        relationship_summary_path=args.relationships)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
