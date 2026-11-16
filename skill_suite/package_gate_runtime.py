"""Fail-closed authorization, ledger, run manifest, and evidence gate for package Skills."""
from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
from typing import Any

from sweep.runtime import durable_json, sha256_file, utc_now, write_json
from .package_skill_gate import LIMITS, fake_control_gate, validate_plan
from .stage_e_pilot import TOTAL_LIMITS


KINDS = tuple(LIMITS)
EXECUTION_FILES = ("skill_suite/package_skill_gate.py",
                   "skill_suite/package_gate_runtime.py",
                   "skill_suite/package_gate_live.py",
                   "skill_suite/pilot_ledger.py",
                   "skill_suite/http_accounting.py",
                   "sweep/sensitive_output_guard.cjs")


class PackageGateBudgetError(RuntimeError):
    pass


class PackageGateLedger:
    def __init__(self, path: Path, limits: dict[str, int] = LIMITS):
        if (set(limits) != set(KINDS) or any(type(value) is not int or value < 0
                                            for value in limits.values())
                or limits["retry"] != 0):
            raise PackageGateBudgetError("exact nonnegative zero-retry limits required")
        self.path, self.limits = path, dict(limits)
        if path.exists():
            self.state = json.loads(path.read_text())
            if self.state.get("limits") != self.limits:
                raise PackageGateBudgetError("package gate budget drift")
        else:
            self.state = {"schema_version": 1, "kind": "package-skill-gate-ledger",
                "limits": self.limits, "counts": dict.fromkeys(KINDS, 0), "attempts": [],
                "pending_sessions": []}
            self._save()

    def _save(self) -> None:
        durable_json(self.path, self.state)

    def reserve(self, kind: str, operation_id: str) -> None:
        if kind not in KINDS or not operation_id:
            raise PackageGateBudgetError("known package gate call kind required")
        if kind == "retry" or self.limits["retry"] != 0:
            raise PackageGateBudgetError("package gate retries are disabled")
        if any(row["operation_id"] == operation_id for row in self.state["attempts"]):
            raise PackageGateBudgetError("zero retry operation already exists")
        increments = {kind: 1}
        if kind == "recovery":
            increments["management"] = 1
        for key, amount in increments.items():
            if self.state["counts"][key] + amount > self.limits[key]:
                raise PackageGateBudgetError(key + " package gate budget exhausted")
        for key, amount in increments.items():
            self.state["counts"][key] += amount
        self.state["attempts"].append({"kind": kind, "operation_id": operation_id,
            "submitted_at": utc_now(), "outcome": "unknown"})
        self._save()

    def finish(self, operation_id: str, outcome: str) -> None:
        rows = [row for row in self.state["attempts"]
                if row["operation_id"] == operation_id]
        if len(rows) != 1 or rows[0]["outcome"] != "unknown" or not outcome:
            raise PackageGateBudgetError("one unfinished package operation required")
        rows[0].update(outcome=outcome, finished_at=utc_now())
        self._save()


AUTH_FIELDS = {"schema_version", "kind", "status", "actor", "decision", "message_ref",
               "effective_date", "plan_sha256", "limits", "resources",
               "allowed_actions", "excluded_actions"}


def validate_authorization(plan_path: Path, auth_path: Path, *, require_active: bool) -> dict[str, Any]:
    value = json.loads(auth_path.read_text())
    if not isinstance(value, dict) or set(value) != AUTH_FIELDS:
        raise ValueError("package gate authorization fields drift")
    if (value["schema_version"] != 1
            or value["kind"] != "genius-package-skill-gate-authorization"
            or value["plan_sha256"] != sha256_file(plan_path)
            or value["limits"] != LIMITS
            or value["resources"] != {"private_package_skills": 2,
                                      "general_sessions": 2, "projects": 0}
            or set(value["excluded_actions"]) != {"generation", "judge", "formal-target",
                "malicious-script", "external-network-from-package", "real-sensitive-data",
                "non-owned-resource", "project-workspace-routing", "retry", "publish", "share"}):
        raise ValueError("package gate authorization scope drift")
    if require_active:
        if (value["status"] != "active" or value["actor"] != "human-user"
                or value["decision"] != "start-package-skill-capability-gate"
                or not value["message_ref"] or not value["effective_date"]):
            raise ValueError("fresh human package gate authorization required")
    elif (value["status"] != "not-authorized" or value["actor"] is not None
          or value["decision"] is not None or value["message_ref"] is not None
          or value["effective_date"] is not None):
        raise ValueError("prepared package gate authorization must remain empty")
    return value


def preview(root: Path, plan_path: Path, auth_path: Path) -> dict[str, Any]:
    plan = validate_plan(root, plan_path)
    validate_authorization(plan_path, auth_path, require_active=False)
    return {"valid": True, "status": plan["status"], "online_authorization": "not-authorized",
        "target_calls": 0, "management_calls": 0, "recovery_calls": 0,
        "cleanup_calls": 0, "generation_calls": 0, "judge_calls": 0,
        "credential_reads": 0, "network_calls": 0}


