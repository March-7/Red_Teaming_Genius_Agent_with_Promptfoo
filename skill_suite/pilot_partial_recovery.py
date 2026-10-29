"""Clean a source-proven partial Skill after pilot provisioning fails before target."""
from __future__ import annotations

import json
from pathlib import Path
import time
from urllib.parse import quote

from sweep import runtime
from .pilot_runtime import _call_limits, _verify_run, LiveTransport


def recover(root: Path, run: Path, case_id: str, row_id: str) -> dict:
    manifest, master, ledger = _verify_run(root, run)
    worker = next((row for row in master["workers"] if row["case_id"] == case_id), None)
    if worker is None:
        raise ValueError("pilot worker missing")
    case = json.loads(Path(worker["case_file"]).read_text())
    row_dir = run / case_id / row_id
    output = row_dir / "partial-provision-recovery.json"
    if output.exists() or (row_dir / "binding.json").exists():
        raise ValueError("one unbound partial provision required")
    create_session = json.loads((row_dir / "create-session.json").read_text())
    skill_receipts = list(row_dir.glob("*-create-skill.json"))
    if len(skill_receipts) != 1:
        raise ValueError("one partial private Skill receipt required")
    create_skill = json.loads(skill_receipts[0].read_text())
    session = create_session["response"]["body"]
    created = create_skill["response"]["body"]
    skill = created.get("skill", {})
    skill_id, session_id, principal = created.get("skill_id"), session.get("session_id"), session.get("user_id")
    if (not isinstance(skill_id, str) or skill.get("skill_id") != skill_id
            or skill.get("owner_id") != principal or skill.get("visibility") != "private"
            or not isinstance(session_id, str) or not session_id.startswith("chat:" + principal + ":")):
        raise ValueError("partial provision resource identity invalid")
    with runtime.sweep_lock(root) as lease:
        runtime.require_free_shim_port()
        transport = LiveTransport(root, run, case_id, lease, ledger)
        try:
            limits = _call_limits(case)
            path = "/api/skills/" + quote(skill_id, safe="")
            delete_receipt = row_dir / "partial-delete-skill.json"
            if delete_receipt.exists():
                prior = json.loads(delete_receipt.read_text())
                body = prior.get("response", {}).get("body", {})
                if (prior.get("response", {}).get("status") != 200
                        or body.get("status") != "deleted" or body.get("skill_id") != skill_id):
                    raise ValueError("prior partial Skill delete receipt invalid")
            else:
                current = transport.json_request(row_dir, row_id, limits, "partial-read-skill",
                                                 "GET", path)
                metadata = current.get("skill", {})
                if (metadata.get("skill_id") != skill_id or metadata.get("owner_id") != principal
                        or metadata.get("name") != skill.get("name")
                        or metadata.get("visibility") != "private"):
                    raise ValueError("partial Skill fresh readback drift")
                deleted = transport.json_request(row_dir, row_id, limits, "partial-delete-skill",
                                                 "DELETE", path, kind="cleanup")
                if deleted not in ({"status": "deleted", "skill_id": skill_id},
                                   {"deleted": True, "skill_id": skill_id}):
                    raise ValueError("partial Skill delete not confirmed")
            operation = run.name + ":" + case_id + ":" + row_id + ":partial-absent-skill"
            transport._reserve("management", operation, row_id, limits)
            started = time.monotonic()
            response = transport.service._client.get(
                transport.service.config.upstream_base_url.rstrip("/") + path,
                headers=transport.service._headers())
            receipt = {"request": {"method": "GET", "path": path},
                "response": {"status": response.status_code}, "observed_at": runtime.utc_now()}
            runtime.write_json(row_dir / "partial-absent-skill.json", receipt)
            if response.status_code != 404:
                ledger.finish(operation, "management-error", elapsed_s=time.monotonic() - started)
                raise ValueError("partial Skill absence not confirmed")
            ledger.finish(operation, "completed", elapsed_s=time.monotonic() - started)
            transport.registry.record(session_id, "session", "retained-session-" + row_id,
                "retained", owner_run_id=run.name, shared=False, environment="live",
                case_id=case_id, row_id=row_id)
            transport.registry.record(skill_id, "skill", skill["name"], "created",
                owner_run_id=run.name, shared=False, environment="live", case_id=case_id,
                row_id=row_id)
            transport.registry.record(skill_id, "skill", skill["name"], "cleaned",
                owner_run_id=run.name, shared=False, environment="live", case_id=case_id,
                row_id=row_id)
        finally:
            transport.close()
    result = {"kind": "skill-pilot-partial-provision-recovery", "case_id": case_id,
        "row_id": row_id, "target_calls": 0, "skill_deleted": True,
        "skill_absent_404": True, "session_retained": True,
        "actual_calls": ledger.case_counts(case_id),
        "execution_code_sha256": runtime.sha256_file(Path(__file__))}
    runtime.write_json(output, result)
    manifest["case_status"][case_id] = "provision-failed-cleaned"
    manifest["actual_calls"] = dict(ledger.state["counts"])
    runtime.write_json(run / "run-manifest.json", manifest)
    return result


def main(argv=None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--row-id", required=True)
    args = parser.parse_args(argv)
    print(json.dumps(recover(args.root.resolve(), args.run.resolve(), args.case_id, args.row_id),
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
