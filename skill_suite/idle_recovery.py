"""One-request, separately authorized recovery of an idle Genius ask_user session."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import quote

from sweep import runtime
from .budget import Ledger
from .evidence import read_ref
from .general_a import ManagementSession
from .http_accounting import meter_client
from .schema import canonical_hash


LIMITS = {"target": 0, "management": 1, "recovery": 1, "cleanup": 0,
          "generation": 0, "judge": 0, "activity_total_s": 0,
          "activity_per_call_s": 0, "skills": 0, "scopes": 0, "sessions": 0}


def scope_hash(packet: dict[str, Any]) -> str:
    return canonical_hash({key: value for key, value in packet.items()
                           if key not in {"status", "authorization", "result"}})


def authorize(packet_path: Path, message_ref: str) -> dict[str, Any]:
    """Record an actual human reply; never manufacture consent."""
    packet = json.loads(packet_path.read_text())
    if (packet.get("status") != "prepared-offline" or packet.get("authorization") is not None
            or packet.get("limits") != LIMITS or not message_ref):
        raise ValueError("fresh one-request recovery packet and human reply required")
    packet["authorization"] = {"actor": "human-user", "decision": "start-idle-read-only-recovery",
        "run_id": packet["run_id"], "scope_hash": scope_hash(packet),
        "message_ref": message_ref, "confirmed_at": runtime.utc_now()}
    packet["status"] = "authorized"
    runtime.write_json(packet_path, packet)
    return packet["authorization"]


def execute(root: Path, run: Path, packet_path: Path) -> dict[str, Any]:
    packet = json.loads(packet_path.read_text())
    authorization = packet.get("authorization") or {}
    if (packet.get("status") != "authorized" or packet.get("limits") != LIMITS
            or authorization.get("actor") != "human-user"
            or authorization.get("decision") != "start-idle-read-only-recovery"
            or authorization.get("run_id") != packet.get("run_id")
            or authorization.get("scope_hash") != scope_hash(packet)
            or not authorization.get("message_ref") or not authorization.get("confirmed_at")
            or packet_path.parent.resolve() != run.resolve()):
        raise ValueError("phase/run/scope-bound idle recovery authorization required")
    if runtime.sha256_file(Path(__file__)) != packet.get("execution_code_sha256"):
        raise ValueError("idle recovery execution code changed")
    if packet["run_id"] != run.name or packet.get("method") != "GET":
        raise ValueError("idle recovery is read-only and run-bound")
    sid = packet["session_id"]
    path = "/api/sessions/" + quote(sid, safe="") + "/live"
    if packet.get("path") != path:
        raise ValueError("unobserved idle recovery path")
    messages = read_ref(run, packet["messages_ref"])
    raw_messages = read_ref(run, packet["raw_messages_ref"])
    if (not isinstance(raw_messages, dict) or not isinstance(raw_messages.get("request"), dict)
            or not isinstance(raw_messages.get("response"), dict)
            or raw_messages["response"].get("body") != messages
            or raw_messages.get("request", {}).get("method") != "GET"
            or raw_messages["request"].get("path") !=
            "/api/sessions/" + quote(sid, safe="") + "/messages?limit=200"):
        raise ValueError("persisted messages do not match the metered recovery GET")
    for name in ("B2-idle-live-http.json", "B2-idle-live-body.json", "B2-idle-proof.json"):
        if (run / name).exists():
            raise ValueError("zero retries: idle recovery already attempted")
    with runtime.sweep_lock(root, recovery_run=run.name) as lease:
        runtime.require_free_shim_port()
        key = run.name + "/" + sid
        if key not in runtime.read_ownership(root):
            raise ValueError("matching pending ownership no longer exists")
        manifest = json.loads((run / "run-manifest.json").read_text())
        if manifest.get("status") != "pending-upstream" or manifest.get("run_id") != run.name:
            raise ValueError("stopped pending run required")
        ledger = Ledger(run / "idle-recovery-ledger.json", LIMITS)
        manager = ManagementSession(root, run, lease)
        receipt: dict[str, Any] = {"request": {"method": "GET", "path": path},
            "environment": "live", "observed_at": runtime.utc_now(), "response": None}
        records: list[dict[str, Any]] = []
        try:
            try:
                with meter_client(manager.service._client, ledger, "B2-idle-live",
                                  management_kind="recovery") as records:
                    payload = manager.service._request_json("GET", path)
                receipt["response"] = {"status": records[-1]["status_code"], "body": payload}
            except Exception as exc:
                receipt["error"] = type(exc).__name__
                ledger.stop("idle-live-error:" + type(exc).__name__)
                raise
            finally:
                runtime.write_json(run / "B2-idle-live-http.json", receipt)
            if not isinstance(payload, dict) or type(payload.get("active")) is not bool:
                raise ValueError("live status response shape unverified")
            runtime.write_json(run / "B2-idle-live-body.json", payload)
            released = False
            if payload["active"] is False and payload.get("started_at_ms") is None:
                proof = {"session_id": sid, "disposition": "inactive-awaiting-user",
                         "request_id": packet["request_id"],
                         "live_ref": {"file": "B2-idle-live-body.json",
                                      "sha256": runtime.sha256_file(run / "B2-idle-live-body.json")},
                         "messages_ref": packet["messages_ref"]}
                runtime.write_json(run / "B2-idle-proof.json", proof)
                runtime.resolve_idle_user_wait(root, run.name, sid, run / "B2-idle-proof.json")
                released = True
            packet["status"] = "idle-computation-released" if released else "still-live"
            packet["result"] = {"request_count": ledger.state["counts"]["recovery"],
                                "active": payload["active"], "ownership_released": released,
                                "question_answered": False, "task_completed_claim": False}
            runtime.write_json(packet_path, packet)
            if released:
                summary_path = run / "summary.json"
                summary = json.loads(summary_path.read_text())
                summary["upstream_ownership_pending"] = False
                summary["idle_recovery"] = {"compute_ownership_released": True,
                    "question_unanswered": True, "task_completed_claim": False,
                    "recovery_calls": ledger.state["counts"]["recovery"]}
                runtime.write_json(summary_path, summary)
                with (run / "summary.md").open("a", encoding="utf-8") as handle:
                    handle.write("\n只读 `/live` 与原 `ask_user` 回执证明会话已无活动流；仅解除计算 ownership。问题仍待回答，B2 对照仍无效。\n")
            manifest.setdefault("recovery_addenda", []).append({"packet": packet_path.name,
                "ledger": "idle-recovery-ledger.json", "http_receipt": "B2-idle-live-http.json"})
            manifest["status"] = "stopped-control-invalid" if released else "pending-upstream"
            manifest["artifact_hashes"].update({p.name: runtime.sha256_file(p) for p in run.iterdir()
                if p.is_file() and p.name != "run-manifest.json"})
            runtime.write_json(run / "run-manifest.json", manifest)
            return packet["result"]
        finally:
            manager.close()
