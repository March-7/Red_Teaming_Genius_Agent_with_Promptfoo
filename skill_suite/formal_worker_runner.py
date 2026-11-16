"""Future formal target collector using 100 source-bound four-row workers.

Preparation and dry-run make no network calls. Live execution requires a
separate human authorization for the entire 400-row master plan and refuses
retained Skill name collisions or pending upstream ownership.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import time
from typing import Any

from sweep import runtime
from .d_smoke_plan import authorize as authorize_worker, LIMITS as WORKER_LIMITS
from .d_provisioner import DProvisioner
from .d_target import submit_one
from .d_observer import observe
from .formal_launch_plan import _retained_collisions
from .formal_shards import verify as verify_prepared


ORDER = (("default", "normal"), ("default", "attack"),
         ("deepseek-v4.1-flash", "normal"), ("deepseek-v4.1-flash", "attack"))


def require_local_credential(root: Path) -> None:
    """Catch absent local auth before consuming one zero-retry worker slot."""
    from dotenv import load_dotenv
    from shim.genius_service import ShimConfig
    load_dotenv(root / ".env", override=True)
    config = ShimConfig.from_env()
    if not config.upstream_base_url or not config.upstream_authorization:
        raise ValueError("Genius credential/base URL unavailable before formal worker start")


def dry_run(master_dir: Path) -> dict[str, Any]:
    prepared = verify_prepared(master_dir)
    master = json.loads((master_dir / "formal-worker-plan.json").read_text())
    distributions = {f"{profile}/{variant}": 0 for profile, variant in ORDER}
    for worker in master["workers"]:
        stage = json.loads((master_dir / worker["directory"] / "d-smoke-plan.json").read_text())
        if [(row["model_profile"], row["variant"]) for row in stage["rows"]] != list(ORDER):
            raise ValueError("four-row worker order drift")
        for profile, variant in ORDER:
            distributions[f"{profile}/{variant}"] += 1
    if set(distributions.values()) != {100}:
        raise ValueError("formal worker distribution is not 100 per model/variant")
    return {**prepared, "model_variant_rows": distributions,
            "actual_calls": master["actual_calls"], "network_calls": 0}


def _started(master_dir: Path, root: Path) -> dict[str, Any]:
    master_path = master_dir / "formal-worker-plan.json"
    master = json.loads(master_path.read_text())
    auth = json.loads((master_dir / "formal-worker-authorization.json").read_text())
    source = Path(master["source_root"])
    launch_path = Path(master["launch_worksheet_file"])
    if (master.get("kind") != "skill-formal-worker-plan"
            or master.get("source_origin") != "provider-response"
            or master.get("target_context") != "global-general"
            or master.get("runner_code_sha256") != runtime.sha256_file(
                Path(__file__).with_name("formal_shards.py"))
            or master.get("formal_runner_code_sha256") != runtime.sha256_file(Path(__file__))
            or master.get("source_plan_sha256") != runtime.sha256_file(source / "campaign-plan.json")
            or master.get("frozen_manifest_sha256") != runtime.sha256_file(source.parent / "campaign-freeze.json")
            or master.get("launch_worksheet_sha256") != runtime.sha256_file(launch_path)
            or master.get("worker_limits") != WORKER_LIMITS
            or auth.get("actor") != "human-user"
            or auth.get("decision") != "start-formal-target-collection"
            or auth.get("run_id") != master.get("run_id")
            or auth.get("plan_sha256") != runtime.sha256_file(master_path)
            or auth.get("candidate_limits") != master.get("candidate_limits_unapproved")
            or not auth.get("message_ref") or not auth.get("confirmed_at")
            or runtime.read_ownership(root)):
        raise ValueError("formal source, code, budget, authorization or ownership gate failed")
    from .formal_bundle import verify_started
    verify_started(root, Path(auth["bundle_file"]).parent, cleanup_required=True)
    from . import campaign
    campaign.verify_frozen(source.parent)
    plan = json.loads((source / "campaign-plan.json").read_text())
    rows = campaign.matrix(plan, campaign.validate_plan(plan, source))
    worker_run_ids = {worker["run_id"] for worker in master["workers"]}
    collisions = [item for item in _retained_collisions(
        root, {row["locators"]["resource_name"] for row in rows})
        if not (item["owner_run_id"] in worker_run_ids
                and (root / item["registry"]).resolve().is_relative_to(master_dir.resolve()))]
    if collisions:
        raise ValueError("retained private Skill names must be released before formal target collection")
    return master


def _totals(master_dir: Path, master: dict[str, Any]) -> dict[str, int]:
    kinds = ("target", "management", "recovery", "cleanup", "generation", "judge")
    totals = dict.fromkeys(kinds, 0)
    for worker in master["workers"]:
        ledger_path = master_dir / worker["directory"] / "call-ledger.json"
        if ledger_path.exists():
            counts = json.loads(ledger_path.read_text())["counts"]
            for kind in kinds:
                totals[kind] += counts[kind]
    return totals


def execute_one(root: Path, master_dir: Path, index: int) -> dict[str, Any]:
    """Future formal start: collect one fixed case, stop on the first error."""
    master = _started(master_dir, root)
    if type(index) is not int or index < 0 or index >= 100:
        raise ValueError("one of the 100 fixed worker indices required")
    worker = master["workers"][index]
    run = master_dir / worker["directory"]
    stage_path = run / "d-smoke-plan.json"
    if worker["plan_sha256"] != runtime.sha256_file(stage_path):
        raise ValueError("formal worker stage plan drift")
    if (run / "call-ledger.json").exists() or (run / "worker-result.json").exists():
        raise ValueError("zero retry: formal worker already started")
    # Enforce the global candidate cap before a worker can consume its own cap.
    totals = _totals(master_dir, master)
    caps = master["candidate_limits_unapproved"]
    for kind, maximum in (("target", 4), ("management", WORKER_LIMITS["management"]),
                          ("recovery", WORKER_LIMITS["recovery"]), ("cleanup", 4)):
        if totals[kind] + maximum > caps[kind]:
            raise ValueError("formal master " + kind + " budget reserve exhausted")
    for prior in master["workers"][:index]:
        result_path = master_dir / prior["directory"] / "worker-result.json"
        if not result_path.exists() or json.loads(result_path.read_text()).get("status") != "collected-4-of-4":
            raise ValueError("formal workers must be collected in frozen order")
    if any((master_dir / future["directory"] / "call-ledger.json").exists()
           for future in master["workers"][index + 1:]):
        raise ValueError("future formal worker submitted out of order")
    auth = json.loads((master_dir / "formal-worker-authorization.json").read_text())
    source = Path(master["source_root"])
    result_path = run / "worker-result.json"
    result = None
    try:
        with runtime.sweep_lock(root) as lease:
            require_local_credential(root)
            authorize_worker(run, source, "formal-master:" + auth["plan_sha256"] + ":" + auth["message_ref"])
            stage = json.loads(stage_path.read_text())
            result = {"kind": "skill-formal-worker-result", "status": "started",
                      "master_plan_sha256": auth["plan_sha256"], "case_id": worker["case_id"],
                      "evaluation_keys": worker["evaluation_keys"], "rows": []}
            runtime.write_json(result_path, result)
            provisioner = DProvisioner(root, run, source, lease)
            try:
                for profile in ("default", "deepseek-v4.1-flash"):
                    pair = [row for row in stage["rows"] if row["model_profile"] == profile]
                    if [(row["model_profile"], row["variant"]) for row in pair] != list(
                            ORDER[:2] if profile == "default" else ORDER[2:]):
                        raise ValueError("formal worker model pair order drift")
                    for row in pair:
                        provisioner.provision_one(row["evaluation_key"])
                    created_at = []
                    for row in pair:
                        binding = json.loads((run / ("binding-" + row["evaluation_key"] + ".json")).read_text())
                        receipt = json.loads((run / binding["receipts"]["create_skill"]["file"]).read_text())
                        created_at.append(datetime.fromisoformat(receipt["observed_at"].replace("Z", "+00:00")))
                    wait_s = stage["min_skill_age_seconds"] - min(
                        (datetime.now(timezone.utc) - created).total_seconds() for created in created_at)
                    if wait_s > 0:
                        time.sleep(wait_s + 0.1)
                    for row in pair:
                        binding_path = run / ("binding-" + row["evaluation_key"] + ".json")
                        target = submit_one(provisioner, binding_path)
                        observed = observe(provisioner, binding_path, target["target_result_ref"])
                        result["rows"].append({"evaluation_key": row["evaluation_key"],
                            "model_profile": profile, "variant": row["variant"],
                            "observation_sha256": runtime.sha256_file(
                                run / ("d-observation-" + row["evaluation_key"] + ".json")),
                            "independent_effect_observed": observed["independent_effect_observed"]})
                result["status"] = "collected-4-of-4"
                result["counts"] = dict(provisioner.ledger.state["counts"])
                if result["counts"]["cleanup"] > 4:
                    raise ValueError("formal worker cleanup exceeded one artifact per row")
            finally:
                provisioner.close()
    except Exception as exc:
        if result is not None:
            result["status"] = "stopped"
            result["error_type"] = type(exc).__name__
            runtime.write_json(result_path, result)
        raise
    runtime.write_json(result_path, result)
    return {"case_id": worker["case_id"], "status": result["status"],
            "counts": result["counts"]}
