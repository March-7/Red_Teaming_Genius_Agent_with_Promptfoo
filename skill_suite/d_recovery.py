"""One-shot, metered read-only reconciliation for a stopped D ask_user target."""
from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
from urllib.parse import quote
from typing import Any

from dotenv import load_dotenv

from sweep import runtime
from .budget import Ledger
from .http_accounting import meter_client
from .d_smoke_plan import LIMITS


def prepare(root: Path, run: Path) -> dict[str, Any]:
    stage_path = run / "d-smoke-plan.json"
    stage = json.loads(stage_path.read_text())
    auth_path = run / "d-smoke-authorization.json"
    auth = json.loads(auth_path.read_text())
    ledger = json.loads((run / "call-ledger.json").read_text())
    packet_path = run / "d-recovery-plan.json"
    if (packet_path.exists() or stage.get("phase") != "D"
            or stage.get("source_origin") != "provider-response"
            or auth.get("actor") != "human-user" or auth.get("decision") != "start"
            or auth.get("plan_sha256") != runtime.sha256_file(stage_path)
            or stage.get("limits") != LIMITS or ledger.get("stopped") != "target-error"
            or ledger.get("counts", {}).get("recovery") != 0):
        raise ValueError("one stopped, approved D stage with unused recovery budget required")
    pending = [item for item in runtime.read_ownership(root).values()
               if item.get("run_id") == stage["run_id"]]
    if len(pending) != 1:
        raise ValueError("exactly one D pending session required")
    session_id = pending[0]["session_id"]
    trace_path = run / "genius_trace.jsonl"
    failures = [json.loads(line) for line in trace_path.read_text().splitlines()
                if line.strip() and json.loads(line).get("kind") == "request_failed"]
    if len(failures) != 1:
        raise ValueError("one persisted D target failure required")
    failure = failures[0]
    summary = failure.get("trace_summary") or {}
    question = summary.get("human_input_request") or {}
    key = failure.get("evaluation_key")
    row = next((item for item in stage["rows"] if item["evaluation_key"] == key), None)
    binding_path = run / ("binding-" + str(key) + ".json")
    binding = json.loads(binding_path.read_text())
    if (failure.get("code") != "genius_human_input_required"
            or failure.get("variant") != "attack"
            or summary.get("upstream_session_id") != session_id
            or question.get("tool") != "ask_user" or question.get("blocking") is not True
            or not question.get("question_id") or not summary.get("request_id")
            or question.get("request_id") != summary["request_id"]
            or not row or binding.get("session_id") != session_id
            or binding.get("evaluation_key") != key):
        raise ValueError("pending D ownership differs from the saved ask_user evidence")
    path = "/api/sessions/" + quote(session_id, safe="")
    packet = {"kind": "skill-d-read-only-recovery", "status": "prepared-offline",
        "run_id": stage["run_id"], "parent_plan_sha256": runtime.sha256_file(stage_path),
        "parent_authorization_sha256": runtime.sha256_file(auth_path),
        "source_failure_trace_sha256": runtime.sha256_file(trace_path),
        "session_id": session_id, "evaluation_key": key,
        "request_id": summary["request_id"], "question_id": question["question_id"],
        "effect_artifact_name": row["effect_artifact_name"],
        "paths": {"messages": path + "/messages?limit=200", "live": path + "/live",
                  "artifacts": path + "/artifacts"},
        "max_recovery_gets": 3, "method": "GET",
        "execution_code_sha256": runtime.sha256_file(Path(__file__))}
    runtime.write_json(packet_path, packet)
    return {"packet_path": str(packet_path), "run_id": stage["run_id"],
            "max_recovery_gets": 3, "actual_recovery_gets": 0}


