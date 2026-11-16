"""Discover and remove only run-owned package-gate sessions after a blocked gate."""
from __future__ import annotations

from datetime import datetime, timedelta
import json
from pathlib import Path
from typing import Any
from urllib.parse import quote

from sweep import runtime
from .package_gate_live import LivePackageGate
from .package_gate_runtime import validate_authorization
from .package_skill_gate import validate_plan


def _sessions(value: Any) -> list[dict[str, Any]]:
    found = []
    if isinstance(value, dict):
        if isinstance(value.get("session_id"), str):
            found.append(value)
        for item in value.values():
            found.extend(_sessions(item))
    elif isinstance(value, list):
        for item in value:
            found.extend(_sessions(item))
    return found


def discover(root: Path, run: Path) -> dict[str, Any]:
    plan = root / "skill-suites/benchmark-multi-risk/package-capability-gate/plan.json"
    auth = root / "skill-suites/benchmark-multi-risk/package-capability-gate/authorization-request.json"
    validate_plan(root, plan)
    validate_authorization(plan, auth, require_active=True)
    output = run / "cleanup-candidates.json"
    if output.exists():
        raise ValueError("package cleanup candidates already exist")
    ledger = json.loads((run / "ledger.json").read_text())
    windows = []
    for row in ledger["attempts"]:
        if "create-session" in row["operation_id"] and row["outcome"] == "completed":
            start = datetime.fromisoformat(row["submitted_at"].replace("Z", "+00:00"))
            end = datetime.fromisoformat(row["finished_at"].replace("Z", "+00:00"))
            windows.append((start - timedelta(seconds=2), end + timedelta(seconds=2)))
    if len(windows) != 4:
        raise ValueError("exactly four package gate session attempts required")
    first_receipt = run / "list-sessions.json"
    if first_receipt.exists():
        body = json.loads(first_receipt.read_text())["response"]["json"]
    else:
        with runtime.sweep_lock(root):
            runtime.require_free_shim_port()
            live = LivePackageGate(root, run)
            try:
                body, _ = live.request(run.name + ":cleanup:list-sessions", "GET",
                                       "/api/sessions?limit=100")
            finally:
                live.close()
    pages = [body]
    total = body.get("total", 0) if isinstance(body, dict) else 0
    if total > 100:
        tail_receipt = run / "list-sessions-tail.json"
        if tail_receipt.exists():
            tail = json.loads(tail_receipt.read_text())["response"]["json"]
        else:
            with runtime.sweep_lock(root):
                runtime.require_free_shim_port()
                live = LivePackageGate(root, run)
                try:
                    tail, _ = live.request(run.name + ":cleanup:list-sessions-tail", "GET",
                        "/api/sessions?limit=100&offset=" + str(max(0, total - 100)))
                finally:
                    live.close()
        pages.append(tail)
    candidates = {}
    # Three run-local receipts remain exact. The shared run's first receipt was
    # overwritten by its second create-session receipt; never guess that id.
    run_root = run.parent
    run_ids = sorted({row["operation_id"].split(":", 1)[0]
                      for row in ledger["attempts"] if "create-session" in row["operation_id"]})
    for run_id in run_ids:
        receipt = run_root / run_id / "create-session.json"
        if not receipt.is_file():
            continue
        body = json.loads(receipt.read_text()).get("response", {}).get("json", {})
        sid = body.get("session_id")
        if (isinstance(sid, str) and sid.startswith("chat:usr_70c01392582d:")
                and body.get("user_id") == "usr_70c01392582d"
                and body.get("session_type") == "general"):
            candidates[sid] = {"session_id": sid, "user_id": body["user_id"],
                "session_type": "general", "created_at": body.get("created_at"),
                "source_receipt": str(receipt.resolve())}
    for item in _sessions(pages):
        sid, created = item.get("session_id"), item.get("created_at")
        if not isinstance(created, str) or item.get("session_type") != "general":
            continue
        when = datetime.fromisoformat(created.replace("Z", "+00:00"))
        if (sid.startswith("chat:usr_70c01392582d:")
                and any(start <= when <= end for start, end in windows)):
            candidates[sid] = {"session_id": sid, "user_id": "usr_70c01392582d",
                "session_type": "general", "created_at": created}
    if len(candidates) != 3:
        raise ValueError("three exact run-owned package gate sessions required")
    result = {"kind": "package-gate-cleanup-candidates",
        "sessions": [candidates[key] for key in sorted(candidates)],
        "source_attempt_count": 4, "unresolved_session_attempts": 1,
        "execution_code_sha256": runtime.sha256_file(Path(__file__))}
    runtime.write_json(output, result)
    return {"discovered": 3, "unresolved_session_attempts": 1,
            "candidate_file": str(output)}


