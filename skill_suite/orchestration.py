"""Offline contract for an opaque Promptfoo Skill case and its managed execution.

The real Genius adapter is a separate readiness gate. This module exercises the
same frozen-task, private-Skill, session, ledger, guard, and oracle order with an
injected fake adapter; it cannot submit a live target.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from sweep import runtime
from .budget import Ledger
from .campaign import asset, matrix, validate_plan
from .file_oracle import normalize_session_artifacts
from .schema import identifier, text_hash


FIXTURE_LIMITS = {"target": 1, "management": 8, "recovery": 0, "cleanup": 1,
                  "generation": 0, "judge": 0, "activity_total_s": 300,
                  "activity_per_call_s": 300, "skills": 1, "scopes": 1, "sessions": 1}
SELECTION_FIELDS = {"case_id", "model_profile", "variant"}


def parse_selection(prompt: str) -> dict[str, str]:
    if not isinstance(prompt, str) or len(prompt) > 500:
        raise ValueError("opaque Promptfoo selection required")
    try:
        value = json.loads(prompt)
    except json.JSONDecodeError as exc:
        raise ValueError("opaque Promptfoo selection must be JSON") from exc
    if not isinstance(value, dict) or set(value) != SELECTION_FIELDS:
        raise ValueError("Skill body or task text cannot enter the Promptfoo target prompt")
    for key in SELECTION_FIELDS:
        identifier(value[key], key)
    if value["model_profile"] not in {"default", "deepseek-v4.1-flash"} or value["variant"] not in {"normal", "attack"}:
        raise ValueError("unknown model or variant")
    return value


def _operation(ledger: Ledger, kind: str, name: str, callback, *args):
    ledger.reserve(kind, name)
    try:
        result = callback(*args)
        ledger.finish(name, "completed")
        return result
    except Exception:
        ledger.finish(name, "adapter-error")
        raise


def execute_fixture(project_root: Path, source_root: Path, output: Path,
                    prompt: str, adapter: Any,
                    strategy_manifest: Path | None = None) -> dict[str, Any]:
    """Run one local fake case; rejects real generated/frozen sources."""
    selection = parse_selection(prompt)
    plan = json.loads((source_root / "campaign-plan.json").read_text())
    if plan["generation"]["origin"] != "offline-fixture":
        raise ValueError("fixture orchestrator cannot run a real generated source")
    cases = validate_plan(plan, source_root)
    rows = matrix(plan, cases)
    matches = [row for row in rows if all(row[key] == selection[key] for key in SELECTION_FIELDS)]
    if len(matches) != 1:
        raise ValueError("unique frozen case/model/variant required")
    row = matches[0]
    if row.get("target_context") != "global-general" or row.get("session_type") != "general":
        raise ValueError("formal Skill case must use the global general assistant")
    if output.exists() or not output.parent.is_dir():
        raise ValueError("new case output directory required")
    content = asset(source_root, row["skill_artifact"])
    if strategy_manifest is not None:
        from .strategy import candidate_for_row
        content = candidate_for_row(source_root, strategy_manifest, plan, row)
    if row["locators"]["record_id"] in row["user_task"]:
        raise ValueError("target artifact name leaked into the legal task")
    with runtime.sweep_lock(project_root):
        output.mkdir()
        ledger = Ledger(output / "call-ledger.json", FIXTURE_LIMITS)
        if hasattr(adapter, "bind_fixture_ledger"):
            adapter.bind_fixture_ledger(ledger)
        metered_control = getattr(adapter, "fixture_http_metered", False)
        def control(kind, operation, callback, *args):
            if metered_control:
                return callback(*args)
            return _operation(ledger, kind, operation, callback, *args)
        prefix = "fixture:" + row["evaluation_key"][:16]
        name = row["locators"]["resource_name"]
        try:
            created = control("management", prefix + ":create-skill",
                                 adapter.create_skill, name, content)
            readback = control("management", prefix + ":read-skill",
                                  adapter.read_skill, created["skill_id"])
            if (created.get("skill_id") != readback.get("skill_id") or readback.get("name") != name
                    or readback.get("instructions") != content
                    or readback.get("visibility") != "private"
                    or readback.get("owner_id") != adapter.principal_id):
                raise ValueError("private Skill identity/content readback mismatch")
            session = control("management", prefix + ":create-session",
                                 adapter.create_session)
            sid = session.get("session_id")
            if (session.get("user_id") != adapter.principal_id or
                    not isinstance(sid, str) or not sid.startswith("chat:" + adapter.principal_id + ":")):
                raise ValueError("native general session identity mismatch")
            before_payload = control("management", prefix + ":before",
                                        adapter.list_artifacts, sid)
            before, _, _ = normalize_session_artifacts(before_payload,
                expected_name=row["locators"]["record_id"])
            if before != {"artifact_state": None, "other_artifacts": []}:
                raise ValueError("isolated session must start empty")
            request = {"messages": [{"role": "user", "content": row["user_task"]}],
                "model_profile": row["model_profile"], "reasoning_effort": "high", "thinking": "on",
                "metadata": {"session_id": sid, "campaign": {
                    "kind": "skill-campaign", "campaign_id": plan["campaign_id"],
                    "case_id": row["case_id"], "variant": row["variant"],
                    "model_profile": row["model_profile"], "skill_id": created["skill_id"],
                    "skill_hash": text_hash(content), "target_context": "global-general"}}}
            result = _operation(ledger, "target", prefix + ":target", adapter.run_target, request)
            if result.get("terminal_status") != "completed" or result.get("session_id") != sid:
                raise ValueError("matching target terminal result required")
            calls = [event for event in result.get("tool_events", []) if event.get("event_type") == "tool_call"
                     and event.get("tool_name") == "skill_read" and
                     event.get("tool_input") == {"skill_name": name}]
            reads = [event for event in result.get("tool_events", []) if event.get("event_type") == "tool_result"
                     and event.get("tool_name") == "skill_read" and event.get("status") == "success"
                     and event.get("tool_call_id") in {call.get("tool_call_id") for call in calls}
                     and event.get("instructions") == content]
            if len(calls) != 1 or len(reads) != 1:
                raise ValueError("actual matching Skill selection and content read required")
            # Guard before the output can leave this provider for Promptfoo assertions.
            guarded_output = runtime.guard_output(result.get("output", ""), known_hashes="")
            after_payload = control("management", prefix + ":after",
                                       adapter.list_artifacts, sid)
            matches = [entry for entry in after_payload.get("artifacts", [])
                       if entry.get("filename") == row["locators"]["record_id"]]
            downloaded_hash = None
            artifact_id = None
            if matches:
                if len(matches) != 1 or len(after_payload["artifacts"]) != 1:
                    raise ValueError("ambiguous target artifact")
                entry = matches[0]
                if entry.get("scope_id") != sid or not isinstance(entry.get("file_token"), str):
                    raise ValueError("listed artifact session/token identity missing")
                body = control("management", prefix + ":download",
                                  adapter.download, entry["file_token"])
                if not isinstance(body, bytes) or not 0 < len(body) <= 4096:
                    raise ValueError("independent artifact bytes required")
                downloaded_hash = hashlib.sha256(body).hexdigest()
            after, _, artifact_id = normalize_session_artifacts(after_payload,
                expected_name=row["locators"]["record_id"], downloaded_sha256=downloaded_hash)
            if artifact_id is not None:
                control("cleanup", prefix + ":delete",
                           adapter.delete_artifact, sid, artifact_id)
                restored_payload = control("management", prefix + ":restored",
                                              adapter.list_artifacts, sid)
                restored, _, _ = normalize_session_artifacts(restored_payload,
                    expected_name=row["locators"]["record_id"])
                if restored != before:
                    raise ValueError("target artifact restoration failed")
            evidence = {"kind": "offline-skill-orchestration-fixture", "environment": "offline-fixture",
                "selection": selection, "case_id": row["case_id"], "model_profile": row["model_profile"],
                "variant": row["variant"], "skill_id": created["skill_id"],
                "skill_hash": text_hash(content), "skill_content_read": True,
                "strategy_candidate_sha256": text_hash(content) if strategy_manifest is not None else None,
                "native_session_id": sid, "fixed_task_hash": row["task_sha256"],
                "output": guarded_output, "before": before, "after": after,
                "artifact_id": artifact_id, "downloaded_sha256": downloaded_hash,
                "independent_effect_observed": artifact_id is not None,
                "live_finding": False, "formal_ready": False,
                "call_accounting": ledger.state["counts"]}
            runtime.write_json(output / "fixture-result.json", evidence)
            return evidence
        except Exception as exc:
            ledger.stop("fixture-error:" + type(exc).__name__)
            raise
        finally:
            runtime.write_json(output / "call-summary.json", ledger.state)
