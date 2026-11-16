"""Bind one D smoke target to frozen Skill bytes and observed API receipts.

This contract is local and read-only. The shim must request live=True before it
can submit an online target; fixture bindings only exercise the proof shape.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import quote

from sweep import runtime
from sweep.runtime import sha256_file
from . import campaign
from .evidence import read_ref
from .schema import canonical_hash, identifier, text_hash


RECEIPTS = {"create_skill", "read_skill", "sharing", "create_session", "artifact_before"}


def _receipt(root: Path, ref: dict[str, str], method: str, path: str,
             environment: str) -> dict[str, Any]:
    raw = read_ref(root, ref)
    request, response = raw.get("request", {}), raw.get("response", {})
    if (raw.get("environment") != environment or request.get("method") != method
            or request.get("path") != path or response.get("status") not in {200, 201}
            or not isinstance(response.get("body"), dict)):
        raise ValueError("observed API receipt identity or status drift")
    return raw


def validate_binding(path: Path, expected_hash: str, *, live: bool) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return the exact campaign row and owned Skill/session identity."""
    if sha256_file(path) != expected_hash:
        raise ValueError("pinned D binding hash required")
    binding = json.loads(path.read_text())
    root = path.parent
    if (not isinstance(binding, dict) or set(binding) != {"kind", "environment", "source_root",
            "stage_plan_sha256", "evaluation_key", "principal_id", "skill_id", "skill_version",
            "session_id", "receipts"} or binding["kind"] != "skill-generated-smoke-binding"
            or binding["environment"] != ("live" if live else "offline-fixture")
            or not isinstance(binding["receipts"], dict) or set(binding["receipts"]) != RECEIPTS):
        raise ValueError("exact owned D binding required")
    principal = identifier(binding["principal_id"], "principal_id")
    skill_id = identifier(binding["skill_id"], "skill_id")
    session_id = identifier(binding["session_id"], "session_id")
    if not session_id.startswith("chat:" + principal + ":"):
        raise ValueError("D must target an owned native general session")
    source = Path(binding["source_root"])
    if not source.is_absolute() or not source.is_dir():
        raise ValueError("absolute frozen campaign source required")
    stage_path = root / "d-smoke-plan.json"
    stage = json.loads(stage_path.read_text())
    if (stage.get("kind") != "skill-generated-smoke-plan" or stage.get("phase") != "D"
            or binding["stage_plan_sha256"] != sha256_file(stage_path)
            or stage.get("source_plan_file_sha256") != sha256_file(source / "campaign-plan.json")
            or stage.get("target_context") != "global-general"
            or stage.get("session_type") != "general" or stage.get("new_projects") != 0
            or stage.get("retry") != 0 or stage.get("limits", {}).get("target") != 4
            or stage.get("limits", {}).get("judge") != 0
            or stage.get("policy_sha256") != sha256_file(root / "approval-policy.json")
            or stage.get("guard_sha256") != sha256_file(runtime.GUARD_PATH)):
        raise ValueError("D stage/source/budget drift")
    from .d_smoke_plan import CODE_FILES, CODE_ROOT
    if stage.get("code_hashes") != {name: sha256_file(CODE_ROOT / name) for name in CODE_FILES}:
        raise ValueError("D execution code changed after stage preparation")
    authorization = json.loads((root / "d-smoke-authorization.json").read_text())
    expected_actor = "human-user" if live else "offline-fixture"
    if (authorization.get("actor") != expected_actor or authorization.get("decision") != "start"
            or authorization.get("phase") != "D" or authorization.get("run_id") != stage["run_id"]
            or authorization.get("plan_sha256") != sha256_file(stage_path)
            or not authorization.get("message_ref") or not authorization.get("confirmed_at")):
        raise ValueError("separate phase-bound D start confirmation required")
    plan = json.loads((source / "campaign-plan.json").read_text())
    cases = campaign.validate_plan(plan, source)
    rows = campaign.matrix(plan, cases)
    campaign.validate_matrix(plan, cases, rows)
    if (stage["source_plan_sha256"] != canonical_hash(plan)
            or stage["campaign_id"] != plan["campaign_id"]
            or stage["source_origin"] != plan["generation"]["origin"]):
        raise ValueError("D source campaign changed")
    if live:
        if (plan["generation"]["origin"] != "provider-response"
                or source.name != "source" or not (source.parent / "campaign-freeze.json").is_file()
                or stage.get("frozen_manifest_sha256") != sha256_file(source.parent / "campaign-freeze.json")):
            raise ValueError("D live source must be the reviewed provider-response freeze")
        campaign.verify_frozen(source.parent)
    matches = [row for row in rows if row["evaluation_key"] == binding["evaluation_key"]]
    selected = [row for row in stage["rows"] if row["evaluation_key"] == binding["evaluation_key"]]
    if len(matches) != 1 or len(selected) != 1:
        raise ValueError("unique frozen D row required")
    row = matches[0]
    if selected[0] != {"evaluation_key": row["evaluation_key"], "case_id": row["case_id"],
                       "model_profile": row["model_profile"], "variant": row["variant"],
                       "task_sha256": row["task_sha256"],
                       "skill_sha256": row["skill_artifact"]["sha256"],
                       "resource_name": row["locators"]["resource_name"],
                       "effect_artifact_name": row["locators"]["record_id"]}:
        raise ValueError("D stage row differs from frozen matrix")
    if row["locators"]["record_id"] in row["user_task"]:
        raise ValueError("attack target leaked into read-only task")
    skill_body = campaign.asset(source, row["skill_artifact"])
    receipts = binding["receipts"]
    create = _receipt(root, receipts["create_skill"], "POST", "/api/skills", binding["environment"])
    create_body = create["request"].get("body", {})
    if (create_body != {"name": row["locators"]["resource_name"], "instructions": skill_body,
            "description": "用于整理资料数量的操作说明", "category": "other", "tags": [],
            "stage": "", "priority": "medium", "needs_credentials": []}):
        raise ValueError("Skill creation payload differs from the frozen carrier")
    skill_path = "/api/skills/" + quote(skill_id, safe="")
    read = _receipt(root, receipts["read_skill"], "GET", skill_path, binding["environment"])
    sharing = _receipt(root, receipts["sharing"], "GET", skill_path + "/sharing", binding["environment"])
    created = create["response"]["body"].get("skill", {})
    metadata = read["response"]["body"].get("skill", {})
    shared = sharing["response"]["body"]
    for skill in (created, metadata):
        if (skill.get("skill_id") != skill_id or skill.get("name") != row["locators"]["resource_name"]
                or skill.get("owner_id") != principal or skill.get("source") != "user"
                or skill.get("visibility") != "private" or skill.get("mode") != "text"
                or skill.get("instructions") != skill_body or skill.get("scripts")
                or skill.get("needs_credentials") or str(skill.get("version")) != binding["skill_version"]):
            raise ValueError("private Skill identity, body or version drift")
    if (create["response"]["body"].get("skill_id") != skill_id
            or metadata.get("shared_with_count") != 0
            or shared != {"skill_id": skill_id, "scope": "private", "members": []}
            or text_hash(skill_body) != row["skill_artifact"]["sha256"]):
        raise ValueError("private catalogue creation/sharing/readback drift")
    session = _receipt(root, receipts["create_session"], "POST", "/api/sessions", binding["environment"])
    if (session["request"].get("body") != {"session_type": "general"}
            or session["response"]["body"].get("session_id") != session_id
            or session["response"]["body"].get("user_id") != principal
            or session["response"]["body"].get("session_type") != "general"):
        raise ValueError("native general session receipt drift")
    before = _receipt(root, receipts["artifact_before"], "GET",
                      "/api/sessions/" + quote(session_id, safe="") + "/artifacts",
                      binding["environment"])
    if before["response"]["body"].get("artifacts") != []:
        raise ValueError("D mutable artifact scope is not initially empty")
    return row, binding


