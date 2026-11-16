"""Read-only partial formal run accounting; never infers an ASR from missing rows."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from sweep import runtime
from .d_gate import audit as audit_worker


PROFILES = ("default", "deepseek-v4.1-flash")
VARIANTS = ("normal", "attack")
KINDS = ("target", "management", "recovery", "cleanup", "generation", "judge")


def audit(root: Path, master_dir: Path) -> dict[str, Any]:
    master_path = master_dir / "formal-worker-plan.json"
    master = json.loads(master_path.read_text())
    auth = json.loads((master_dir / "formal-worker-authorization.json").read_text())
    if (master.get("kind") != "skill-formal-worker-plan"
            or master.get("target_rows") != 400
            or master.get("worker_count") != 100
            or len(master.get("workers", [])) != 100):
        raise ValueError("fixed 100 x 4 formal master plan required")
    authorized = (auth.get("actor") == "human-user"
                  and auth.get("decision") == "start-formal-target-collection"
                  and auth.get("run_id") == master["run_id"]
                  and auth.get("plan_sha256") == runtime.sha256_file(master_path)
                  and bool(auth.get("message_ref")) and bool(auth.get("confirmed_at")))
    if not authorized and auth != {"status": "not-authorized",
                                   "plan_sha256": runtime.sha256_file(master_path)}:
        raise ValueError("formal master authorization state invalid")
    rows = []
    counts = dict.fromkeys(KINDS, 0)
    stopped_workers = []
    for worker in master["workers"]:
        run = master_dir / worker["directory"]
        stage = json.loads((run / "d-smoke-plan.json").read_text())
        if (stage.get("case_id") != worker["case_id"]
                or runtime.sha256_file(run / "d-smoke-plan.json") != worker["plan_sha256"]
                or len(stage.get("rows", [])) != 4
                or {item["evaluation_key"] for item in stage["rows"]} !=
                   set(worker["evaluation_keys"])):
            raise ValueError("formal worker row partition drift")
        ledger_path = run / "call-ledger.json"
        ledger = json.loads(ledger_path.read_text()) if ledger_path.exists() else None
        result_path = run / "worker-result.json"
        worker_result = json.loads(result_path.read_text()) if result_path.exists() else None
        attempt_by_key = {}
        worker_audit = None
        if ledger is not None:
            for kind in KINDS:
                counts[kind] += ledger["counts"][kind]
            for attempt in ledger.get("attempts", []):
                if attempt.get("kind") == "target":
                    operation = attempt.get("operation_id", "")
                    if not operation.startswith("target:"):
                        raise ValueError("unexpected formal target operation identity")
                    key = operation.removeprefix("target:")
                    if key in attempt_by_key:
                        raise ValueError("duplicate target submission in one worker")
                    attempt_by_key[key] = attempt
            if len(attempt_by_key) != ledger["counts"]["target"]:
                raise ValueError("formal target ledger count differs from attempts")
            worker_audit = audit_worker(run, root)
        if (ledger is not None and ledger.get("stopped")) or (
                worker_result is not None and worker_result.get("status") == "stopped"):
            stopped_workers.append(worker["case_id"])
        gate_by_key = ({item["evaluation_key"]: item for item in worker_audit["rows"]}
                       if worker_audit is not None else {})
        for item in stage["rows"]:
            key = item["evaluation_key"]
            attempt = attempt_by_key.get(key)
            gate_row = gate_by_key.get(key)
            if attempt is None:
                status = "not-submitted"
            elif (attempt.get("outcome") == "completed"
                  and gate_row is not None
                  and gate_row.get("status") == "evidence-valid-pending-review"):
                status = "evidence-valid-pending-review"
            elif attempt.get("outcome") == "unknown":
                status = "upstream-terminal-unknown"
            elif attempt.get("outcome") != "completed":
                status = "target-error"
            else:
                status = "target-completed-evidence-incomplete"
            rows.append({"case_id": worker["case_id"], "evaluation_key": key,
                "model_profile": item["model_profile"], "variant": item["variant"],
                "status": status, "target_outcome": attempt.get("outcome") if attempt else None,
                "worker_directory": worker["directory"]})
    if len(rows) != 400 or len({item["evaluation_key"] for item in rows}) != 400:
        raise ValueError("formal progress must account for every planned row")
    caps = master["candidate_limits_unapproved"]
    budget_exceeded = any(counts[kind] > caps[kind]
                          for kind in ("target", "management", "recovery", "cleanup"))
    if counts["recovery"] > counts["management"]:
        raise ValueError("recovery GET count exceeds the total management HTTP count")
    unexpected_non_target_calls = counts["generation"] != 0 or counts["judge"] != 0
    pending = runtime.read_ownership(root)
    model_results = {}
    for profile in PROFILES:
        model_rows = [item for item in rows if item["model_profile"] == profile]
        if len(model_rows) != 200:
            raise ValueError("formal progress model distribution drift")
        variants = {}
        for variant in VARIANTS:
            selected = [item for item in model_rows if item["variant"] == variant]
            if len(selected) != 100:
                raise ValueError("formal progress variant distribution drift")
            variants[variant] = {"planned": 100,
                "submitted": sum(item["target_outcome"] is not None for item in selected),
                "evidence_valid": sum(item["status"] == "evidence-valid-pending-review"
                                      for item in selected),
                "target_error": sum(item["status"] == "target-error" for item in selected),
                "terminal_unknown": sum(item["status"] == "upstream-terminal-unknown"
                                        for item in selected),
                "evidence_incomplete": sum(item["status"] == "target-completed-evidence-incomplete"
                                           for item in selected),
                "not_submitted": sum(item["status"] == "not-submitted" for item in selected)}
        model_results[profile] = variants
    valid_rows = sum(item["status"] == "evidence-valid-pending-review" for item in rows)
    if not authorized and any(counts[kind] for kind in
                              ("target", "management", "recovery", "cleanup", "generation", "judge")):
        status = "unauthorized-worker-attempts"
    elif not authorized:
        status = "not-authorized"
    elif pending:
        status = "pending-upstream"
    elif stopped_workers or budget_exceeded or unexpected_non_target_calls or any(item["status"] in {
            "target-error", "target-completed-evidence-incomplete",
            "upstream-terminal-unknown"} for item in rows):
        status = "stopped-needs-review"
    elif valid_rows == 400 and (master_dir / "formal-target-evidence.json").is_file():
        status = "target-collected-needs-review"
    else:
        status = "collecting"
    return {"kind": "skill-formal-progress-audit", "status": status,
        "master_plan_sha256": runtime.sha256_file(master_path),
        "authorization_valid": authorized,
        "planned_target_rows": 400, "submitted_target_attempts": counts["target"],
        "evidence_valid_rows": valid_rows,
        "call_accounting": counts, "budget_exceeded": budget_exceeded,
        "unexpected_non_target_calls": unexpected_non_target_calls,
        "stopped_worker_case_ids": stopped_workers,
        "pending_ownership_count": len(pending),
        "models": model_results, "rows": rows,
        "confirmed_breakthrough_numerator": None,
        "valid_attack_denominator": None,
        "formal_asr_final": False,
        "judge_status": "not-in-this-target-progress-audit"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--master", type=Path, required=True)
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    result = audit(args.project_root, args.master)
    if args.output is not None:
        if args.output.exists() or not args.output.parent.is_dir():
            raise ValueError("new progress output file required")
        runtime.write_json(args.output, result)
    print(json.dumps({key: result[key] for key in (
        "status", "planned_target_rows", "submitted_target_attempts",
        "evidence_valid_rows", "call_accounting", "pending_ownership_count",
        "confirmed_breakthrough_numerator", "valid_attack_denominator",
        "models")}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
