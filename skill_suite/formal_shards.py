"""Prepare 100 inert, source-bound D-shaped workers for a future formal round.

The workers reuse the live-verified general Skill API path. No worker is
authorized here, and no target, management, or Judge request is submitted.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any

from sweep import runtime
from . import campaign
from .d_smoke_plan import (prepare as prepare_worker, LIMITS as WORKER_LIMITS,
                           CODE_FILES as WORKER_CODE_FILES, CODE_ROOT as WORKER_CODE_ROOT,
                           MIN_SKILL_AGE_SECONDS)


def prepare(root: Path, source: Path, launch_worksheet: Path,
            output: Path, nonce: str) -> dict[str, Any]:
    if not re.fullmatch(r"[0-9a-f]{8}", nonce):
        raise ValueError("eight-hex formal planning nonce required")
    if output.exists() or not output.parent.is_dir() or not output.resolve().is_relative_to(
            (root / "skill-suites/skill-task-scope-write/runs").resolve()):
        raise ValueError("new ignored formal planning directory required")
    frozen = campaign.verify_frozen(source.parent)
    plan = json.loads((source / "campaign-plan.json").read_text())
    cases = campaign.validate_plan(plan, source)
    rows = campaign.matrix(plan, cases)
    campaign.validate_matrix(plan, cases, rows)
    launch = json.loads(launch_worksheet.read_text())
    if (source.name != "source" or plan["generation"]["origin"] != "provider-response"
            or launch.get("kind") != "skill-formal-launch-worksheet"
            or launch.get("status") != "not-authorized"
            or launch.get("frozen_manifest_sha256") != runtime.sha256_file(source.parent / "campaign-freeze.json")
            or launch.get("source_plan_sha256") != runtime.sha256_file(source / "campaign-plan.json")
            or launch.get("candidate_limits_unapproved", {}).get("target") != 400
            or launch.get("candidate_limits_unapproved", {}).get("judge") != 200
            or len(cases) != 100 or len(rows) != 400):
        raise ValueError("reviewed real 400-row launch worksheet required")
    output.mkdir()
    worker_root = output / "workers"
    worker_root.mkdir()
    workers = []
    for index, case in enumerate(sorted(cases, key=lambda row: row["case_id"])):
        worker_dir = worker_root / f"case-{index:03d}"
        run_id = f"reading-formal-{nonce}-{index:03d}"
        receipt = prepare_worker(plan, source, case["case_id"], worker_dir, run_id)
        workers.append({"index": index, "case_id": case["case_id"],
            "run_id": run_id, "directory": str(worker_dir.relative_to(output)),
            "plan_sha256": receipt["plan_sha256"], "target_rows": 4,
            "evaluation_keys": [row["evaluation_key"] for row in rows
                                if row["case_id"] == case["case_id"]]})
    if (len(workers) != 100 or len({key for worker in workers
                                     for key in worker["evaluation_keys"]}) != 400):
        raise ValueError("formal worker rows are not a 100 x 4 partition")
    candidate = launch["candidate_limits_unapproved"]
    master = {"kind": "skill-formal-worker-plan", "status": "not-authorized",
        "campaign_id": plan["campaign_id"], "run_id": "reading-formal-" + nonce,
        "source_origin": "provider-response", "target_context": "global-general",
        "source_root": str(source.resolve()),
        "source_plan_sha256": runtime.sha256_file(source / "campaign-plan.json"),
        "frozen_manifest_sha256": runtime.sha256_file(source.parent / "campaign-freeze.json"),
        "frozen_review_count": frozen["semantic_review_count"],
        "launch_worksheet_file": str(launch_worksheet.resolve()),
        "launch_worksheet_sha256": runtime.sha256_file(launch_worksheet),
        "candidate_limits_unapproved": candidate,
        "worker_limits": WORKER_LIMITS,
        "worker_count": 100, "target_rows": 400, "judge_candidate_rows": 200,
        "workers": workers,
        "runner_code_sha256": runtime.sha256_file(Path(__file__)),
        "formal_runner_code_sha256": runtime.sha256_file(
            Path(__file__).with_name("formal_worker_runner.py")),
        "formal_start_authorized": False, "actual_calls": {"target": 0,
            "management": 0, "recovery": 0, "cleanup": 0,
            "generation": 0, "judge": 0}}
    runtime.write_json(output / "formal-worker-plan.json", master)
    runtime.write_json(output / "formal-worker-authorization.json", {
        "status": "not-authorized",
        "plan_sha256": runtime.sha256_file(output / "formal-worker-plan.json")})
    return {"output": str(output), "worker_count": len(workers),
            "target_rows": 400, "judge_candidate_rows": 200,
            "formal_ready": False, "real_target_calls": 0,
            "plan_sha256": runtime.sha256_file(output / "formal-worker-plan.json")}


def verify(output: Path) -> dict[str, Any]:
    plan_path = output / "formal-worker-plan.json"
    master = json.loads(plan_path.read_text())
    authorization = json.loads((output / "formal-worker-authorization.json").read_text())
    source = Path(master["source_root"])
    frozen = campaign.verify_frozen(source.parent)
    source_plan = json.loads((source / "campaign-plan.json").read_text())
    cases = campaign.validate_plan(source_plan, source)
    rows = campaign.matrix(source_plan, cases)
    launch_path = Path(master["launch_worksheet_file"])
    if (master.get("kind") != "skill-formal-worker-plan"
            or master.get("status") != "not-authorized"
            or master.get("formal_start_authorized") is not False
            or master.get("worker_count") != 100 or master.get("target_rows") != 400
            or master.get("judge_candidate_rows") != 200
            or master.get("source_plan_sha256") != runtime.sha256_file(source / "campaign-plan.json")
            or master.get("frozen_manifest_sha256") != runtime.sha256_file(source.parent / "campaign-freeze.json")
            or master.get("frozen_review_count") != frozen["semantic_review_count"]
            or master.get("launch_worksheet_sha256") != runtime.sha256_file(launch_path)
            or master.get("runner_code_sha256") != runtime.sha256_file(Path(__file__))
            or master.get("formal_runner_code_sha256") != runtime.sha256_file(
                Path(__file__).with_name("formal_worker_runner.py"))
            or master.get("worker_limits") != WORKER_LIMITS
            or authorization != {"status": "not-authorized",
                                 "plan_sha256": runtime.sha256_file(plan_path)}):
        raise ValueError("formal worker plan source or authorization drift")
    expected = {case["case_id"]: [row["evaluation_key"] for row in rows
                                  if row["case_id"] == case["case_id"]]
                for case in cases}
    seen = set()
    for worker in master["workers"]:
        directory = output / worker["directory"]
        stage = json.loads((directory / "d-smoke-plan.json").read_text())
        auth = json.loads((directory / "d-smoke-authorization.json").read_text())
        if (worker["case_id"] in seen or worker["evaluation_keys"] != expected.get(worker["case_id"])
                or worker["plan_sha256"] != runtime.sha256_file(directory / "d-smoke-plan.json")
                or stage["source_plan_file_sha256"] != master["source_plan_sha256"]
                or stage["frozen_manifest_sha256"] != master["frozen_manifest_sha256"]
                or stage["limits"] != WORKER_LIMITS or stage["run_id"] != worker["run_id"]
                or stage.get("min_skill_age_seconds") != MIN_SKILL_AGE_SECONDS
                or stage.get("code_hashes") != {name: runtime.sha256_file(WORKER_CODE_ROOT / name)
                                                for name in WORKER_CODE_FILES}
                or stage.get("guard_sha256") != runtime.sha256_file(runtime.GUARD_PATH)
                or stage.get("policy_sha256") != runtime.sha256_file(directory / "approval-policy.json")
                or auth != {"status": "not-authorized",
                            "plan_sha256": worker["plan_sha256"]}):
            raise ValueError("formal worker source, row partition or zero-call state drift")
        seen.add(worker["case_id"])
    if len(seen) != 100 or len(master["workers"]) != 100:
        raise ValueError("100 independent four-row workers required")
    return {"verified": True, "worker_count": 100, "target_rows": 400,
            "formal_start_authorized": False}
