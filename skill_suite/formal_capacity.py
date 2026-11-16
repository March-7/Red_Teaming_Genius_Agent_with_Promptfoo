"""Offline capacity worksheet for the eventual 400-row general Skill campaign.

This is an auditable lower/conditional operation count, never execution
authorization or a final management cap. Live source/readback and recovery
pilots must settle the remaining overhead before a formal run can be ready.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from . import campaign
from .schema import canonical_hash
from sweep.runtime import write_json


BASE_MANAGEMENT_STEPS = (
    "private-skill-create",
    "private-skill-read",
    "private-sharing-read",
    "general-session-create",
    "artifact-before-read",
    "catalogue-before-target-read",
    "catalogue-after-target-read",
    "artifact-after-read",
)
EFFECT_MANAGEMENT_STEPS = ("artifact-download", "artifact-restored-read")
EFFECT_CLEANUP_STEPS = ("artifact-delete",)


def worksheet(plan: dict[str, Any], source_root: Path) -> dict[str, Any]:
    """Derive counts only after the entire campaign contract is validated."""
    if plan.get("schema_version") != 3 or plan.get("target_context") != "global-general":
        raise ValueError("formal capacity requires the current general artifact campaign")
    cases = campaign.validate_plan(plan, source_root)
    rows = campaign.matrix(plan, cases)
    campaign.validate_matrix(plan, cases, rows)
    if (len(rows) != 400 or len(cases) != 100
            or any(row.get("session_type") != "general" or row.get("native_resources") is not None
                   for row in rows)
            or len({row["evaluation_key"] for row in rows}) != 400
            or len({row["logical_session_key"] for row in rows}) != 400
            or len({row["locators"]["resource_name"] for row in rows}) != 400):
        raise ValueError("400 isolated general rows required")
    distribution = {profile: {variant: sum(row["model_profile"] == profile
                                          and row["variant"] == variant for row in rows)
                              for variant in ("normal", "attack")}
                    for profile in ("default", "deepseek-v4.1-flash")}
    if distribution != {profile: {"normal": 100, "attack": 100} for profile in distribution}:
        raise ValueError("two-model paired coverage drift")
    count = len(rows)
    return {"kind": "skill-formal-capacity-worksheet", "campaign_id": plan["campaign_id"],
            "plan_sha256": canonical_hash(plan),
            "source_origin": plan["generation"]["origin"], "target_context": "global-general",
            "execution_status": "offline-draft", "formal_ready": False,
            "target_calls": count, "attack_calls": count // 2, "normal_calls": count // 2,
            "model_variant_rows": distribution, "max_concurrency": 2, "retry": 0,
            "native_resource_upper_bound_if_one_per_row": {
                "private_skill_instances": count, "general_sessions": count,
                "projects": 0, "mutable_artifact_scopes": count},
            "observed_api_steps_per_row": {
                "base_management": list(BASE_MANAGEMENT_STEPS),
                "effect_conditional_management": list(EFFECT_MANAGEMENT_STEPS),
                "effect_conditional_cleanup": list(EFFECT_CLEANUP_STEPS)},
            "counted_management_floor": count * len(BASE_MANAGEMENT_STEPS),
            "conditional_management_if_every_row_has_effect": count * len(EFFECT_MANAGEMENT_STEPS),
            "conditional_cleanup_if_every_row_has_effect": count * len(EFFECT_CLEANUP_STEPS),
            "management_overhead": "unfrozen: model catalogue, ownership and recovery pilot",
            "judge_provider": "unselected", "judge_request_cap": None,
            "approved_management_cap": None, "approved_recovery_cap": None,
            "formal_start_authorized": False}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    plan = json.loads(args.plan.read_text())
    result = worksheet(plan, args.plan.parent)
    if args.output is not None:
        if args.output.exists() or not args.output.parent.is_dir():
            raise ValueError("new output file with existing parent required")
        write_json(args.output, result)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
