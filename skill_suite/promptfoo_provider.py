"""Python file provider entry point; only the offline fixture mode is enabled."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from skill_suite import campaign
from skill_suite.offline_adapter import OfflineAdapter
from skill_suite.orchestration import execute_fixture, parse_selection


def call_api(prompt: str, _options=None, _context=None):
    if os.environ.get("SKILL_ORCHESTRATION_MODE") != "offline-fixture":
        raise RuntimeError("live Skill provisioner is not verified or enabled")
    source = Path(os.environ["SKILL_OFFLINE_CAMPAIGN_SOURCE"])
    project_root = Path(os.environ["SKILL_OFFLINE_PROJECT_ROOT"])
    output = Path(os.environ["SKILL_OFFLINE_CASE_OUTPUT"])
    selection = parse_selection(prompt)
    plan = json.loads((source / "campaign-plan.json").read_text())
    rows = campaign.matrix(plan, campaign.validate_plan(plan, source))
    matches = [row for row in rows if all(row[key] == selection[key] for key in selection)]
    if len(matches) != 1:
        raise ValueError("unique opaque case required")
    adapter = OfflineAdapter(matches[0]["locators"]["record_id"],
                             mutate=os.environ.get("SKILL_OFFLINE_MUTATE") == "1")
    strategy = os.environ.get("SKILL_OFFLINE_STRATEGY_PLAN")
    result = execute_fixture(project_root, source, output, prompt, adapter,
                             strategy_manifest=Path(strategy) if strategy else None)
    return {"output": result["output"], "metadata": {
        "fixture_evidence": str(output / "fixture-result.json"),
        "environment": "offline-fixture", "formal_ready": False}}
