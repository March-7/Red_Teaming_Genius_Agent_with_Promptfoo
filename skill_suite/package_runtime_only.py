"""Offline plan and authorization gate for direct package runtime feasibility."""
from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
from typing import Any

from sweep.runtime import durable_json, sha256_file, write_json
from .package_gate_runtime import PackageGateLedger
from .package_skill_gate import build_package
from .stage_e_pilot import TOTAL_LIMITS as GLOBAL_LIMITS


INCREMENT_LIMITS = {"target": 2, "management": 32, "recovery": 4,
                    "cleanup": 6, "generation": 0, "judge": 0, "retry": 0}
PRIOR_COUNTS = {"target": 0, "management": 43, "recovery": 1,
                "cleanup": 9, "generation": 0, "judge": 0, "retry": 0}
TOTAL_STAGE_LIMITS = {"target": 2, "management": 75, "recovery": 5,
                      "cleanup": 15, "generation": 0, "judge": 0, "retry": 0}
EXECUTION_FILES = ("skill_suite/package_skill_gate.py",
                   "skill_suite/package_gate_runtime.py",
                   "skill_suite/package_gate_live.py",
                   "skill_suite/package_runtime_only.py",
                   "skill_suite/package_runtime_only_live.py",
                   "skill_suite/schema.py",
                   "skill_suite/registry.py",
                   "skill_suite/pilot_ledger.py",
                   "skill_suite/http_accounting.py",
                   "sweep/sensitive_output_guard.cjs")


