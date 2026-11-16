"""Render an inert Promptfoo Judge config for future sealed target replay."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from sweep import runtime


def prepare(project_root: Path, offline_config: Path, output: Path) -> dict[str, Any]:
    if output.exists() or not output.parent.is_dir():
        raise ValueError("new formal replay config path required")
    config = yaml.safe_load(offline_config.read_text())
    if (not isinstance(config, dict) or len(config.get("tests", [])) != 400
            or config.get("metadata", {}).get("formal_ready") is not False
            or config.get("metadata", {}).get("source_origin") != "provider-response"
            or config.get("metadata", {}).get("expected_target_calls") != 400
            or config.get("defaultTest", {}).get("options", {}).get("transform") !=
                (project_root / "sweep/sensitive_output_guard.cjs").as_uri()
            or config["metadata"].get("guard", {}).get("sha256") !=
                runtime.sha256_file(project_root / "sweep/sensitive_output_guard.cjs")):
        raise ValueError("guarded real-source 400-row offline config required")
    target = project_root / "skill_suite/formal_replay_provider.py"
    if not target.is_file():
        raise ValueError("sealed replay target provider missing")
    config["description"] = "Formal Skill sealed target replay and candidate Judge preparation"
    config["targets"] = [{"id": "file://" + str(target) + ":call_api",
                          "label": "sealed-live-target-replay"}]
    config["metadata"].update(kind="skill-formal-replay-judge-preview",
                              formal_ready=False, target_provider_status="sealed-results-only",
                              actual_calls={"target": 0, "judge": 0})
    output.write_text(yaml.safe_dump(config, allow_unicode=True, sort_keys=False))
    return {"config": str(output), "test_rows": len(config["tests"]),
            "attack_judge_assertion_rows": sum(test["assert"][0]["type"] == "llm-rubric"
                                               for test in config["tests"]),
            "real_target_calls": 0, "real_judge_calls": 0, "formal_ready": False}