def prepare_run(root: Path, run_id: str, plan_path: Path, auth_path: Path) -> dict[str, Any]:
    validate_plan(root, plan_path)
    validate_authorization(plan_path, auth_path, require_active=True)
    if not re.fullmatch(r"package-reference-[a-z0-9-]{8,80}", run_id):
        raise ValueError("neutral package gate run id required")
    run = root / "skill-suites/benchmark-multi-risk/package-capability-gate/runs" / run_id
    if run.exists():
        raise ValueError("new package gate run directory required")
    run.mkdir(parents=True)
    (run / "plan.snapshot.json").write_bytes(plan_path.read_bytes())
    (run / "authorization.snapshot.json").write_bytes(auth_path.read_bytes())
    shutil.copy2(root / "skill-suites/skill-task-scope-write/approval-policy.json",
                 run / "approval-policy.json")
    ledger = PackageGateLedger(run / "ledger.json")
    global_ledger_path = root / "skill-suites/benchmark-multi-risk/runs/pilot-standing-ledger.json"
    global_state = json.loads(global_ledger_path.read_text())
    if global_state.get("limits") != TOTAL_LIMITS:
        raise ValueError("package gate global standing budget drift")
    manifest = {"schema_version": 1, "kind": "genius-package-skill-gate-run",
        "run_id": run_id, "status": "prepared", "target_context": "global-general",
        "session_type": "general", "plan_file": str(plan_path.resolve()),
        "authorization_file": str(auth_path.resolve()),
        "plan_sha256": sha256_file(plan_path),
        "authorization_sha256": sha256_file(auth_path), "limits": LIMITS,
        "policy_sha256": sha256_file(run / "approval-policy.json"),
        "code_hashes": {name: sha256_file(root / name) for name in EXECUTION_FILES},
        "global_ledger_file": str(global_ledger_path.resolve()),
        "global_counts_at_prepare": global_state["counts"],
        "actual_calls": ledger.state["counts"], "models": {
            "default": "not-started", "deepseek-v4.1-flash": "not-started"},
        "generation_calls": 0, "judge_calls": 0, "formal_asr_eligible": False}
    write_json(run / "run-manifest.json", manifest)
    return {"run": str(run), "status": "prepared", "actual_calls": manifest["actual_calls"]}


def prepare_followup_run(root: Path, run_id: str, plan_path: Path, auth_path: Path,
                         prior_run: Path) -> dict[str, Any]:
    validate_plan(root, plan_path)
    validate_authorization(plan_path, auth_path, require_active=True)
    prior_manifest = json.loads((prior_run / "run-manifest.json").read_text())
    prior_ledger = json.loads((prior_run / "ledger.json").read_text())
    counts = prior_ledger.get("counts", {})
    download_policy_error = (prior_run / "download-package.json").is_file()
    if (prior_manifest.get("status") not in {
            "blocked-template-contract", "blocked-upload-validation", "prepared-followup",
            "blocked-package-test-http"}
            or prior_ledger.get("limits") != LIMITS
            or counts.get("target") != 0 or counts.get("generation") != 0
            or counts.get("judge") != 0 or counts.get("retry") != 0
            or counts.get("management", 0) > 64 or counts.get("cleanup", 0) > 8
            or (prior_manifest.get("status") == "prepared-followup"
                and not download_policy_error)):
        raise ValueError("one bounded pre-target package gate run required")
    for mode in ("shell", "sandbox"):
        if not (prior_run / ("template-" + mode + ".zip")).is_file():
            raise ValueError("prior official package template missing")
    result = prepare_run(root, run_id, plan_path, auth_path)
    run = Path(result["run"])
    for mode in ("shell", "sandbox"):
        shutil.copy2(prior_run / ("template-" + mode + ".zip"),
                     run / ("template-" + mode + ".zip"))
    carried = dict(prior_ledger)
    carried["carried_from"] = {"run": str(prior_run.resolve()),
        "manifest_sha256": sha256_file(prior_run / "run-manifest.json"),
        "ledger_sha256": sha256_file(prior_run / "ledger.json")}
    durable_json(run / "ledger.json", carried)
    manifest = json.loads((run / "run-manifest.json").read_text())
    manifest.update(status="prepared-followup", actual_calls=carried["counts"],
        prior_run_ref=carried["carried_from"])
    write_json(run / "run-manifest.json", manifest)
    return {"run": str(run), "status": "prepared-followup",
            "actual_calls": carried["counts"], "prior_run_ref": carried["carried_from"]}


def validate_evidence(package_path: Path, evidence_path: Path) -> dict[str, Any]:
    package = json.loads(package_path.read_text())
    evidence = json.loads(evidence_path.read_text())
    required = {"schema_version", "kind", "model_profile", "package", "receipts",
                "target_calls", "generation_calls", "judge_calls",
                "formal_asr_eligible"}
    if (set(evidence) != required or evidence["schema_version"] != 1
            or evidence["kind"] != "genius-package-skill-model-evidence"
            or evidence["model_profile"] not in {"default", "deepseek-v4.1-flash"}
            or evidence["package"] != package
            or evidence["target_calls"] != 1 or evidence["generation_calls"] != 0
            or evidence["judge_calls"] != 0 or evidence["formal_asr_eligible"] is not False):
        raise ValueError("package model evidence boundary drift")
    return fake_control_gate(package, evidence["receipts"])


def main(argv=None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("preview", "prepare-run", "prepare-followup"))
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--authorization", type=Path, required=True)
    parser.add_argument("--run-id")
    parser.add_argument("--prior-run", type=Path)
    args = parser.parse_args(argv)
    root = args.root.resolve()
    if args.command == "preview":
        result = preview(root, args.plan.resolve(), args.authorization.resolve())
    elif args.command == "prepare-run":
        if not args.run_id:
            raise ValueError("prepare-run requires run-id")
        result = prepare_run(root, args.run_id, args.plan.resolve(),
                             args.authorization.resolve())
    else:
        if not args.run_id or not args.prior_run:
            raise ValueError("prepare-followup requires run-id and prior-run")
        result = prepare_followup_run(root, args.run_id, args.plan.resolve(),
            args.authorization.resolve(), args.prior_run.resolve())
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
