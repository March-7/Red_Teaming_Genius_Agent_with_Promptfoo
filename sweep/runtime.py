"""Shared local run facilities. Importing this module does not load credentials."""
from __future__ import annotations

from contextlib import contextmanager
import datetime as dt
import fcntl
import hashlib
import json
from pathlib import Path
import socket
import subprocess
import sys
import time
import threading
from typing import Any, Callable

import httpx

POLICY_REQUIRED_FIELDS = ("run_id", "session_id", "tool", "action_id", "resource")
GUARD_PATH = Path(__file__).resolve().with_name("sensitive_output_guard.cjs")


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def durable_json(path: Path, value: Any) -> None:
    """Atomic, fsynced state used for budgets and unresolved upstream ownership."""
    import os
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)
    descriptor = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def validate_policy_document(document: Any, label: str) -> list[str]:
    if not isinstance(document, dict):
        return [f"{label}: policy must be a JSON object"]
    rules = document.get("rules")
    if not isinstance(rules, list) or len(rules) != 1:
        return [f"{label}: policy must contain exactly one rule"]
    rule = rules[0]
    if not isinstance(rule, dict):
        return [f"{label}: policy rule must be an object"]
    errors = []
    for field in POLICY_REQUIRED_FIELDS:
        value = rule.get(field)
        if not isinstance(value, str) or not value.strip():
            errors.append(f"{label}: missing or empty policy field {field}")
        elif any(char in value for char in ("*", "?")):
            errors.append(f"{label}: policy field {field} contains a wildcard")
        elif "{{" in value or "}}" in value:
            errors.append(f"{label}: policy field {field} is not exact")
    if not isinstance(document.get("protocol"), dict):
        errors.append(f"{label}: policy protocol must be an object")
    return errors


def snapshot_policy(policy_bytes: bytes, destination: Path, *, unbound: bool = False) -> str:
    document = json.loads(policy_bytes)
    errors = validate_policy_document(document, str(destination))
    if errors:
        raise ValueError("; ".join(errors))
    if unbound and any(not document["rules"][0][key].startswith("unbound-")
                       for key in POLICY_REQUIRED_FIELDS[1:]):
        raise ValueError("Skill suite requires an unbound approval policy")
    destination.write_bytes(policy_bytes)
    return sha256_file(destination)


def mount_sensitive_guard(config: dict[str, Any], manifest: dict[str, Any]) -> None:
    if not GUARD_PATH.is_file():
        raise ValueError("missing sensitive output guard")
    transform = GUARD_PATH.as_uri()
    options = config.setdefault("defaultTest", {}).setdefault("options", {})
    if options.get("transform") not in (None, transform):
        raise ValueError("conflicting output transform bypasses the sensitive output guard")
    options["transform"] = transform
    for test in config.get("tests", []):
        case_options = test.get("options") or {}
        if "transform" in case_options and case_options["transform"] != transform:
            raise ValueError("per-test output transform would bypass the sensitive output guard")
    manifest["sensitive_output_guard"] = {
        "placement": "defaultTest.options.transform", "transform": transform,
        "sha256": sha256_file(GUARD_PATH), "per_test_overrides_checked": True,
    }


class SensitiveOutputError(RuntimeError):
    pass


def guard_output(output: str, *, known_hashes: str = "") -> str:
    """Run the actual shared Node guard before exposing text to any consumer."""
    import os
    script = ("const fs=require('node:fs');const guard=require(process.argv[1]);"
              "try{guard(fs.readFileSync(0,'utf8'));}"
              "catch(e){process.exit(23);}")
    result = subprocess.run(
        ["node", "-e", script, str(GUARD_PATH)], input=output, text=True,
        capture_output=True, timeout=10,
        env={**os.environ, "GENIUS_SENSITIVE_VALUE_HASHES": known_hashes},
    )
    if result.returncode:
        raise SensitiveOutputError("SENSITIVE_OUTPUT_REVIEW_REQUIRED")
    return output


def sensitive_value_hashes(root: Path) -> str:
    """Only called by confirmed execution paths; never by offline preview/replay."""
    from dotenv import dotenv_values
    values: set[str] = set()
    for name in (".env", ".env.promptfoo"):
        for key, value in dotenv_values(root / name).items():
            if not value or len(value) < 8:
                continue
            if any(marker in key.lower() for marker in ("key", "secret", "token", "password", "authorization")):
                values.add(value)
                if value.startswith("Bearer "):
                    values.add(value.removeprefix("Bearer "))
    return ",".join(sorted(hashlib.sha256(v.encode()).hexdigest() for v in values))


def require_free_shim_port() -> None:
    try:
        connection = socket.create_connection(("127.0.0.1", 4030), timeout=0.5)
    except ConnectionRefusedError:
        return
    with connection:
        raise RuntimeError("127.0.0.1:4030 is occupied; stop the existing shim before running a sweep")


