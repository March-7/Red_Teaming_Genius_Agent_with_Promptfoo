"""Preserve the superseded single-risk formal packet as calibration evidence.

The 100-case/400-row packet is intentionally non-executable. A future
benchmark-driven multi-risk packet must use a distinct schema and launcher.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from sweep import runtime
from .formal_worker_runner import dry_run


CODE_FILES = (
    "skill_suite/formal_bundle.py", "skill_suite/formal_launch_plan.py",
    "skill_suite/formal_shards.py", "skill_suite/formal_worker_runner.py",
    "skill_suite/formal_results.py", "skill_suite/formal_replay_provider.py",
    "skill_suite/formal_replay_config.py", "skill_suite/formal_prestart_cleanup.py",
    "skill_suite/formal_report.py", "skill_suite/formal_progress.py",
    "skill_suite/skill_cleanup_pilot.py",
    "skill-suites/skill-task-scope-write/promptfoo/dashscope-judge-one-shot.mjs",
    "skill-suites/skill-task-scope-write/promptfoo/allow-dashscope.cjs",
)

LEGACY_DISPOSITION = "superseded-for-formal"
LEGACY_STATUS = "calibration-only"


def reject_legacy_start() -> None:
    raise ValueError(
        "legacy single-risk formal bundle is calibration-only and superseded-for-formal"
    )


def _supersession(root: Path) -> tuple[Path, dict[str, Any]]:
    path = root / "skill-suites/skill-task-scope-write/formal-supersession.json"
    manifest = json.loads(path.read_text())
    rows = manifest.get("historical_bundles", [])
    if (manifest.get("kind") != "skill-formal-supersession-manifest"
            or manifest.get("risk_id") != "skill-task-scope-write"
            or manifest.get("evaluation_stage") != "calibration"
            or manifest.get("disposition") != LEGACY_DISPOSITION
            or manifest.get("execution_enabled") is not False
            or set(manifest.get("blocked_operations", [])) != {
                "formal-authorization", "prestart-cleanup", "target-collection", "judge"}
            or not rows
            or len({row.get("run_id") for row in rows}) != len(rows)
            or any(row.get("disposition") != LEGACY_DISPOSITION
                   or len(str(row.get("bundle_sha256", ""))) != 64
                   or len(str(row.get("authorization_sha256", ""))) != 64
                   for row in rows)):
        raise ValueError("legacy formal supersession manifest invalid")
    return path, manifest


def prepare(root: Path, worker_dir: Path, cleanup_dir: Path,
            replay_config: Path, judge_dir: Path, output: Path,
            *, precleanup_snapshot_manifest: Path | None = None) -> dict[str, Any]:
    if output.exists() or not output.parent.is_dir():
        raise ValueError("new formal start bundle directory required")
    supersession_path, _ = _supersession(root)
    preview = dry_run(worker_dir)
    master_path = worker_dir / "formal-worker-plan.json"
    master = json.loads(master_path.read_text())
    cleanup_path = cleanup_dir / "cleanup-plan.json"
    cleanup = json.loads(cleanup_path.read_text())
    judge_path = judge_dir / "judge-plan.json"
    judge = json.loads(judge_path.read_text())
    judge_auth = json.loads((judge_dir / "judge-authorization.json").read_text())
    config = yaml.safe_load(replay_config.read_text())
    if (cleanup.get("kind") != "skill-formal-prestart-cleanup"
            or cleanup.get("status") != "not-authorized"
            or cleanup.get("master_plan_sha256") != runtime.sha256_file(master_path)
            or len(cleanup.get("items", [])) != 6
            or cleanup.get("limits", {}).get("management") != 12
            or cleanup.get("limits", {}).get("cleanup") != 6
            or judge.get("kind") != "skill-judge-plan"
            or judge.get("source_origin") != "provider-response"
            or judge.get("formal_config_sha256") != runtime.sha256_file(replay_config)
            or judge.get("max_requests") != 200
            or judge.get("enable_thinking") is not False
            or judge.get("http_timeout_seconds") != 300
            or judge.get("wrapper_sha256") != runtime.sha256_file(
                root / "skill-suites/skill-task-scope-write/promptfoo/dashscope-judge-one-shot.mjs")
            or judge_auth != {"status": "not-authorized",
                              "plan_sha256": runtime.sha256_file(judge_path)}
            or config.get("metadata", {}).get("formal_ready") is not False
            or config.get("metadata", {}).get("source_origin") != "provider-response"
            or len(config.get("tests", [])) != 400
            or preview["target_rows"] != 400 or preview["network_calls"] != 0
            or runtime.read_ownership(root)):
        raise ValueError("real 400-row source, audited cleanup and unapproved Judge packet required")
    snapshot_ref = None
    if precleanup_snapshot_manifest is not None:
        snapshot = json.loads(precleanup_snapshot_manifest.read_text())
        if (snapshot.get("kind") != "skill-d-precleanup-snapshot"
                or snapshot.get("status") != "captured-before-formal-start"
                or len(snapshot.get("runs", [])) != 2):
            raise ValueError("two preserved D evidence snapshots required")
        from .d_gate import audit as audit_d
        d3 = precleanup_snapshot_manifest.parent / "d-generated-20261003-9ab39271"
        if audit_d(d3, root).get("d_smoke_ready") is not True:
            raise ValueError("preserved D3 evidence does not pass the read-only gate")
        snapshot_ref = {"file": str(precleanup_snapshot_manifest.resolve()),
                        "sha256": runtime.sha256_file(precleanup_snapshot_manifest)}
    limits = dict(master["candidate_limits_unapproved"])
    limits["management"] += cleanup["limits"]["management"]
    limits["cleanup"] += cleanup["limits"]["cleanup"]
    if (limits["target"] != 400 or limits["management"] != 4812
            or limits["recovery"] != 400 or limits["cleanup"] != 406
            or limits["judge"] != 200 or limits["projects"] != 0):
        raise ValueError("formal overall budget arithmetic drift")
    output.mkdir()
    plan = {"kind": "skill-formal-start-bundle", "status": LEGACY_STATUS,
        "formal_disposition": LEGACY_DISPOSITION, "evaluation_stage": "calibration",
        "superseded_by": "benchmark-multi-risk-portfolio", "execution_enabled": False,
        "supersession_manifest_file": str(supersession_path.resolve()),
        "supersession_manifest_sha256": runtime.sha256_file(supersession_path),
        "campaign_id": master["campaign_id"], "target_context": "global-general",
        "frozen_manifest_sha256": master["frozen_manifest_sha256"],
        "frozen_review_count": master["frozen_review_count"],
        "worker_master_file": str(master_path.resolve()),
        "worker_master_sha256": runtime.sha256_file(master_path),
        "cleanup_plan_file": str(cleanup_path.resolve()),
        "cleanup_plan_sha256": runtime.sha256_file(cleanup_path),
        "replay_config_file": str(replay_config.resolve()),
        "replay_config_sha256": runtime.sha256_file(replay_config),
        "judge_plan_file": str(judge_path.resolve()),
        "judge_plan_sha256": runtime.sha256_file(judge_path),
        "guard_sha256": runtime.sha256_file(root / "sweep/sensitive_output_guard.cjs"),
        "precleanup_d_evidence_snapshot": snapshot_ref,
        "code_hashes": {name: runtime.sha256_file(root / name) for name in CODE_FILES},
        "row_distribution": preview["model_variant_rows"],
        "overall_candidate_limits_unapproved": limits,
        "historical_startup_sequence": ["human-formal-start-authorization",
            "six-owned-Skill-GET-DELETE-404", "100x4-live-target-collection",
            "seal-400-target-receipts", "separate-Judge-authorization-and-replay",
            "independent-oracle-and-human-result-review"],
        "formal_target_calls": 0, "judge_calls": 0,
        "formal_start_authorized": False,
        "stop_condition": "legacy packet cannot be authorized; build a new benchmark multi-risk packet"}
    runtime.write_json(output / "formal-start-bundle.json", plan)
    runtime.write_json(output / "formal-start-authorization.json", {
        "status": "not-authorized",
        "bundle_sha256": runtime.sha256_file(output / "formal-start-bundle.json")})
    return {"output": str(output), "status": plan["status"],
            "bundle_sha256": runtime.sha256_file(output / "formal-start-bundle.json"),
            "target_rows": 400, "judge_candidate_rows": 200,
            "formal_start_authorized": False,
            "overall_candidate_limits_unapproved": limits}


def verify(root: Path, output: Path) -> dict[str, Any]:
    bundle_path = output / "formal-start-bundle.json"
    bundle = json.loads(bundle_path.read_text())
    authorization = json.loads((output / "formal-start-authorization.json").read_text())
    worker_path = Path(bundle["worker_master_file"])
    cleanup_path = Path(bundle["cleanup_plan_file"])
    config_path = Path(bundle["replay_config_file"])
    judge_path = Path(bundle["judge_plan_file"])
    supersession_path, _ = _supersession(root)
    master = json.loads(worker_path.read_text())
    cleanup = json.loads(cleanup_path.read_text())
    judge = json.loads(judge_path.read_text())
    config = yaml.safe_load(config_path.read_text())
    if (bundle.get("kind") != "skill-formal-start-bundle"
            or bundle.get("status") != LEGACY_STATUS
            or bundle.get("formal_disposition") != LEGACY_DISPOSITION
            or bundle.get("evaluation_stage") != "calibration"
            or bundle.get("superseded_by") != "benchmark-multi-risk-portfolio"
            or bundle.get("execution_enabled") is not False
            or bundle.get("supersession_manifest_file") != str(supersession_path.resolve())
            or bundle.get("supersession_manifest_sha256") != runtime.sha256_file(
                supersession_path)
            or bundle.get("formal_start_authorized") is not False
            or bundle.get("worker_master_sha256") != runtime.sha256_file(worker_path)
            or bundle.get("cleanup_plan_sha256") != runtime.sha256_file(cleanup_path)
            or bundle.get("replay_config_sha256") != runtime.sha256_file(config_path)
            or bundle.get("judge_plan_sha256") != runtime.sha256_file(judge_path)
            or bundle.get("guard_sha256") != runtime.sha256_file(
                root / "sweep/sensitive_output_guard.cjs")
            or (bundle.get("precleanup_d_evidence_snapshot") is not None
                and bundle["precleanup_d_evidence_snapshot"]["sha256"] != runtime.sha256_file(
                    Path(bundle["precleanup_d_evidence_snapshot"]["file"])))
            or bundle.get("code_hashes") != {name: runtime.sha256_file(root / name)
                                             for name in CODE_FILES}
            or authorization != {"status": "not-authorized",
                                 "bundle_sha256": runtime.sha256_file(bundle_path)}
            or master.get("frozen_manifest_sha256") != bundle.get("frozen_manifest_sha256")
            or master.get("frozen_review_count") != 100
            or cleanup.get("master_plan_sha256") != runtime.sha256_file(worker_path)
            or len(cleanup.get("items", [])) != 6
            or judge.get("max_requests") != 200
            or judge.get("enable_thinking") is not False
            or judge.get("http_timeout_seconds") != 300
            or judge.get("wrapper_sha256") != runtime.sha256_file(
                root / "skill-suites/skill-task-scope-write/promptfoo/dashscope-judge-one-shot.mjs")
            or config.get("metadata", {}).get("formal_ready") is not False
            or len(config.get("tests", [])) != 400
            or runtime.read_ownership(root)):
        raise ValueError("formal start bundle hash, source, code or zero-call state drift")
    preview = dry_run(worker_path.parent)
    return {"verified": True, "status": bundle["status"],
            "target_rows": preview["target_rows"],
            "judge_candidate_rows": 200,
            "formal_start_authorized": False,
            "bundle_sha256": runtime.sha256_file(bundle_path)}


def authorize(root: Path, output: Path, message_ref: str) -> dict[str, Any]:
    """Reject authorization of every legacy single-risk packet."""
    verify(root, output)
    reject_legacy_start()


def verify_started(root: Path, output: Path, *, cleanup_required: bool) -> dict[str, Any]:
    # Historical authorization files may exist outside version control. None
    # can revive this packet or reach cleanup/target network code.
    reject_legacy_start()
    raise AssertionError("unreachable")
    bundle_path = output / "formal-start-bundle.json"
    bundle = json.loads(bundle_path.read_text())
    auth = json.loads((output / "formal-start-authorization.json").read_text())
    master_path = Path(bundle["worker_master_file"])
    master = json.loads(master_path.read_text())
    worker_auth = json.loads((master_path.parent / "formal-worker-authorization.json").read_text())
    cleanup_path = Path(bundle["cleanup_plan_file"])
    cleanup = json.loads(cleanup_path.read_text())
    if (bundle.get("kind") != "skill-formal-start-bundle"
            or bundle.get("worker_master_sha256") != runtime.sha256_file(master_path)
            or bundle.get("cleanup_plan_sha256") != runtime.sha256_file(cleanup_path)
            or bundle.get("replay_config_sha256") != runtime.sha256_file(
                Path(bundle["replay_config_file"]))
            or bundle.get("judge_plan_sha256") != runtime.sha256_file(
                Path(bundle["judge_plan_file"]))
            or bundle.get("guard_sha256") != runtime.sha256_file(
                root / "sweep/sensitive_output_guard.cjs")
            or (bundle.get("precleanup_d_evidence_snapshot") is not None
                and bundle["precleanup_d_evidence_snapshot"]["sha256"] != runtime.sha256_file(
                    Path(bundle["precleanup_d_evidence_snapshot"]["file"])))
            or bundle.get("code_hashes") != {name: runtime.sha256_file(root / name)
                                             for name in CODE_FILES}
            or auth.get("actor") != "human-user"
            or auth.get("decision") != "start-formal-target-collection"
            or auth.get("bundle_sha256") != runtime.sha256_file(bundle_path)
            or auth.get("master_plan_sha256") != runtime.sha256_file(master_path)
            or auth.get("run_id") != master["run_id"]
            or auth.get("overall_limits") != bundle["overall_candidate_limits_unapproved"]
            or not auth.get("message_ref") or not auth.get("confirmed_at")
            or worker_auth.get("bundle_file") != str(bundle_path.resolve())
            or worker_auth.get("bundle_sha256") != auth["bundle_sha256"]
            or worker_auth.get("plan_sha256") != auth["master_plan_sha256"]
            or worker_auth.get("message_ref") != auth["message_ref"]
            or cleanup.get("master_plan_sha256") != auth["master_plan_sha256"]):
        raise ValueError("formal bundle or derived worker start authorization drift")
    if cleanup_required:
        result_path = cleanup_path.parent / "cleanup-result.json"
        if not result_path.exists():
            raise ValueError("six retained private Skills must be cleared at formal start")
        result = json.loads(result_path.read_text())
        if (result.get("kind") != "skill-formal-prestart-cleanup-result"
                or result.get("status") != "verified-cleaned"
                or result.get("plan_sha256") != runtime.sha256_file(cleanup_path)
                or result.get("master_plan_sha256") != runtime.sha256_file(master_path)
                or len(result.get("items", [])) != 6
                or result.get("actual_calls", {}).get("management") != 12
                or result["actual_calls"].get("cleanup") != 6):
            raise ValueError("formal startup cleanup receipt incomplete")
    return {"started": True, "bundle_sha256": auth["bundle_sha256"],
            "cleanup_verified": cleanup_required}
