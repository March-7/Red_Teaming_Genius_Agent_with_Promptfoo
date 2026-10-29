"""Standing-authorized, zero-network master plan for multi-risk pilots."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from sweep.runtime import sha256_file, write_json
from .pilot_cases import CALL_KINDS, STANDING_LIMITS, validate_index as validate_cases


GOAL_THREAD_ID = "01a107ee-c5a4-7232-bfef-c4a5b46a6837"
ORDER = [
    {"model_profile": "default", "variant": "positive"},
    {"model_profile": "deepseek-v4.1-flash", "variant": "positive"},
    {"model_profile": "default", "variant": "normal"},
    {"model_profile": "default", "variant": "attack"},
    {"model_profile": "deepseek-v4.1-flash", "variant": "normal"},
    {"model_profile": "deepseek-v4.1-flash", "variant": "attack"},
]


def _exact(value: Any, fields: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError(f"{label} has missing or unknown fields")
    return value


def validate_authorization(path: Path, pilot_index_path: Path,
                           shortlist_path: Path) -> dict[str, Any]:
    authorization = json.loads(path.read_text())
    _exact(authorization, {"schema_version", "kind", "actor", "decision", "goal_thread_id",
        "effective_date", "pilot_index_sha256", "shortlist_sha256", "limits",
        "allowed_actions", "excluded_actions", "clarification_approval_unknown_terminal",
        "status"}, "standing authorization")
    if (authorization["schema_version"] != 1
            or authorization["kind"] != "genius-skill-pilot-standing-authorization"
            or authorization["actor"] != "human-user"
            or authorization["decision"] != "start-bounded-preparation-pilots"
            or authorization["goal_thread_id"] != GOAL_THREAD_ID
            or authorization["pilot_index_sha256"] != sha256_file(pilot_index_path)
            or authorization["shortlist_sha256"] != sha256_file(shortlist_path)
            or authorization["limits"] != {"max_candidate_risk_families": 10, **STANDING_LIMITS}
            or authorization["status"] != "active"):
        raise ValueError("standing pilot authorization drift")
    if set(authorization["excluded_actions"]) != {
            "generation", "judge", "formal-target", "external-publication",
            "commit", "push", "non-owned-resource", "real-sensitive-data"}:
        raise ValueError("standing authorization exclusions drift")
    if set(authorization["allowed_actions"]) != {
            "public-source-audit", "local-implementation", "private-skill-create-read",
            "general-session-create", "run-owned-synthetic-asset-manage",
            "positive-normal-attack-target", "receiver-synthetic-nonce",
            "read-only-recovery", "run-owned-cleanup"}:
        raise ValueError("standing authorization allowed actions drift")
    handling = authorization["clarification_approval_unknown_terminal"]
    if handling != {"clarification": "frozen-values-or-invalidate-row",
                    "approval": "mark-approval-blocked-and-continue",
                    "unknown_terminal": "read-only-recovery-no-resubmit"}:
        raise ValueError("standing authorization handling drift")
    return authorization


def prepare(pilot_index_path: Path, authorization_path: Path, shortlist_path: Path,
            output: Path, *, project_root: Path, card_index_path: Path,
            capability_path: Path, source_registry_path: Path, source_inventory_path: Path,
            source_inventory_summary_path: Path, relationship_summary_path: Path) -> dict[str, Any]:
    if output.exists() or not output.parent.is_dir():
        raise ValueError("new pilot master plan path required")
    cases_result = validate_cases(pilot_index_path, project_root=project_root,
        shortlist_path=shortlist_path, card_index_path=card_index_path,
        capability_path=capability_path, source_registry_path=source_registry_path,
        source_inventory_path=source_inventory_path,
        source_inventory_summary_path=source_inventory_summary_path,
        relationship_summary_path=relationship_summary_path)
    authorization = validate_authorization(authorization_path, pilot_index_path, shortlist_path)
    pilot_index = json.loads(pilot_index_path.read_text())
    workers = []
    for position, ref in enumerate(pilot_index["cases"]):
        case_path = pilot_index_path.parent / ref["file"]
        case = json.loads(case_path.read_text())
        workers.append({"position": position, "case_id": case["case_id"],
            "risk_family": case["risk_family"], "case_file": str(case_path.resolve()),
            "case_sha256": ref["sha256"], "call_order": ORDER,
            "limits": case["limits"], "resource_caps": {"private_skills": 6,
                "general_sessions": 6, "projects": 0,
                "initial_asset_scopes": 6 if case["initial_assets"] else 0,
                "receivers": 1 if case["resource_templates"]["receiver_name"] else 0},
            "data_flow": {"genius": "frozen task, private Skill, synthetic inputs and run-owned assets",
                "receiver": ("case nonce and synthetic marker only" if
                    case["case_id"] == "receiver-exfiltration" else
                    "case nonce only" if case["resource_templates"]["receiver_name"] else "none"),
                "generation_provider": "none", "judge_provider": "none",
                "credentials_or_raw_trace_externalized": False},
            "status": "not-started"})
    plan = {"schema_version": 1, "kind": "genius-skill-multi-risk-pilot-master",
        "evaluation_stage": "pilot", "target_context": "global-general",
        "session_type": "general", "retry": 0, "max_concurrency": 1,
        "pilot_index_file": str(pilot_index_path.resolve()),
        "pilot_index_sha256": sha256_file(pilot_index_path),
        "authorization_file": str(authorization_path.resolve()),
        "authorization_sha256": sha256_file(authorization_path),
        "standing_limits": authorization["limits"],
        "planned_limits": cases_result["planned_limits"],
        "workers": workers, "worker_count": len(workers),
        "actual_calls": dict.fromkeys(CALL_KINDS, 0),
        "common_ledger": "ignored-run/pilot-standing-ledger.json",
        "stop_conditions": ["standing-budget-exhausted", "non-owned-resource",
            "real-sensitive-data", "guard-hit", "credential-requires-user-login",
            "source-or-case-hash-drift"],
        "execution_status": "standing-authorized-not-started",
        "formal_asr_eligible": False}
    write_json(output, plan)
    return dry_run(output, authorization_path, shortlist_path,
        project_root=project_root, card_index_path=card_index_path,
        capability_path=capability_path, source_registry_path=source_registry_path,
        source_inventory_path=source_inventory_path,
        source_inventory_summary_path=source_inventory_summary_path,
        relationship_summary_path=relationship_summary_path)


def dry_run(plan_path: Path, authorization_path: Path, shortlist_path: Path, *,
            project_root: Path, card_index_path: Path, capability_path: Path,
            source_registry_path: Path, source_inventory_path: Path,
            source_inventory_summary_path: Path, relationship_summary_path: Path) -> dict[str, Any]:
    plan = json.loads(plan_path.read_text())
    _exact(plan, {"schema_version", "kind", "evaluation_stage", "target_context",
        "session_type", "retry", "max_concurrency", "pilot_index_file", "pilot_index_sha256",
        "authorization_file", "authorization_sha256", "standing_limits", "planned_limits",
        "workers", "worker_count", "actual_calls", "common_ledger", "stop_conditions",
        "execution_status", "formal_asr_eligible"}, "pilot master plan")
    pilot_index_path = Path(plan["pilot_index_file"])
    authorization = validate_authorization(authorization_path, pilot_index_path, shortlist_path)
    cases_result = validate_cases(pilot_index_path, project_root=project_root,
        shortlist_path=shortlist_path, card_index_path=card_index_path,
        capability_path=capability_path, source_registry_path=source_registry_path,
        source_inventory_path=source_inventory_path,
        source_inventory_summary_path=source_inventory_summary_path,
        relationship_summary_path=relationship_summary_path)
    if (plan["schema_version"] != 1 or plan["kind"] != "genius-skill-multi-risk-pilot-master"
            or plan["evaluation_stage"] != "pilot" or plan["target_context"] != "global-general"
            or plan["session_type"] != "general" or plan["retry"] != 0
            or plan["max_concurrency"] != 1
            or plan["pilot_index_sha256"] != sha256_file(pilot_index_path)
            or plan["authorization_file"] != str(authorization_path.resolve())
            or plan["authorization_sha256"] != sha256_file(authorization_path)
            or plan["standing_limits"] != authorization["limits"]
            or plan["planned_limits"] != cases_result["planned_limits"]
            or plan["worker_count"] != 10 or len(plan["workers"]) != 10
            or plan["actual_calls"] != dict.fromkeys(CALL_KINDS, 0)
            or plan["execution_status"] != "standing-authorized-not-started"
            or plan["formal_asr_eligible"] is not False):
        raise ValueError("pilot master plan drift")
    case_refs = json.loads(pilot_index_path.read_text())["cases"]
    for position, (worker, ref) in enumerate(zip(plan["workers"], case_refs)):
        case_path = pilot_index_path.parent / ref["file"]
        if (worker["position"] != position or worker["case_file"] != str(case_path.resolve())
                or worker["case_sha256"] != sha256_file(case_path)
                or worker["call_order"] != ORDER or worker["status"] != "not-started"
                or worker["limits"]["generation"] != 0 or worker["limits"]["judge"] != 0
                or worker["limits"]["retry"] != 0
                or worker["data_flow"]["credentials_or_raw_trace_externalized"] is not False):
            raise ValueError("pilot worker source, order, budget, or data flow drift")
    return {"valid": True, "worker_count": 10, "call_order_rows": 60,
            "planned_limits": plan["planned_limits"],
            "remaining_after_plans": cases_result["remaining_after_plans"],
            "actual_calls": dict(plan["actual_calls"]), "network_calls": 0,
            "credential_reads": 0, "generation_calls": 0, "judge_calls": 0,
            "formal_asr_eligible": False}


def _args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--authorization", type=Path, required=True)
    parser.add_argument("--shortlist", type=Path, required=True)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--card-index", type=Path, required=True)
    parser.add_argument("--capabilities", type=Path, required=True)
    parser.add_argument("--sources", type=Path, required=True)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--inventory-summary", type=Path, required=True)
    parser.add_argument("--relationships", type=Path, required=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "dry-run"))
    _args(parser)
    parser.add_argument("--pilot-index", type=Path)
    args = parser.parse_args(argv)
    kwargs = {"project_root": args.project_root, "card_index_path": args.card_index,
        "capability_path": args.capabilities, "source_registry_path": args.sources,
        "source_inventory_path": args.inventory,
        "source_inventory_summary_path": args.inventory_summary,
        "relationship_summary_path": args.relationships}
    if args.command == "prepare":
        if args.pilot_index is None:
            raise ValueError("prepare requires --pilot-index")
        result = prepare(args.pilot_index, args.authorization, args.shortlist, args.plan, **kwargs)
    else:
        result = dry_run(args.plan, args.authorization, args.shortlist, **kwargs)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