def cleanup(root: Path, run: Path) -> dict[str, Any]:
    path = run / "cleanup-candidates.json"
    value = json.loads(path.read_text())
    current_code = runtime.sha256_file(Path(__file__))
    if value.get("execution_code_sha256") != current_code:
        amendment_path = run / "cleanup-amendment.json"
        if not amendment_path.is_file():
            raise ValueError("package cleanup code drift")
        amendment = json.loads(amendment_path.read_text())
        if amendment != {"prior_candidate_sha256": runtime.sha256_file(path),
                         "prior_code_sha256": value.get("execution_code_sha256"),
                         "new_code_sha256": current_code,
                         "reason": "session detail GET returned 405; use verified live endpoint"}:
            raise ValueError("package cleanup amendment drift")
    output = run / "cleanup-result.json"
    if (output.exists() or len(value.get("sessions", [])) != 3
            or value.get("unresolved_session_attempts") != 1):
        raise ValueError("one three-session package cleanup with one unresolved attempt required")
    results = []
    with runtime.sweep_lock(root):
        runtime.require_free_shim_port()
        live = LivePackageGate(root, run)
        try:
            for index, item in enumerate(value["sessions"]):
                sid = item["session_id"]
                if (item.get("user_id") != "usr_70c01392582d"
                        or not sid.startswith("chat:usr_70c01392582d:")
                        or item.get("session_type") != "general"):
                    raise ValueError("package cleanup session ownership drift")
                encoded = quote(sid, safe="")
                body, _ = live.request(run.name + f":cleanup:pre-live-{index}", "GET",
                                       "/api/sessions/" + encoded + "/live")
                if not isinstance(body, dict) or body.get("active") is not False:
                    raise ValueError("package cleanup requires idle session")
                live.request(run.name + f":cleanup:delete-session-{index}", "DELETE",
                             "/api/sessions/" + encoded, kind="cleanup",
                             expected={200, 204})
                live.request(run.name + f":cleanup:absent-session-{index}", "GET",
                             "/api/sessions/" + encoded + "/live", expected={404})
                results.append({"session_id": sid, "deleted": True, "absent_404": True})
            counts = live.stage.state["counts"]
            global_counts = live.global_ledger.state["counts"]
        finally:
            live.close()
    result = {"kind": "package-gate-cleanup-result", "sessions": results,
        "all_deleted": True, "actual_calls": counts, "global_calls": global_counts,
        "execution_code_sha256": runtime.sha256_file(Path(__file__))}
    runtime.write_json(output, result)
    return result


def recover_unresolved(root: Path, run: Path) -> dict[str, Any]:
    output = run / "cleanup-unresolved-result.json"
    if output.exists() or not (run / "cleanup-result.json").is_file():
        raise ValueError("one post-cleanup unresolved recovery required")
    ledger = json.loads((run / "ledger.json").read_text())
    attempt = next((row for row in ledger["attempts"]
                    if row["operation_id"].endswith(":q:create-session")
                    and "package-reference-shared" in row["operation_id"]), None)
    if attempt is None:
        raise ValueError("missing overwritten Qwen session attempt")
    start = datetime.fromisoformat(attempt["submitted_at"].replace("Z", "+00:00"))
    end = datetime.fromisoformat(attempt["finished_at"].replace("Z", "+00:00"))
    with runtime.sweep_lock(root):
        runtime.require_free_shim_port()
        live = LivePackageGate(root, run)
        try:
            body, _ = live.request(run.name + ":cleanup:latest-session-recovery", "GET",
                                   "/api/sessions/latest", kind="recovery",
                                   expected={200, 404})
            candidate = body.get("session", body) if isinstance(body, dict) else {}
            sid, created = candidate.get("session_id"), candidate.get("created_at")
            matched = False
            if isinstance(sid, str) and isinstance(created, str):
                when = datetime.fromisoformat(created.replace("Z", "+00:00"))
                matched = (sid.startswith("chat:usr_70c01392582d:")
                           and start - timedelta(seconds=2) <= when <= end + timedelta(seconds=2))
            if matched:
                encoded = quote(sid, safe="")
                state, _ = live.request(run.name + ":cleanup:latest-live", "GET",
                    "/api/sessions/" + encoded + "/live")
                if state.get("active") is not False:
                    raise ValueError("latest package gate session is not idle")
                live.request(run.name + ":cleanup:delete-latest-session", "DELETE",
                    "/api/sessions/" + encoded, kind="cleanup", expected={200, 204})
                live.request(run.name + ":cleanup:absent-latest-session", "GET",
                    "/api/sessions/" + encoded + "/live", expected={404})
            counts, global_counts = live.stage.state["counts"], live.global_ledger.state["counts"]
        finally:
            live.close()
    result = {"kind": "package-gate-unresolved-session-recovery",
        "latest_matched_overwritten_attempt": matched,
        "session_deleted": matched, "session_absent_404": matched,
        "unresolved_session_attempts": 0 if matched else 1,
        "actual_calls": counts, "global_calls": global_counts,
        "execution_code_sha256": runtime.sha256_file(Path(__file__))}
    runtime.write_json(output, result)
    return result


def main(argv=None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("discover", "cleanup", "recover-unresolved"))
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--run", type=Path, required=True)
    args = parser.parse_args(argv)
    root, run = args.root.resolve(), args.run.resolve()
    if args.command == "discover":
        result = discover(root, run)
    elif args.command == "cleanup":
        result = cleanup(root, run)
    else:
        result = recover_unresolved(root, run)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