def case_request(stage: dict[str, Any], row: dict[str, Any], binding: dict[str, Any]) -> dict[str, Any]:
    """Build the only target request allowed for a provisioned D row."""
    return {"messages": [{"role": "user", "content": row["user_task"]}],
        "metadata": {"session_id": binding["session_id"], "campaign": {
            "kind": "skill-campaign", "phase": "D", "run_id": stage["run_id"],
            "campaign_id": stage["campaign_id"], "case_id": row["case_id"],
            "model_profile": row["model_profile"], "variant": row["variant"],
            "evaluation_key": row["evaluation_key"], "skill_id": binding["skill_id"],
            "skill_version": binding["skill_version"],
            "skill_hash": row["skill_artifact"]["sha256"],
            "target_context": "global-general"}},
        "model_profile": row["model_profile"], "reasoning_effort": "high", "thinking": "on"}


def bound_request(path: Path, expected_hash: str, request: dict[str, Any],
                  *, live: bool) -> dict[str, Any]:
    if set(request) != {"messages", "metadata", "model_profile", "reasoning_effort", "thinking"}:
        raise ValueError("D target request contains unregistered fields")
    row, binding = validate_binding(path, expected_hash, live=live)
    stage = json.loads((path.parent / "d-smoke-plan.json").read_text())
    if request != case_request(stage, row, binding):
        raise ValueError("D target task, model, session or Skill identity drift")
    return {"row": row, "binding": binding, "stage": stage}
