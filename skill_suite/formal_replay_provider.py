"""Promptfoo file provider for sealed live target results; never invokes Genius."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sweep import runtime
from skill_suite.formal_results import replay_row
from skill_suite.orchestration import parse_selection


def call_api(prompt: str, _options=None, _context=None):
    if os.environ.get("SKILL_FORMAL_REPLAY_MODE") != "sealed-live-results":
        raise RuntimeError("sealed formal target replay is not enabled")
    master_dir = Path(os.environ["SKILL_FORMAL_REPLAY_MASTER_DIR"])
    evidence_path = master_dir / "formal-target-evidence.json"
    expected_hash = os.environ.get("SKILL_FORMAL_REPLAY_EVIDENCE_SHA256", "")
    if not expected_hash or runtime.sha256_file(evidence_path) != expected_hash:
        raise ValueError("pinned sealed formal evidence required before Promptfoo grading")
    master_path = master_dir / "formal-worker-plan.json"
    authorization = json.loads((master_dir / "formal-worker-authorization.json").read_text())
    if (authorization.get("actor") != "human-user"
            or authorization.get("decision") != "start-formal-target-collection"
            or authorization.get("plan_sha256") != runtime.sha256_file(master_path)):
        raise ValueError("formal target collection authorization missing")
    from skill_suite.formal_bundle import verify_started
    verify_started(Path(__file__).resolve().parent.parent,
                   Path(authorization["bundle_file"]).parent,
                   cleanup_required=True)
    return replay_row(master_dir, evidence_path, parse_selection(prompt))
