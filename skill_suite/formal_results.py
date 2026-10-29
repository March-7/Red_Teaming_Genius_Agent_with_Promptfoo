"""Seal 400 live target receipts for later Promptfoo Judge replay."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sweep import runtime
from .d_gate import audit as audit_worker
from .formal_worker_runner import _totals
from .schema import text_hash


def seal(root: Path, master_dir: Path) -> dict[str, Any]:
    output = master_dir / "formal-target-evidence.json"
    if output.exists():
        raise ValueError("formal target evidence already sealed")
    master_path = master_dir / "formal-worker-plan.json"
    master = json.loads(master_path.read_text())
    auth_path = master_dir / "formal-worker-authorization.json"
    auth = json.loads(auth_path.read_text())
    if (master.get("kind") != "skill-formal-worker-plan"
            or auth.get("actor") != "human-user"
            or auth.get("decision") != "start-formal-target-collection"
            or auth.get("plan_sha256") != runtime.sha256_file(master_path)
            or runtime.read_ownership(root)):
        raise ValueError("authorized, complete and idle formal target collection required")
    from .formal_bundle import verify_started
    verify_started(root, Path(auth["bundle_file"]).parent, cleanup_required=True)
    records = []
    for worker in master["workers"]:
        run = master_dir / worker["directory"]
        result_path = run / "worker-result.json"
        if not result_path.exists() or json.loads(result_path.read_text()).get("status") != "collected-4-of-4":
            raise ValueError("one of the 100 formal workers is incomplete")
        gate = audit_worker(run, root)
        if (gate.get("validated_rows") != 4 or gate.get("resources_verified") is not True
                or gate.get("pending_ownership_count") != 0
                or gate.get("ledger_stopped")):
            raise ValueError("formal worker lacks four valid source/oracle receipts")
        for row in gate["rows"]:
            if row["status"] != "evidence-valid-pending-review":
                raise ValueError("formal row evidence invalid")
            key = row["evaluation_key"]
            observation_path = run / ("d-observation-" + key + ".json")
            target_path = run / ("d-target-result-" + key + ".json")
            observation = json.loads(observation_path.read_text())
            records.append({"case_id": row["case_id"], "evaluation_key": key,
                "model_profile": row["model_profile"], "variant": row["variant"],
                "worker_directory": worker["directory"],
                "observation_sha256": runtime.sha256_file(observation_path),
                "target_result_sha256": runtime.sha256_file(target_path),
                "guarded_output_sha256": text_hash(observation["guarded_output"]),
                "json_output_valid": row["json_output_valid"],
                "independent_effect_observed": row["independent_effect_observed"],
                "review_status": "pending"})
    if (len(records) != 400 or len({item["evaluation_key"] for item in records}) != 400
            or sum(item["variant"] == "attack" for item in records) != 200):
        raise ValueError("formal target evidence must cover exactly 400 unique rows")
    counts = _totals(master_dir, master)
    caps = master["candidate_limits_unapproved"]
    if (counts["target"] != 400 or counts["judge"] != 0
            or counts["generation"] != 0
            or any(counts[kind] > caps[kind] for kind in ("target", "management", "recovery", "cleanup"))):
        raise ValueError("formal target accounting exceeds the frozen launch plan")
    manifest = {"kind": "skill-formal-target-evidence", "status": "target-collected-needs-review",
        "master_plan_sha256": runtime.sha256_file(master_path),
        "master_authorization_sha256": runtime.sha256_file(auth_path),
        "frozen_manifest_sha256": master["frozen_manifest_sha256"],
        "source_plan_sha256": master["source_plan_sha256"],
        "target_rows": 400, "attack_rows": 200, "normal_rows": 200,
        "counts": counts, "rows": records,
        "formal_asr_computed": False, "judge_calls": 0,
        "sealed_at": runtime.utc_now()}
    runtime.write_json(output, manifest)
    return {"output": str(output), "target_rows": 400, "counts": counts,
            "judge_calls": 0, "formal_asr_computed": False}


def replay_row(master_dir: Path, evidence_path: Path, selection: dict[str, str]) -> dict[str, Any]:
    """Read only one sealed result; no target or management request can occur."""
    master = json.loads((master_dir / "formal-worker-plan.json").read_text())
    evidence = json.loads(evidence_path.read_text())
    if (evidence.get("kind") != "skill-formal-target-evidence"
            or evidence.get("status") != "target-collected-needs-review"
            or evidence.get("master_plan_sha256") != runtime.sha256_file(master_dir / "formal-worker-plan.json")
            or evidence.get("master_authorization_sha256") != runtime.sha256_file(
                master_dir / "formal-worker-authorization.json")
            or evidence.get("frozen_manifest_sha256") != master["frozen_manifest_sha256"]
            or evidence.get("target_rows") != 400
            or len(evidence.get("rows", [])) != 400
            or len({row.get("evaluation_key") for row in evidence.get("rows", [])}) != 400
            or set(selection) != {"case_id", "model_profile", "variant"}):
        raise ValueError("sealed formal target evidence or opaque selection drift")
    matches = [row for row in evidence["rows"] if all(row[key] == selection[key] for key in selection)]
    if len(matches) != 1:
        raise ValueError("unique sealed formal result required")
    row = matches[0]
    run = master_dir / row["worker_directory"]
    observation_path = run / ("d-observation-" + row["evaluation_key"] + ".json")
    target_path = run / ("d-target-result-" + row["evaluation_key"] + ".json")
    if (runtime.sha256_file(observation_path) != row["observation_sha256"]
            or runtime.sha256_file(target_path) != row["target_result_sha256"]):
        raise ValueError("formal target/observation evidence hash drift")
    observation = json.loads(observation_path.read_text())
    output = observation.get("guarded_output")
    if not isinstance(output, str) or text_hash(output) != row["guarded_output_sha256"]:
        raise ValueError("guarded formal output differs from the sealed receipt")
    return {"output": output, "metadata": {"environment": "live-target-replay",
        "evaluation_key": row["evaluation_key"],
        "evidence_manifest_sha256": runtime.sha256_file(evidence_path),
        "target_calls_this_replay": 0}}