def _exact(value: Any, fields: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError(f"{label} has missing or unknown fields")
    return value


def validate_plan(root: Path, path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text())
    _exact(value, {"schema_version", "kind", "status", "target_context",
        "session_type", "prior_summary_ref", "official_shell_template_ref",
        "source_files", "runtime_contract", "models", "call_order",
        "increment_limits", "total_stage_limits", "global_limits",
        "resource_caps", "excluded_actions", "actual_calls",
        "online_authorization", "formal_asr_eligible"}, "runtime-only package plan")
    if (value["schema_version"] != 1
            or value["kind"] != "genius-package-runtime-only-plan"
            or value["status"] != "prepared-awaiting-online-confirmation"
            or value["target_context"] != "global-general"
            or value["session_type"] != "general"
            or value["increment_limits"] != INCREMENT_LIMITS
            or value["total_stage_limits"] != TOTAL_STAGE_LIMITS
            or value["global_limits"] != GLOBAL_LIMITS
            or value["resource_caps"] != {"private_package_skills": 1,
                "general_sessions": 2, "projects": 0}
            or value["actual_calls"] != PRIOR_COUNTS
            or value["online_authorization"] != "not-authorized"
            or value["formal_asr_eligible"] is not False):
        raise ValueError("runtime-only package plan boundary drift")
    base = root / "skill-suites/benchmark-multi-risk"
    for key in ("prior_summary_ref", "official_shell_template_ref"):
        ref = value[key]
        target = base / ref["file"]
        if not target.is_file() or sha256_file(target) != ref["sha256"]:
            raise ValueError("runtime-only source ref drift")
    for ref in value["source_files"]:
        target = path.parent / ref["file"]
        if not target.is_file() or sha256_file(target) != ref["sha256"]:
            raise ValueError("runtime-only package source drift")
    if (value["models"] != [
            {"model_profile": "default", "reasoning_effort": "high", "thinking": "on"},
            {"model_profile": "deepseek-v4.1-flash", "reasoning_effort": "high",
             "thinking": "on"}]
            or value["call_order"] != ["package-build", "validate", "confirm",
                "read-sharing", "create-two-sessions", "wait-90s",
                "qwen-target", "deepseek-target", "cleanup"]
            or set(value["excluded_actions"]) != {"package-download", "package-test",
                "generation", "judge", "formal-target", "retry", "publish", "share",
                "project-workspace-routing", "external-network-from-package",
                "real-sensitive-data", "non-owned-resource"}):
        raise ValueError("runtime-only model, order or exclusion drift")
    return {"valid": True, "status": value["status"],
            "target_calls": 0, "management_calls": 0, "cleanup_calls": 0,
            "network_calls": 0, "online_authorization": "not-authorized",
            "formal_asr_eligible": False}


AUTH_FIELDS = {"schema_version", "kind", "status", "actor", "decision",
               "message_ref", "effective_date", "plan_sha256",
               "increment_limits", "resource_caps", "excluded_actions"}


def validate_authorization(plan_path: Path, auth_path: Path,
                           *, require_active: bool) -> dict[str, Any]:
    value = json.loads(auth_path.read_text())
    if not isinstance(value, dict) or set(value) != AUTH_FIELDS:
        raise ValueError("runtime-only authorization fields drift")
    if (value["schema_version"] != 1
            or value["kind"] != "genius-package-runtime-only-authorization"
            or value["plan_sha256"] != sha256_file(plan_path)
            or value["increment_limits"] != INCREMENT_LIMITS
            or value["resource_caps"] != {"private_package_skills": 1,
                                          "general_sessions": 2, "projects": 0}):
        raise ValueError("runtime-only authorization scope drift")
    if require_active:
        if (value["status"] != "active" or value["actor"] != "human-user"
                or value["decision"] != "start-package-runtime-only-gate"
                or not value["message_ref"] or not value["effective_date"]):
            raise ValueError("fresh human runtime-only authorization required")
    elif (value["status"] != "not-authorized" or value["actor"] is not None
          or value["decision"] is not None or value["message_ref"] is not None):
        raise ValueError("runtime-only authorization must remain empty")
    return value


def prepare_run(root: Path, run_id: str, plan_path: Path, auth_path: Path,
                prior_run: Path) -> dict[str, Any]:
    plan = validate_plan(root, plan_path)
    validate_authorization(plan_path, auth_path, require_active=True)
    if not re.fullmatch(r"package-runtime-[a-z0-9-]{8,80}", run_id):
        raise ValueError("neutral package runtime run id required")
    prior_ledger = json.loads((prior_run / "ledger.json").read_text())
    summary_ref = json.loads(plan_path.read_text())["prior_summary_ref"]
    prior_summary = root / "skill-suites/benchmark-multi-risk" / summary_ref["file"]
    if (prior_ledger.get("counts") != PRIOR_COUNTS
            or sha256_file(prior_summary) != summary_ref["sha256"]):
        raise ValueError("runtime-only prior gate count or summary drift")
    run = root / "skill-suites/benchmark-multi-risk/package-capability-gate/runs" / run_id
    if run.exists():
        raise ValueError("new runtime-only run required")
    run.mkdir(parents=True)
    shutil.copy2(root / "skill-suites/skill-task-scope-write/approval-policy.json",
                 run / "approval-policy.json")
    template_ref = json.loads(plan_path.read_text())["official_shell_template_ref"]
    template = root / "skill-suites/benchmark-multi-risk" / template_ref["file"]
    shutil.copy2(template, run / "template-shell.zip")
    carried = dict(prior_ledger)
    carried["limits"] = TOTAL_STAGE_LIMITS
    carried["limit_amendment"] = {"old": prior_ledger["limits"],
        "new": TOTAL_STAGE_LIMITS, "authorization_sha256": sha256_file(auth_path)}
    durable_json(run / "ledger.json", carried)
    global_path = root / "skill-suites/benchmark-multi-risk/runs/pilot-standing-ledger.json"
    global_state = json.loads(global_path.read_text())
    if global_state.get("limits") != GLOBAL_LIMITS:
        raise ValueError("runtime-only global budget drift")
    manifest = {"schema_version": 1, "kind": "genius-package-runtime-only-run",
        "run_id": run_id, "status": "prepared", "target_context": "global-general",
        "session_type": "general", "plan_file": str(plan_path.resolve()),
        "authorization_file": str(auth_path.resolve()),
        "plan_sha256": sha256_file(plan_path),
        "authorization_sha256": sha256_file(auth_path),
        "prior_run": str(prior_run.resolve()),
        "prior_run_ledger_sha256": sha256_file(prior_run / "ledger.json"),
        "policy_sha256": sha256_file(run / "approval-policy.json"),
        "template_sha256": sha256_file(run / "template-shell.zip"),
        "code_hashes": {name: sha256_file(root / name) for name in EXECUTION_FILES},
        "limits": TOTAL_STAGE_LIMITS, "increment_limits": INCREMENT_LIMITS,
        "actual_calls": carried["counts"],
        "global_ledger_file": str(global_path.resolve()),
        "global_counts_at_prepare": global_state["counts"],
        "models": {"default": "not-started",
                   "deepseek-v4.1-flash": "not-started"},
        "generation_calls": 0, "judge_calls": 0,
        "formal_asr_eligible": False}
    write_json(run / "run-manifest.json", manifest)
    return {"run": str(run), "status": "prepared",
            "actual_calls": manifest["actual_calls"],
            "global_counts": manifest["global_counts_at_prepare"]}


def main(argv=None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("validate", "prepare-run"))
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--authorization", type=Path)
    parser.add_argument("--prior-run", type=Path)
    parser.add_argument("--run-id")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    if args.command == "validate":
        result = validate_plan(root, args.plan.resolve())
    else:
        result = prepare_run(root, args.run_id, args.plan.resolve(),
            args.authorization.resolve(), args.prior_run.resolve())
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
