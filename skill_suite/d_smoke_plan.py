"""Offline four-row generated-carrier smoke plan; execution needs new approval."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from sweep import runtime
from sweep.runtime import sha256_file, write_json
from . import campaign
from .schema import canonical_hash, identifier


LIMITS = {"target": 4, "management": 64, "recovery": 4, "cleanup": 8,
          "generation": 0, "judge": 0, "activity_total_s": 1200,
          "activity_per_call_s": 300, "skills": 4, "scopes": 4, "sessions": 4}
MIN_SKILL_AGE_SECONDS = 90
CODE_ROOT = Path(__file__).resolve().parent.parent
CODE_FILES = ("skill_suite/d_smoke_plan.py", "skill_suite/d_provisioner.py",
              "skill_suite/d_binding.py", "skill_suite/d_target.py",
              "skill_suite/d_observer.py", "skill_suite/d_gate.py",
              "skill_suite/observed_api.py",
              "skill_suite/artifact_download.py", "shim/genius_service.py",
              "sweep/runtime.py")


def prepare(plan: dict[str, Any], source: Path, case_id: str,
            output: Path, run_id: str) -> dict[str, Any]:
    identifier(case_id, "case_id")
    identifier(run_id, "run_id")
    if output.exists() or not output.parent.is_dir():
        raise ValueError("new D smoke plan directory required")
    if json.loads((source / "campaign-plan.json").read_text()) != plan:
        raise ValueError("D source plan file differs from the reviewed campaign")
    cases = campaign.validate_plan(plan, source)
    rows = campaign.matrix(plan, cases)
    campaign.validate_matrix(plan, cases, rows)
    if plan["schema_version"] != 3 or plan.get("target_context") != "global-general":
        raise ValueError("D requires the current general artifact campaign")
    origin = plan["generation"]["origin"]
    frozen_hash = None
    if origin == "provider-response":
        if source.name != "source" or not (source.parent / "campaign-freeze.json").is_file():
            raise ValueError("live D plan requires a reviewed frozen source")
        campaign.verify_frozen(source.parent)
        frozen_hash = sha256_file(source.parent / "campaign-freeze.json")
    selected = [row for row in rows if row["case_id"] == case_id]
    if (len(selected) != 4 or
            {(row["model_profile"], row["variant"]) for row in selected} !=
            {(profile, variant) for profile in ("default", "deepseek-v4.1-flash")
             for variant in ("normal", "attack")}):
        raise ValueError("one generated combination must cover two paired models")
    policy_source = Path(__file__).resolve().parent.parent / "skill-suites/skill-task-scope-write/approval-policy.json"
    policy_bytes = policy_source.read_bytes()
    output.mkdir()
    policy_hash = runtime.snapshot_policy(policy_bytes, output / "approval-policy.json", unbound=True)
    stage = {"kind": "skill-generated-smoke-plan", "schema_version": 1,
        "phase": "D", "run_id": run_id, "campaign_id": plan["campaign_id"],
        "source_origin": origin, "source_plan_sha256": canonical_hash(plan),
        "source_plan_file_sha256": sha256_file(source / "campaign-plan.json"),
        "frozen_manifest_sha256": frozen_hash,
        "risk_id": plan["risk_id"], "effect_surface": plan["risk_contract"]["effect_surface"],
        "target_context": "global-general", "session_type": "general",
        "case_id": case_id, "model_matrix": plan["model_matrix"],
        "limits": LIMITS, "max_concurrency": 1, "retry": 0,
        "min_skill_age_seconds": MIN_SKILL_AGE_SECONDS,
        "lifecycle": "retain", "new_projects": 0,
        "policy_sha256": policy_hash, "guard_sha256": sha256_file(runtime.GUARD_PATH),
        "code_hashes": {name: sha256_file(CODE_ROOT / name) for name in CODE_FILES},
        "rows": [{"evaluation_key": row["evaluation_key"],
                  "case_id": row["case_id"], "model_profile": row["model_profile"],
                  "variant": row["variant"], "task_sha256": row["task_sha256"],
                  "skill_sha256": row["skill_artifact"]["sha256"],
                  "resource_name": row["locators"]["resource_name"],
                  "effect_artifact_name": row["locators"]["record_id"]}
                 for row in selected]}
    write_json(output / "d-smoke-plan.json", stage)
    write_json(output / "d-smoke-authorization.json", {
        "status": "not-authorized", "plan_sha256": sha256_file(output / "d-smoke-plan.json")})
    summary = {"kind": "skill-d-smoke-preparation", "run_id": run_id,
        "source_origin": origin, "selected_rows": 4, "planned_target_calls": 4,
        "actual_calls": {"target": 0, "management": 0, "cleanup": 0,
                         "generation": 0, "judge": 0},
        "authorization_status": "not-authorized", "formal_ready": False,
        "plan_sha256": sha256_file(output / "d-smoke-plan.json")}
    write_json(output / "d-smoke-preparation.json", summary)
    return {"output": str(output), **summary}


def authorize(run: Path, source: Path, message_ref: str) -> dict[str, Any]:
    """Record a new, explicit human D reply only for a real frozen source."""
    stage_path = run / "d-smoke-plan.json"
    stage = json.loads(stage_path.read_text())
    prior = json.loads((run / "d-smoke-authorization.json").read_text())
    if (prior.get("status") != "not-authorized" or not message_ref
            or stage.get("phase") != "D" or stage.get("source_origin") != "provider-response"
            or stage.get("limits") != LIMITS
            or stage.get("min_skill_age_seconds") != MIN_SKILL_AGE_SECONDS
            or stage.get("source_plan_file_sha256") != sha256_file(source / "campaign-plan.json")
            or stage.get("frozen_manifest_sha256") != sha256_file(source.parent / "campaign-freeze.json")
            or stage.get("policy_sha256") != sha256_file(run / "approval-policy.json")
            or stage.get("guard_sha256") != sha256_file(runtime.GUARD_PATH)
            or stage.get("code_hashes") != {name: sha256_file(CODE_ROOT / name) for name in CODE_FILES}
            or (run / "call-ledger.json").exists() or (run / "resource-registry.jsonl").exists()):
        raise ValueError("fresh frozen D plan and separate human start reply required")
    campaign.verify_frozen(source.parent)
    record = {"actor": "human-user", "decision": "start", "phase": "D",
              "run_id": stage["run_id"], "plan_sha256": sha256_file(stage_path),
              "message_ref": message_ref, "confirmed_at": runtime.utc_now()}
    write_json(run / "d-smoke-authorization.json", record)
    return record


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args(argv)
    plan = json.loads(args.plan.read_text())
    print(json.dumps(prepare(plan, args.plan.parent, args.case_id,
                             args.output, args.run_id), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
