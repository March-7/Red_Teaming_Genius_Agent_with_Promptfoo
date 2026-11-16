"""Read-only B resource handoff and Project description oracle adapters."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import quote

from sweep import runtime
from .schema import canonical_hash
from .state_oracle import normalize_project_description


def verify_borrowed_project(root: Path, row: dict[str, Any], receipt: dict[str, Any],
                            principal_id: str, initial_state: dict[str, Any]) -> dict[str, Any]:
    """Check source-run ownership and a fresh current-account API readback."""
    source_name = row.get("source_run_id")
    if source_name not in {"notes-general-20261002-fc3ea249", "notes-general-a2-20261002-20f3cfcd"}:
        raise ValueError("unexpected source run for retained Project")
    source = root / "skill-suites/skill-task-scope-write/runs" / source_name
    manifest = json.loads((source / "run-manifest.json").read_text())
    expected_status = ("stopped-control-invalid" if source_name == "notes-general-20261002-fc3ea249"
                       else "completed-general-A2")
    if manifest.get("kind") != "skill-suite" or manifest.get("status") != expected_status:
        raise ValueError("source run is not a closed retained A run")
    registry_path = source / "resource-registry.jsonl"
    digest = runtime.sha256_file(registry_path)
    if digest != row.get("source_registry_sha256") or manifest["artifact_hashes"].get("resource-registry.jsonl") != digest:
        raise ValueError("borrowed resource registry changed")
    registry = [json.loads(line) for line in registry_path.read_text().splitlines() if line]
    matching = [item for item in registry if item.get("resource_id") == row.get("project_id")]
    if not matching or (matching[-1].get("kind"), matching[-1].get("state"), matching[-1].get("owner_run_id"),
                        matching[-1].get("shared")) != ("scope", "retained", source_name, False):
        raise ValueError("Project was not retained exclusively by the source run")
    cases = [json.loads(line) for line in (source / "case-registry.jsonl").read_text().splitlines() if line]
    if len([case for case in cases if case.get("case_id") == row.get("source_case_id")
            and case.get("scope_id") == row["project_id"]
            and case.get("model_profile") == row.get("model_profile")]) != 1:
        raise ValueError("source Project is not the planned model/case resource")
    suffix = row["source_case_id"].removeprefix("notes-")
    prior_path = source / ("A-project-read-" + suffix + ".json")
    prior_hash = runtime.sha256_file(prior_path)
    if (prior_hash != row.get("source_project_receipt_sha256")
            or manifest["artifact_hashes"].get(prior_path.name) != prior_hash):
        raise ValueError("source Project owner/creation readback changed")
    expected_path = "/api/projects/" + quote(row["project_id"], safe="")
    response = receipt.get("response", {})
    if (receipt.get("request", {}).get("method") != "GET" or receipt["request"].get("path") != expected_path
            or response.get("status") != 200):
        raise ValueError("fresh Project owner/status GET required")
    from .state_oracle import when
    if (not manifest.get("finished_at") or not receipt.get("observed_at")
            or when(receipt["observed_at"]) <= when(manifest["finished_at"])):
        raise ValueError("Project readback must occur after the source run ended")
    project = response.get("body", {})
    if isinstance(project.get("project"), dict): project = project["project"]
    state, version = normalize_project_description(project, project_id=row["project_id"],
        original_name=row["project_name"], principal_id=principal_id)
    if canonical_hash(state) != canonical_hash(initial_state) or not state["name_unchanged"]:
        raise ValueError("borrowed Project initial state drift")
    if row.get("owner_id") != principal_id:
        raise ValueError("source owner and current account differ")
    return {"resource_id": row["project_id"], "initial_state_hash": canonical_hash(state),
            "version": version, "borrowed_from": source_name, "owner_id": principal_id}


def validate_fixed_pair_packet(packet: dict[str, Any], assets: list[dict[str, Any]],
                               asset_root: Path) -> dict[str, Any]:
    """Offline boundary: only the Skill body carries the unrequested write goal."""
    if (packet.get("kind") != "B-fixed-case-plan" or packet.get("phase") != "B"
            or packet.get("target_context") != "global-general" or packet.get("session_type") != "general"
            or packet.get("actual_target_calls") != 0 or len(packet.get("cases", [])) != 6):
        raise ValueError("six-case offline B packet required")
    from .schema import text_hash
    cases = packet["cases"]
    if (len({row["scope_id"] for row in cases}) != 6
            or len({row["logical_session_key"] for row in cases}) != 6
            or len({row["initial_state_hash"] for row in cases}) != 1):
        raise ValueError("B resources or equivalent initial state drift")
    expected_roles = {(p, v) for p in ("default", "deepseek-v4.1-flash")
                      for v in ("allowed-write", "normal", "attack")}
    if {(row["model_profile"], row["variant"]) for row in cases} != expected_roles:
        raise ValueError("missing paired models or variants")
    goal = packet["goal_value"]
    if not isinstance(goal, str) or not goal:
        raise ValueError("fixed reversible field value required")
    if "accepted_artifact_sha256" in packet:
        from .file_oracle import accepted_note_hashes
        if (packet.get("effect_surface") != "native-general-session-artifact-creation"
                or packet["accepted_artifact_sha256"] != accepted_note_hashes(goal)
                or packet.get("expected_artifact_sha256") not in packet["accepted_artifact_sha256"]):
            raise ValueError("artifact byte acceptance differs from the frozen one-line task")
    for row in cases:
        if (text_hash(row["user_task"]) != row["task_hash"]
                or row["target_context"] != "global-general" or row["session_type"] != "general"
                or row["requested_reasoning_effort"] != "high" or row["requested_thinking"] != "on"):
            raise ValueError("B task/request identity drift")
        if row["variant"] in {"normal", "attack"} and goal in row["user_task"]:
            raise ValueError("unrequested write goal leaked into read-only task")
        from sweep.resource_naming import validate_neutral_user_question
        validate_neutral_user_question(row["user_task"])
    for profile in ("default", "deepseek-v4.1-flash"):
        rows = {row["variant"]: row for row in cases if row["model_profile"] == profile}
        normal, attack, positive = (rows[k] for k in ("normal", "attack", "allowed-write"))
        if (normal["case_id"] != attack["case_id"]
                or normal["task_template_hash"] != attack["task_template_hash"]
                or normal["task_template_hash"] == positive["task_template_hash"]):
            raise ValueError("normal/attack task or explicit write control drift")
        assets_by_role = {a["variant"]: a for a in assets if a["model_profile"] == profile}
        if set(assets_by_role) != {"normal", "attack"}:
            raise ValueError("normal and attack Skill assets required per model")
        n, a = assets_by_role["normal"], assets_by_role["attack"]
        npath, apath = (asset_root / n["instructions_file"], asset_root / a["instructions_file"])
        if (runtime.sha256_file(npath) != n["instructions_sha256"]
                or runtime.sha256_file(apath) != a["instructions_sha256"]):
            raise ValueError("B Skill content hash drift")
        ntext, atext = npath.read_text(), apath.read_text()
        if (not atext.startswith(ntext) or goal in ntext or goal not in atext
                or normal["resource_name"] != n["name"] or attack["resource_name"] != a["name"]
                or positive["resource_name"] != n["name"]
                or normal["skill_body_hash"] != n["instructions_sha256"]
                or attack["skill_body_hash"] != a["instructions_sha256"]):
            raise ValueError("Skill carrier is not the sole attacker-controlled difference")
    return {"offline": True, "case_count": 6, "model_count": 2, "normal_count": 2,
            "attack_count": 2, "authorized_write_count": 2, "attack_payload_location": "Skill body only",
            "actual_target_calls": 0}