def stop_shim(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def start_shim(root: Path, env: dict[str, str], *, port_check: Callable[[], None] | None = None) -> subprocess.Popen[bytes]:
    (port_check or require_free_shim_port)()
    process = subprocess.Popen(
        [sys.executable, "-m", "shim.genius_service", "--host", "127.0.0.1", "--port", "4030"],
        cwd=root, env=env,
    )
    try:
        for _ in range(80):
            if process.poll() is not None:
                raise RuntimeError("run-local Genius shim exited during startup")
            try:
                response = httpx.get("http://127.0.0.1:4030/health", timeout=0.5, trust_env=False)
                if response.status_code == 200:
                    payload = response.json()
                    if payload.get("pid") != process.pid:
                        raise RuntimeError("shim health belongs to a different process")
                    if payload.get("credential_configured") is not True:
                        raise RuntimeError("run-local Genius shim has no configured credential")
                    return process
            except httpx.HTTPError:
                pass
            time.sleep(0.1)
        raise RuntimeError("run-local Genius shim did not become healthy")
    except BaseException:
        stop_shim(process)
        raise


def ownership_path(root: Path) -> Path:
    return root / "logs" / ".upstream-ownership.json"


def read_ownership(root: Path) -> dict[str, Any]:
    path = ownership_path(root)
    return json.loads(path.read_text()) if path.exists() else {}


def record_pending(root: Path, run_id: str, session_id: str, evidence: str) -> None:
    """Caller must hold the project lock. Unknown activity survives process exit."""
    rows = read_ownership(root)
    key = f"{run_id}/{session_id}"
    rows[key] = {"run_id": run_id, "session_id": session_id, "evidence": evidence,
                 "status": "unknown", "recorded_at": utc_now()}
    durable_json(ownership_path(root), rows)


def resolve_pending(root: Path, run_id: str, session_id: str, terminal: dict[str, Any]) -> None:
    if terminal.get("session_id") != session_id or terminal.get("status") not in {"completed", "failed", "cancelled"}:
        raise ValueError("matching upstream terminal evidence required")
    evidence = Path(terminal.get("evidence_path", ""))
    if not evidence.is_file() or sha256_file(evidence) != terminal.get("evidence_hash"):
        raise ValueError("terminal evidence file/hash required")
    payload = json.loads(evidence.read_text())
    if payload.get("session_id") != session_id or payload.get("status") != terminal["status"]:
        raise ValueError("terminal evidence content does not match")
    rows = read_ownership(root)
    rows.pop(f"{run_id}/{session_id}", None)
    durable_json(ownership_path(root), rows)


def resolve_idle_user_wait(root: Path, run_id: str, session_id: str, evidence: Path) -> None:
    """Release computation ownership after independent idle + ask_user readback.

    The unanswered question remains in the stopped run. This is neither a
    completed task nor permission to answer it or submit another target.
    """
    proof = json.loads(evidence.read_text())
    if proof.get("session_id") != session_id or proof.get("disposition") != "inactive-awaiting-user":
        raise ValueError("matching idle user-wait evidence required")
    def read(ref):
        path = (evidence.parent / ref["file"]).resolve()
        if not path.is_relative_to(evidence.parent.resolve()) or sha256_file(path) != ref["sha256"]:
            raise ValueError("idle readback path/hash mismatch")
        return json.loads(path.read_text())
    live = read(proof["live_ref"]); messages = read(proof["messages_ref"]).get("messages", [])
    if live.get("active") is not False or live.get("started_at_ms") is not None:
        raise ValueError("server has not confirmed absence of a live stream")
    matching = [m for m in messages if m.get("session_id") == session_id and m.get("request_id") == proof.get("request_id")
                and m.get("tool_name") == "ask_user" and m.get("role") == "tool"]
    waiting = []
    for message in matching:
        try: result = json.loads(message.get("tool_result") or "{}")
        except (ValueError, TypeError): continue
        if result.get("status") == "awaiting_user" and result.get("blocking") is True and result.get("question_id"):
            waiting.append(result)
    if len(waiting) != 1: raise ValueError("matching structured pending user question required")
    rows = read_ownership(root); key = f"{run_id}/{session_id}"
    if key not in rows: raise ValueError("unknown ownership is not registered for this run/session")
    rows.pop(key)
    durable_json(ownership_path(root), rows)


@contextmanager
def sweep_lock(root: Path, *, recovery_run: str | None = None):
    path = root / "logs" / ".sweep.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("another plugin sweep is active; wait for its completion")
        try:
            pending = read_ownership(root)
            if pending and (not recovery_run or any(row["run_id"] != recovery_run for row in pending.values())):
                raise RuntimeError("unresolved upstream ownership; read-only recovery required")
            lease = RunLease(root)
            try:
                yield lease
            finally:
                lease.active = False
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


class RunLease:
    """An active project lock passed to lifecycle operations; no nested flock."""
    def __init__(self, root: Path):
        import os
        self.root, self.active = root.resolve(), True
        self.thread, self.pid = threading.get_ident(), os.getpid()

    def require_active(self) -> None:
        import os
        if not self.active or self.thread != threading.get_ident() or self.pid != os.getpid():
            raise RuntimeError("active project run lock required before lifecycle operation")
