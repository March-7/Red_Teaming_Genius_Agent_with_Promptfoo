"""Normalize ten audited hosted Promptfoo responses into reviewable Skill assets."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import tempfile
from typing import Any

import yaml

from sweep.models import MATRIX
from sweep.runtime import sha256_file, write_json
from . import campaign
from .generation_pipeline import materialize_assets


def normalize_completed(run: Path, output: Path) -> dict[str, Any]:
    if output.exists() or not output.parent.is_dir():
        raise ValueError("new output directory required")
    stage_path = run / "generation-plan.json"
    stage = json.loads(stage_path.read_text())
    authorization = json.loads((run / "generation-authorization.json").read_text())
    dispatch = json.loads((run / "generation-result.json").read_text())
    ledger = json.loads((run / "generation-ledger.json").read_text())
    if (stage.get("kind") != "skill-generation-plan"
            or authorization.get("actor") != "human-user"
            or authorization.get("plan_sha256") != sha256_file(stage_path)
            or authorization.get("scope_hash") != stage.get("generation_scope_hash")
            or dispatch.get("status") != "generation-complete-needs-review"
            or dispatch.get("plan_sha256") != sha256_file(stage_path)
            or len(dispatch.get("job_results", [])) != 10
            or any(job.get("status") != "completed" for job in dispatch["job_results"])
            or ledger.get("counts", {}).get("generation") != 10
            or ledger["counts"].get("target") != 0 or ledger["counts"].get("judge") != 0):
        raise ValueError("ten authorized hosted generation attempts required")
    packages = []
    for job in stage["jobs"]:
        job_id = job["job_id"]
        attempt_path = run / ("attempt-" + job_id + ".json")
        attempt = json.loads(attempt_path.read_text())
        raw_path = run / ("raw-response-" + job_id + ".json")
        if (attempt.get("environment") != "live" or attempt.get("status") != "completed"
                or attempt.get("job_id") != job_id
                or attempt.get("raw_response_ref") !=
                {"file": raw_path.name, "sha256": sha256_file(raw_path)}):
            raise ValueError("hosted HTTP attempt/raw response linkage missing")
        raw = json.loads(raw_path.read_text())
        content = raw.get("choices", [{}])[0].get("message", {}).get("content")
        decoded = campaign.raw_prompt_packages(content)
        generated = yaml.safe_load((run / "jobs" / job_id / "generated-live.yaml").read_text())
        tests = generated.get("tests", []) if isinstance(generated, dict) else []
        if (len(decoded) != 1 or len(tests) != 1
                or set(tests[0].get("vars", {})) != {"skill_payload"}
                or tests[0].get("metadata", {}).get("pluginId") != "file://./plugin.yaml"
                or json.loads(tests[0]["vars"]["skill_payload"]) != decoded[0]
                or decoded[0].get("skill_key") != job["expected_skill_key"]
                or decoded[0].get("effect_artifact_name") != job["effect_artifact_name"]):
            raise ValueError("raw hosted response and Promptfoo export differ")
        packages.append(decoded[0])
    if len({package["skill_key"] for package in packages}) != 10:
        raise ValueError("ten distinct hosted Skill packages required")
    with tempfile.TemporaryDirectory(prefix=".real-skill-campaign-", dir=output.parent) as temporary:
        root = Path(temporary)
        for name in ("generation-plan.json", "generation-authorization.json",
                     "generation-result.json", "generation-ledger.json", "provider-config.json"):
            shutil.copyfile(run / name, root / name)
        def ref(path: Path) -> dict[str, str]:
            return {"file": str(path.relative_to(root)), "sha256": sha256_file(path)}
        skills = materialize_assets(root, packages)
        skill_by_key = {skill["skill_key"]: skill for skill in skills}
        calls = []
        for number, job in enumerate(sorted(stage["jobs"], key=lambda row: row["job_id"]), 1):
            job_id = job["job_id"]
            directory = root / "jobs" / job_id
            directory.mkdir(parents=True)
            for name in ("plugin.yaml", "live-config.yaml", "prompt.txt", "generated-live.yaml"):
                shutil.copyfile(run / "jobs" / job_id / name, directory / name)
            for name in ("attempt-" + job_id + ".json", "raw-response-" + job_id + ".json"):
                shutil.copyfile(run / name, root / name)
            request = {"request_id": job_id, "provider_id": stage["provider_id"],
                "model": stage["model"],
                "provider_config_sha256": sha256_file(root / "provider-config.json"),
                "max_output_tokens": stage["max_output_tokens"],
                "prompt_sha256": job["prompt_sha256"],
                "stage_plan_sha256": sha256_file(root / "generation-plan.json"),
                "payload": job["generation_fields"]}
            request_path = root / ("request-" + job_id + ".json")
            write_json(request_path, request)
            response = {"request_id": job_id, "provider_id": stage["provider_id"],
                "model": stage["model"], "status": "completed",
                "raw_response": ref(root / ("raw-response-" + job_id + ".json")),
                "http_attempt_ref": ref(root / ("attempt-" + job_id + ".json")),
                "generated_ref": ref(directory / "generated-live.yaml"),
                "normalized_skills": [campaign.payload_skill(root, skill_by_key[job["expected_skill_key"]])]}
            response_path = root / ("response-" + job_id + ".json")
            write_json(response_path, response)
            calls.append({"attempt": number, "request_id": job_id,
                          "request": ref(request_path), "response": ref(response_path)})
        generation = {"origin": "provider-response", "provider_id": stage["provider_id"],
            "model": stage["model"], "max_requests": stage["max_requests"],
            "max_input_tokens": stage["max_input_tokens"],
            "max_output_tokens": stage["max_output_tokens"],
            "max_concurrency": stage["max_concurrency"], "retry": stage["retry"],
            "submitted_fields": stage["submitted_fields"],
            "provider_config": ref(root / "provider-config.json"), "receipt": None}
        plan = {"schema_version": 3, "kind": "skill-campaign",
            "target_context": "global-general", "campaign_id": stage["campaign_id"],
            "risk_id": "skill-task-scope-write", "risk_contract": stage["risk_contract"],
            "model_matrix": [{"label": label, "model_profile": profile,
                              "reasoning_effort": "high", "thinking": "on"}
                             for label, profile, _ in MATRIX],
            "execution": {"max_concurrency": 2, "retry": 0,
                          "lifecycle": "retain", "expected_target_calls": 400},
            "generation": generation, "skills": skills}
        receipt = {"schema_version": 1, "kind": "skill-generation-receipt",
            "origin": "provider-response", "scope_hash": stage["generation_scope_hash"],
            "confirmation": {key: authorization[key] for key in
                ("actor", "decision", "phase", "scope_hash", "message_ref", "confirmed_at")},
            "calls": calls}
        write_json(root / "generation-receipt.json", receipt)
        plan["generation"]["receipt"] = ref(root / "generation-receipt.json")
        write_json(root / "campaign-plan.json", plan)
        cases = campaign.validate_plan(plan, root)
        rows = campaign.matrix(plan, cases)
        campaign.validate_matrix(plan, cases, rows)
        (root / "formal-matrix-preview.jsonl").write_text(
            "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows))
        write_json(root / "campaign-review-template.json", campaign.review_template(plan, cases))
        write_json(root / "campaign-preview.json", campaign.preview(plan, cases, root))
        inventory = {str(path.relative_to(root)): sha256_file(path)
                     for path in sorted(root.rglob("*")) if path.is_file()}
        write_json(root / "source-manifest.json", {"kind": "skill-provider-response-source",
            "origin": "provider-response", "campaign_id": plan["campaign_id"],
            "generation_call_count": 10, "target_calls": 0, "judge_calls": 0,
            "skill_count": 10, "combination_count": 100, "matrix_rows": 400,
            "semantic_review_count": 0, "formal_ready": False,
            "artifact_hashes": inventory})
        if output.exists():
            raise ValueError("output appeared during normalization")
        root.rename(output)
    return {"output": str(output), "source_origin": "provider-response",
            "skill_count": 10, "combination_count": 100, "matrix_rows": 400,
            "semantic_review_count": 0, "formal_ready": False}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    print(json.dumps(normalize_completed(args.run, args.output), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
