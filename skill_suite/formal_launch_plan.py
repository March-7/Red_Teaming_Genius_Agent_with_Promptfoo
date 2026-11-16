"""Read-only, real-source formal launch worksheet; never authorizes target calls."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from sweep import runtime
from . import campaign
from .d_gate import audit as audit_d
from .formal_capacity import worksheet
from .schema import canonical_hash


def _retained_collisions(root: Path, names: set[str]) -> list[dict[str, str]]:
    found = []
    runs = root / "skill-suites/skill-task-scope-write/runs"
    for registry_path in sorted(runs.glob("*/resource-registry.jsonl")):
        latest: dict[str, dict[str, Any]] = {}
        for line in registry_path.read_text().splitlines():
            if line.strip():
                item = json.loads(line)
                latest[item["resource_id"]] = item
        for item in latest.values():
            if (item.get("kind") == "skill" and item.get("name") in names
                    and item.get("state") != "cleaned"):
                found.append({"name": item["name"], "resource_id": item["resource_id"],
                              "owner_run_id": item.get("owner_run_id", ""),
                              "registry": str(registry_path.relative_to(root))})
    return found


def prepare(root: Path, source: Path, d_run: Path, formal_config: Path,
            judge_dir: Path, output: Path) -> dict[str, Any]:
    if output.exists() or not output.parent.is_dir():
        raise ValueError("new formal launch worksheet path required")
    if source.name != "source" or not (source.parent / "campaign-freeze.json").is_file():
        raise ValueError("reviewed real provider-response freeze required")
    frozen = campaign.verify_frozen(source.parent)
    plan = json.loads((source / "campaign-plan.json").read_text())
    if plan["generation"]["origin"] != "provider-response":
        raise ValueError("formal launch cannot use a fixture source")
    cases = campaign.validate_plan(plan, source)
    rows = campaign.matrix(plan, cases)
    campaign.validate_matrix(plan, cases, rows)
    capacity = worksheet(plan, source)
    d_gate = audit_d(d_run, root)
    d_plan = json.loads((d_run / "d-smoke-plan.json").read_text())
    d_ledger = json.loads((d_run / "call-ledger.json").read_text())
    if (d_gate.get("d_smoke_ready") is not True or d_gate.get("source_origin") != "provider-response"
            or d_gate.get("validated_rows") != 4 or d_gate.get("pending_ownership_count") != 0
            or d_plan.get("frozen_manifest_sha256") != runtime.sha256_file(source.parent / "campaign-freeze.json")
            or d_ledger["counts"].get("target") != 4
            or d_ledger["counts"].get("management") != 32
            or d_ledger["counts"].get("judge") != 0):
        raise ValueError("matching four-row live API pilot required")
    config = yaml.safe_load(formal_config.read_text())
    judge_plan_path = judge_dir / "judge-plan.json"
    judge_auth = json.loads((judge_dir / "judge-authorization.json").read_text())
    judge = json.loads(judge_plan_path.read_text())
    guard_path = root / "sweep/sensitive_output_guard.cjs"
    if (config.get("metadata", {}).get("formal_ready") is not False
            or config["metadata"].get("plan_sha256") != canonical_hash(plan)
            or config["metadata"].get("guard", {}).get("sha256") != runtime.sha256_file(guard_path)
            or config.get("defaultTest", {}).get("options", {}).get("transform") != guard_path.as_uri()
            or len(config.get("tests", [])) != 400
            or judge.get("source_origin") != "provider-response"
            or judge.get("frozen_manifest_sha256") != runtime.sha256_file(source.parent / "campaign-freeze.json")
            or judge.get("formal_config_sha256") != runtime.sha256_file(formal_config)
            or judge.get("max_requests") != 200
            or judge.get("enable_thinking") is not False
            or judge.get("http_timeout_seconds") != 300
            or judge.get("wrapper_sha256") != runtime.sha256_file(
                root / "skill-suites/skill-task-scope-write/promptfoo/dashscope-judge-one-shot.mjs")
            or len(judge.get("rows", [])) != 200
            or judge_auth != {"status": "not-authorized",
                              "plan_sha256": runtime.sha256_file(judge_plan_path)}):
        raise ValueError("400-row guarded config and 200-row unapproved Judge plan required")
    names = {row["locators"]["resource_name"] for row in rows}
    collisions = _retained_collisions(root, names)
    if len(names) != 400:
        raise ValueError("one distinct Skill locator per formal row required")
    candidate = {"target": 400, "management": 4800, "recovery": 400,
                 "cleanup": 400, "generation": 0, "judge": 200,
                 "private_skills": 400, "general_sessions": 400, "projects": 0,
                 "activity_per_target_s": 300, "activity_total_s": 120000,
                 "max_concurrency": 2, "retry": 0}
    # 8 observed base GET/POSTs + 2 effect GETs + 1 possible extra GET per row;
    # 400 recovery GETs are separately reserved within the 4800 management cap.
    if (candidate["management"] < capacity["counted_management_floor"]
            + capacity["conditional_management_if_every_row_has_effect"]
            + candidate["recovery"]):
        raise ValueError("candidate management cap does not cover the counted API path")
    missing = ["live-formal-target-provider-and-binding",
               "formal-authorization-and-provider-budget-approval"]
    if collisions:
        missing.append("retained-private-skill-name-collisions")
    if runtime.read_ownership(root):
        missing.append("pending-upstream-ownership")
    result = {"kind": "skill-formal-launch-worksheet", "status": "not-authorized",
        "source_origin": "provider-response", "campaign_id": plan["campaign_id"],
        "source_plan_sha256": runtime.sha256_file(source / "campaign-plan.json"),
        "frozen_manifest_sha256": runtime.sha256_file(source.parent / "campaign-freeze.json"),
        "frozen_review_count": frozen["semantic_review_count"],
        "d_live_gate_sha256": runtime.sha256_file(d_run / "d-gate.json"),
        "d_live_ledger_sha256": runtime.sha256_file(d_run / "call-ledger.json"),
        "formal_config_sha256": runtime.sha256_file(formal_config),
        "judge_plan_sha256": runtime.sha256_file(judge_plan_path),
        "guard_sha256": runtime.sha256_file(guard_path),
        "model_variant_rows": capacity["model_variant_rows"],
        "candidate_limits_unapproved": candidate,
        "capacity_evidence": {"live_pilot_target": 4, "live_pilot_management": 32,
                              "base_management_per_row": 8,
                              "base_management_400": capacity["counted_management_floor"],
                              "effect_conditional_management_400":
                                  capacity["conditional_management_if_every_row_has_effect"],
                              "effect_conditional_cleanup_400":
                                  capacity["conditional_cleanup_if_every_row_has_effect"]},
        "retained_skill_collisions": collisions,
        "missing_readiness": missing, "formal_ready": False,
        "actual_calls": {"target": 0, "management": 0, "recovery": 0,
                         "cleanup": 0, "generation": 0, "judge": 0}}
    runtime.write_json(output, result)
    return {"output": str(output), "formal_ready": False,
            "expected_target_rows": 400, "judge_candidate_rows": 200,
            "retained_name_collisions": len(collisions), "missing_readiness": missing}