def execute(root: Path, run: Path) -> dict[str, Any]:
    packet_path = run / "d-recovery-plan.json"
    packet = json.loads(packet_path.read_text())
    stage_path = run / "d-smoke-plan.json"
    stage = json.loads(stage_path.read_text())
    auth_path = run / "d-smoke-authorization.json"
    auth = json.loads(auth_path.read_text())
    sid = packet.get("session_id")
    base = "/api/sessions/" + quote(str(sid), safe="")
    paths = {"messages": base + "/messages?limit=200", "live": base + "/live",
             "artifacts": base + "/artifacts"}
    if (packet.get("kind") != "skill-d-read-only-recovery"
            or packet.get("status") != "prepared-offline"
            or packet.get("run_id") != stage.get("run_id")
            or packet.get("parent_plan_sha256") != runtime.sha256_file(stage_path)
            or packet.get("parent_authorization_sha256") != runtime.sha256_file(auth_path)
            or packet.get("source_failure_trace_sha256") != runtime.sha256_file(run / "genius_trace.jsonl")
            or packet.get("execution_code_sha256") != runtime.sha256_file(Path(__file__))
            or packet.get("method") != "GET" or packet.get("paths") != paths
            or packet.get("max_recovery_gets") != 3 or stage.get("limits") != LIMITS
            or auth.get("actor") != "human-user" or auth.get("decision") != "start"
            or auth.get("plan_sha256") != runtime.sha256_file(stage_path)):
        raise ValueError("D recovery source, code, request shape or authorization drift")
    for label in paths:
        for suffix in ("http", "body"):
            if (run / ("d-recovery-" + label + "-" + suffix + ".json")).exists():
                raise ValueError("zero retry: D recovery GET already attempted")
    with runtime.sweep_lock(root, recovery_run=stage["run_id"]):
        runtime.require_free_shim_port()
        pending_key = stage["run_id"] + "/" + sid
        if pending_key not in runtime.read_ownership(root):
            raise ValueError("matching D pending ownership no longer exists")
        ledger = Ledger(run / "call-ledger.json", LIMITS)
        if ledger.state["stopped"] != "target-error" or ledger.state["counts"]["recovery"] != 0:
            raise ValueError("D recovery ledger state changed")
        # The D authorization already reserves four GETs inside the 64 management cap.
        load_dotenv(root / ".env", override=True)
        from shim.genius_service import GeniusService, ShimConfig
        config = replace(ShimConfig.from_env(), upstream_retry_attempts=0,
            token_refresh_margin_s=0, hard_timeout_s=300,
            human_input_continue_plugin="", human_input_max_rounds=0,
            approval_policy_file=str(run / "approval-policy.json"),
            trace_jsonl_path=str(run / "genius_trace.jsonl"),
            lifecycle_jsonl_path=str(run / "session_lifecycle.jsonl"), trace_raw_events=True)
        service = GeniusService(config)
        refs = {}
        def get(label: str) -> dict[str, Any]:
            path = paths[label]
            receipt_path = run / ("d-recovery-" + label + "-http.json")
            body_path = run / ("d-recovery-" + label + "-body.json")
            receipt = {"request": {"method": "GET", "path": path},
                       "response": None, "environment": "live", "observed_at": runtime.utc_now()}
            records: list[dict[str, Any]] = []
            try:
                with meter_client(service._client, ledger, "d-recovery:" + label,
                                  management_kind="recovery") as records:
                    body = service._request_json("GET", path)
                if len(records) != 1 or records[0]["outcome"] != "completed":
                    raise ValueError("one successful D recovery HTTP GET required")
                receipt["response"] = {"status": records[0]["status_code"], "body": body}
                runtime.write_json(body_path, body)
                refs[label] = {"file": body_path.name, "sha256": runtime.sha256_file(body_path)}
                return body
            except Exception as exc:
                receipt["error"] = type(exc).__name__
                raise
            finally:
                receipt["http_attempts"] = records
                runtime.write_json(receipt_path, receipt)
        try:
            messages = get("messages")
            live = get("live")
            released = False
            if (isinstance(live, dict) and live.get("active") is False
                    and live.get("started_at_ms") is None):
                proof = {"session_id": sid, "disposition": "inactive-awaiting-user",
                         "request_id": packet["request_id"],
                         "live_ref": refs["live"], "messages_ref": refs["messages"]}
                proof_path = run / "d-recovery-idle-proof.json"
                runtime.write_json(proof_path, proof)
                runtime.resolve_idle_user_wait(root, stage["run_id"], sid, proof_path)
                released = True
            if not released:
                packet.update(status="still-live", ownership_released=False,
                              recovery_calls=ledger.state["counts"]["recovery"])
                runtime.write_json(packet_path, packet)
                return {"ownership_released": False, "active": live.get("active"),
                        "recovery_calls": ledger.state["counts"]["recovery"]}
            artifacts = get("artifacts")
            items = artifacts.get("artifacts") if isinstance(artifacts, dict) else None
            if not isinstance(items, list) or any(not isinstance(item, dict) or
                    item.get("scope_id") != sid for item in items):
                raise ValueError("D recovery artifact scope readback invalid")
            matches = [item for item in items if item.get("filename") == packet["effect_artifact_name"]]
            packet.update(status="idle-computation-released", ownership_released=True,
                          question_answered=False, target_completed_claim=False,
                          artifact_ref=refs["artifacts"], artifact_match_count=len(matches),
                          recovery_calls=ledger.state["counts"]["recovery"])
            runtime.write_json(packet_path, packet)
            return {"ownership_released": True, "active": False,
                    "artifact_match_count": len(matches),
                    "recovery_calls": ledger.state["counts"]["recovery"]}
        finally:
            service.close()
