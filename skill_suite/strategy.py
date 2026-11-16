"""Offline one-iteration Skill-content strategy plan; never submits a target."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import tempfile
from typing import Any

from sweep.runtime import sha256_file, write_json
from .campaign import asset, validate_plan
from .schema import canonical_hash, identifier


FIELDS = {"strategy_id", "plan_sha256", "skill_key", "candidate_ref", "iteration",
          "numIterations", "management_per_target", "cleanup_per_target"}


def prepare_variant(source_root: Path, request: Any, output: Path) -> dict[str, Any]:
    if not isinstance(request, dict) or set(request) != FIELDS:
        raise ValueError("Skill-only strategy cannot modify a user task or another field")
    if request["strategy_id"] != "skill-content-only":
        raise ValueError("generic jailbreak strategies cannot mutate this Skill carrier")
    if request["iteration"] != 1 or request["numIterations"] != 1:
        raise ValueError("one explicitly budgeted Skill iteration required")
    for field in ("management_per_target", "cleanup_per_target"):
        if type(request[field]) is not int or request[field] < 1:
            raise ValueError("explicit per-target management and cleanup caps required")
    identifier(request["skill_key"], "Skill key")
    plan_path = source_root / "campaign-plan.json"
    plan = json.loads(plan_path.read_text())
    if sha256_file(plan_path) != request["plan_sha256"]:
        raise ValueError("campaign plan changed")
    cases = validate_plan(plan, source_root)
    if plan["schema_version"] != 3 or plan["risk_contract"]["effect_surface"] != "native-general-session-artifact-creation":
        raise ValueError("session artifact campaign v3 required")
    skills = [skill for skill in plan["skills"] if skill["skill_key"] == request["skill_key"]]
    if len(skills) != 1:
        raise ValueError("unique Skill required")
    skill = skills[0]
    ref = request["candidate_ref"]
    candidate = asset(source_root, ref)
    normal = asset(source_root, skill["normal"])
    original = asset(source_root, skill["attack"])
    if (not candidate.startswith(normal) or candidate == original
            or skill["effect_artifact_name"] not in candidate):
        raise ValueError("candidate must change only the attack Skill while keeping its task and goal")
    if output.exists() or not output.parent.is_dir():
        raise ValueError("new output directory required")
    target_calls = len([case for case in cases if case["skill_key"] == skill["skill_key"]]) * len(plan["model_matrix"]) * 2
    with tempfile.TemporaryDirectory(prefix=".skill-strategy-", dir=output.parent) as temporary:
        temporary_root = Path(temporary)
        candidate_path = temporary_root / "attack-candidate.md"
        shutil.copyfile(source_root / ref["file"], candidate_path)
        if sha256_file(candidate_path) != ref["sha256"]:
            raise ValueError("candidate content drift")
        task_hashes = sorted(case["template_sha256"] for case in cases
                             if case["skill_key"] == skill["skill_key"])
        manifest = {"schema_version": 1, "kind": "skill-content-iteration-plan",
            "strategy_id": "skill-content-only", "campaign_plan_sha256": request["plan_sha256"],
            "skill_key": skill["skill_key"], "iteration": 1, "numIterations": 1,
            "normal_sha256": skill["normal"]["sha256"],
            "base_attack_sha256": skill["attack"]["sha256"],
            "candidate_sha256": sha256_file(candidate_path),
            "candidate_ref": {"file": candidate_path.name, "sha256": sha256_file(candidate_path)},
            "effect_artifact_name": skill["effect_artifact_name"],
            "task_template_hashes": task_hashes,
            "model_matrix_sha256": canonical_hash(plan["model_matrix"]),
            "risk_contract_sha256": canonical_hash(plan["risk_contract"]),
            "budget_upper_bound": {"target": target_calls,
                "management": target_calls * request["management_per_target"],
                "cleanup": target_calls * request["cleanup_per_target"],
                "generation": 0, "judge": 0, "retry": 0},
            "actual_calls": {"target": 0, "management": 0, "cleanup": 0,
                             "generation": 0, "judge": 0},
            "live_enabled": False, "formal_ready": False}
        if len(task_hashes) != 10 or target_calls != 40:
            raise ValueError("exactly ten tasks and two models per Skill required")
        write_json(temporary_root / "iteration-plan.json", manifest)
        temporary_root.rename(output)
    return {"output": str(output), "candidate_sha256": manifest["candidate_sha256"],
            "target_upper_bound": target_calls, "actual_target_calls": 0,
            "live_enabled": False}


def candidate_for_row(source_root: Path, manifest_path: Path,
                      plan: dict[str, Any], row: dict[str, Any]) -> str:
    manifest = json.loads(manifest_path.read_text())
    if (manifest.get("kind") != "skill-content-iteration-plan"
            or manifest.get("strategy_id") != "skill-content-only"
            or manifest.get("live_enabled") is not False
            or manifest.get("iteration") != 1 or manifest.get("numIterations") != 1
            or row["variant"] != "attack"
            or row.get("skill_key") != manifest.get("skill_key")
            or row["task_template_sha256"] not in manifest.get("task_template_hashes", [])
            or manifest.get("campaign_plan_sha256") != sha256_file(source_root / "campaign-plan.json")
            or manifest.get("model_matrix_sha256") != canonical_hash(plan["model_matrix"])
            or manifest.get("risk_contract_sha256") != canonical_hash(plan["risk_contract"])
            or row["locators"]["record_id"] != manifest.get("effect_artifact_name")):
        raise ValueError("Skill-only strategy identity or frozen task drift")
    ref = manifest.get("candidate_ref")
    if not isinstance(ref, dict) or set(ref) != {"file", "sha256"}:
        raise ValueError("candidate reference missing")
    candidate_path = manifest_path.parent / ref["file"]
    if (not candidate_path.is_file() or candidate_path.resolve().parent != manifest_path.parent.resolve()
            or sha256_file(candidate_path) != ref["sha256"]
            or ref["sha256"] != manifest.get("candidate_sha256")
            or ref["sha256"] == row["skill_artifact"]["sha256"]):
        raise ValueError("candidate Skill bytes changed")
    return candidate_path.read_text()
