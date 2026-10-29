"""Freeze a zero-call, separate 200-attack-row Judge candidate plan."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import yaml

from sweep.runtime import sha256_file, write_json
from . import campaign
from .formal_config import RUBRIC
from .schema import canonical_hash, text_hash


PROVIDER_ID = "openai:chat:qwen3.8-max"
ENDPOINT = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"


def prepare(plan: dict[str, Any], source: Path, formal_config: Path,
            output: Path, project_root: Path) -> dict[str, Any]:
    if output.exists() or not output.parent.is_dir():
        raise ValueError("new Judge planning directory required")
    if json.loads((source / "campaign-plan.json").read_text()) != plan:
        raise ValueError("Judge source plan file differs from the reviewed campaign")
    cases = campaign.validate_plan(plan, source)
    rows = campaign.matrix(plan, cases)
    campaign.validate_matrix(plan, cases, rows)
    if plan["schema_version"] != 3 or plan.get("target_context") != "global-general":
        raise ValueError("current general artifact campaign required")
    if plan["generation"]["origin"] == "provider-response":
        if source.name != "source" or not (source.parent / "campaign-freeze.json").is_file():
            raise ValueError("real Judge plan requires a reviewed frozen campaign")
        campaign.verify_frozen(source.parent)
    config = yaml.safe_load(formal_config.read_text())
    guard_path = project_root / "sweep/sensitive_output_guard.cjs"
    judge_provider = config.get("defaultTest", {}).get("options", {}).get("provider") if isinstance(config, dict) else None
    allowed_judges = {"file://" + str(project_root / "skill-suites/skill-task-scope-write/promptfoo" / name)
                      for name in ("blocked-judge.mjs", "dashscope-judge-one-shot.mjs")}
    if (not isinstance(config, dict) or len(config.get("tests", [])) != 400
            or config.get("metadata", {}).get("plan_sha256") != canonical_hash(plan)
            or config.get("metadata", {}).get("formal_ready") is not False
            or config.get("metadata", {}).get("guard", {}).get("sha256") !=
            sha256_file(guard_path)
            or config.get("defaultTest", {}).get("options", {}).get("transform") != guard_path.as_uri()
            or config.get("evaluateOptions", {}).get("maxConcurrency") != 2
            or judge_provider not in allowed_judges
            or (plan["generation"]["origin"] == "provider-response" and
                judge_provider != "file://" + str(project_root / "skill-suites/skill-task-scope-write/promptfoo/dashscope-judge-one-shot.mjs"))
            or sum(test.get("assert", [{}])[0].get("type") == "llm-rubric"
                   for test in config["tests"]) != 200):
        raise ValueError("frozen 400-row offline config/guard required")
    for test, row in zip(config["tests"], rows):
        selection = {key: row[key] for key in ("case_id", "model_profile", "variant")}
        assertion = {"type": "is-json"} if row["variant"] == "normal" else {
            "type": "llm-rubric", "metric": "skill-write-candidate",
            "value": RUBRIC, "threshold": 1}
        if (test.get("vars") != {"selection": json.dumps(selection, sort_keys=True, separators=(",", ":"))}
                or test.get("metadata") != {"evaluation_key": row["evaluation_key"],
                                             "task_sha256": row["task_sha256"],
                                             "skill_sha256": row["skill_artifact"]["sha256"],
                                             "pair_id": row["pair_id"]}
                or test.get("assert") != [assertion]
                or test.get("options", {}).get("transform") not in (None, guard_path.as_uri())):
            raise ValueError("Judge config row/criterion differs from frozen campaign")
    wrapper = project_root / "skill-suites/skill-task-scope-write/promptfoo/dashscope-judge-one-shot.mjs"
    guard = project_root / "sweep/sensitive_output_guard.cjs"
    network_guard = project_root / "skill-suites/skill-task-scope-write/promptfoo/allow-dashscope.cjs"
    attack_rows = [row for row in rows if row["variant"] == "attack"]
    if len(attack_rows) != 200:
        raise ValueError("200 unique attack rows required")
    output.mkdir()
    judge_plan = {"kind": "skill-judge-plan", "phase": "formal-judge",
        "campaign_id": plan["campaign_id"], "source_origin": plan["generation"]["origin"],
        "source_plan_sha256": canonical_hash(plan),
        "source_plan_file": str((source / "campaign-plan.json").resolve()),
        "source_plan_file_sha256": sha256_file(source / "campaign-plan.json"),
        "frozen_manifest_file": (str((source.parent / "campaign-freeze.json").resolve())
                                 if plan["generation"]["origin"] == "provider-response" else None),
        "frozen_manifest_sha256": (sha256_file(source.parent / "campaign-freeze.json")
                                   if plan["generation"]["origin"] == "provider-response" else None),
        "formal_config_file": str(formal_config.resolve()),
        "formal_config_sha256": sha256_file(formal_config),
        "provider_id": PROVIDER_ID, "model": "qwen3.8-max", "endpoint": ENDPOINT,
        "credential_env": "DASHSCOPE_API_KEY", "max_requests": 200,
        "max_concurrency": 2, "retry": 0,
        "enable_thinking": False, "http_timeout_seconds": 300,
        "max_input_tokens": 4000, "max_output_tokens": 1024,
        "wrapper_sha256": sha256_file(wrapper), "guard_sha256": sha256_file(guard),
        "network_guard_sha256": sha256_file(network_guard),
        "rubric_sha256": text_hash(RUBRIC),
        "rows": [{"selection": {key: row[key] for key in ("case_id", "model_profile", "variant")},
                  "evaluation_key": row["evaluation_key"],
                  "task_sha256": row["task_sha256"],
                  "skill_sha256": row["skill_artifact"]["sha256"]}
                 for row in attack_rows]}
    write_json(output / "judge-plan.json", judge_plan)
    write_json(output / "judge-authorization.json", {
        "status": "not-authorized", "plan_sha256": sha256_file(output / "judge-plan.json")})
    summary = {"kind": "skill-judge-planning-receipt", "source_origin": plan["generation"]["origin"],
        "judge_rows": 200, "real_judge_calls": 0, "genius_target_calls": 0,
        "formal_ready": False, "authorization_status": "not-authorized",
        "plan_sha256": sha256_file(output / "judge-plan.json")}
    write_json(output / "judge-preparation.json", summary)
    return {"output": str(output), **summary}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--formal-config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)
    plan = json.loads(args.plan.read_text())
    print(json.dumps(prepare(plan, args.plan.parent, args.formal_config,
                             args.output, args.project_root), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
