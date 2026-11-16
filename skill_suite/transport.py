"""Pinned, run-local bindings for the existing general/workspace chat transport.

This does not register Skills or guess Genius control-plane endpoints.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any
from sweep.runtime import sha256_file
from .evidence import read_rows
from .schema import load_suite, validate_isolation
from .budget import require_confirmation


def bound_case(registry_path: str, registry_hash: str, request: dict[str, Any]) -> dict[str, Any]:
    if set(request) - {"messages", "metadata", "model_profile", "reasoning_effort", "thinking", "model", "stream"}:
        raise ValueError("unregistered request fields can override Skill binding")
    path = Path(registry_path)
    if not registry_path or not path.is_file() or sha256_file(path) != registry_hash:
        raise ValueError("pinned run-local Skill case registry required")
    suite = load_suite(path.parent / "suite.snapshot.yaml")
    rows = read_rows(path)
    validate_isolation(rows, suite)
    metadata = request.get("metadata") or {}
    campaign = metadata.get("campaign") or {}
    if campaign.get("kind") != "skill-suite" or campaign.get("plugin_id"):
        raise ValueError("Skill suite cannot impersonate a built-in plugin")
    keys = ("run_id", "suite_id", "risk_id", "case_id", "variant", "model_profile")
    matches = [row for row in rows if all(campaign.get(k) == row[k] for k in keys)]
    if len(matches) != 1:
        raise ValueError("unique registry-bound Skill case required")
    case = matches[0]
    require_confirmation(suite, case["run_id"])
    if metadata != case_request(case)["metadata"]:
        raise ValueError("Skill case routing metadata changed")
    if request.get("messages") != [{"role": "user", "content": case["user_task"]}]:
        raise ValueError("Skill case requires the fixed single legal user task")
    for key in ("model_profile", "reasoning_effort", "thinking"):
        if request.get(key) != case[key]:
            raise ValueError("Skill case request parameter changed: " + key)
    if metadata.get("session_id") != case["session_id"]:
        raise ValueError("Skill case native session changed")
    if case["session_id"].startswith("project:"):
        if case["session_id"] != "project:" + case["scope_id"] or metadata.get("project_id") != case["scope_id"]:
            raise ValueError("Skill case Project/session binding changed")
    elif not case["session_id"].startswith("chat:") or metadata.get("project_id") is not None:
        raise ValueError("existing isolated chat or Project native session required")
    if request.get("attachments") or metadata.get("attachments"):
        raise ValueError("attachments cannot replace the registered Skill carrier")
    return case


def case_request(case: dict[str, Any]) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "session_id": case["session_id"],
        "campaign": {"kind": "skill-suite", "campaign_id": case["run_id"], **{
            k: case[k] for k in ("run_id", "suite_id", "risk_id", "case_id", "variant", "model_profile", "skill_id", "skill_version", "skill_hash")}},
    }
    if case["schema_version"] == 2:
        if case.get("target_context") != "global-general" or not case["session_id"].startswith("chat:"):
            raise ValueError("global Skill target cannot route to a Workspace session")
        metadata["campaign"]["target_context"] = "global-general"
    if case["session_id"].startswith("project:"):
        metadata["project_id"] = case["scope_id"]
    return {"messages": [{"role": "user", "content": case["user_task"]}], "metadata": metadata,
            **{k: case[k] for k in ("model_profile", "reasoning_effort", "thinking")}}
