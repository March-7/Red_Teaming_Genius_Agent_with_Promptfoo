"""Repeat DeepSeek workspace shell reachability three times.

This is not a promptfoo generation/eval run.  It reuses one retained neutral
Project/file fixture from Stage A and sends three independent workspace
requests to DeepSeek-V4.1-Flash.  Each request uses a new session.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import datetime as dt
import fcntl
import json
from pathlib import Path
from typing import Any, Iterator

from dotenv import load_dotenv
from dataclasses import replace

from shim.genius_service import GeniusService, ShimConfig
from sweep.shell_injection_probe import (
    GROUP_ID,
    PLUGIN_ID,
    USER_QUERY_ANSWER,
    _analyze,
    _prompt,
)


TARGET_LABEL = "DeepSeek-V4.1-Flash / high"
MODEL_PROFILE = "deepseek-v4.1-flash"


def _stamp() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


@contextmanager
def _sweep_lock(root: Path) -> Iterator[None]:
    path = root / "logs" / ".sweep.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError(
                "another plugin sweep is active; wait for its completion"
            ) from exc
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def _request(
    run_id: str,
    fixture: dict[str, Any],
    repeat_index: int,
) -> dict[str, Any]:
    return {
        "model": "genius-agent",
        "messages": [
            {"role": "user", "content": _prompt(fixture, "workspace")}
        ],
        "metadata": {
            "session_id": f"shell-repeat:{run_id}:{repeat_index}",
            "project_id": fixture["project_id"],
            "campaign": {
                "run_id": run_id,
                "group_id": GROUP_ID,
                "plugin_id": PLUGIN_ID,
                "probe_kind": "shell-injection-repeat-deepseek-workspace",
                "target_label": TARGET_LABEL,
                "model_profile": MODEL_PROFILE,
                "path": "workspace",
                "repeat_index": repeat_index,
            },
        },
        "model_profile": MODEL_PROFILE,
        "reasoning_effort": "high",
        "thinking": "on",
    }


def run_probe(root: Path, fixture_registry: Path) -> dict[str, Any]:
    run_id = f"{_stamp()}-shell-repeat-deepseek-workspace"
    run_dir = root / "sweeps" / GROUP_ID / PLUGIN_ID / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    load_dotenv(root / ".env", override=False)

    fixtures = _read_jsonl(fixture_registry)
    fixture = next(
        (
            row
            for row in fixtures
            if row.get("target_number") == 2
            and row.get("setup_status") == "ready"
        ),
        None,
    )
    if fixture is None:
        raise ValueError("fixture registry has no ready DeepSeek fixture")

    manifest: dict[str, Any] = {
        "schema_version": 1,
        "run_id": run_id,
        "group_id": GROUP_ID,
        "plugin_id": PLUGIN_ID,
        "mode": "shell-injection-repeat-deepseek-workspace",
        "generation_calls": 0,
        "judge_calls": 0,
        "formal_redteam_eval": False,
        "retry_attempts": 0,
        "logical_target_calls": 0,
        "upstream_target_calls": 0,
        "target_call_limit": 3,
        "human_input_max_rounds": 1,
        "human_input_auto_answer": USER_QUERY_ANSWER,
        "reused_fixture_registry": str(fixture_registry),
        "status": "target-running",
    }
    _write_json(run_dir / "probe-manifest.json", manifest)

    config = replace(
        ShimConfig.from_env(),
        upstream_retry_attempts=0,
        trace_jsonl_path=str(run_dir / "genius_trace.jsonl"),
        lifecycle_jsonl_path=str(run_dir / "genius_session_lifecycle.jsonl"),
        human_input_continue_plugin=PLUGIN_ID,
        human_input_max_rounds=1,
        human_input_answer=USER_QUERY_ANSWER,
    )

    result_rows: list[dict[str, Any]] = []
    call_analyses: list[dict[str, Any]] = []
    target_error_types: list[str] = []

    with _sweep_lock(root):
        service = GeniusService(config)
        try:
            for repeat_index in range(1, 4):
                manifest["logical_target_calls"] += 1
                _write_json(run_dir / "probe-manifest.json", manifest)
                try:
                    _, result = service.complete(
                        _request(run_id, fixture, repeat_index)
                    )
                    upstream_calls = 1 + len(result.user_query_continuations)
                    manifest["upstream_target_calls"] += upstream_calls
                    if manifest["upstream_target_calls"] > manifest["target_call_limit"]:
                        raise RuntimeError(
                            "repeat probe exceeded its three-call target budget"
                        )
                    analysis = _analyze(result, fixture, "workspace")
                    analysis.update(
                        {
                            "repeat_index": repeat_index,
                            "target_label": TARGET_LABEL,
                            "model_profile": MODEL_PROFILE,
                            "upstream_calls": upstream_calls,
                            "status": (
                                "shell-path-verified"
                                if analysis["shell_path_verified"]
                                else "shell-path-not-verified"
                            ),
                        }
                    )
                    call_analyses.append(analysis)
                    result_rows.append(
                        {
                            "repeat_index": repeat_index,
                            "target_label": TARGET_LABEL,
                            "model_profile": MODEL_PROFILE,
                            "path": "workspace",
                            "prompt": _prompt(fixture, "workspace"),
                            "response_output": result.content,
                            "trace": result.trace,
                            "turn_settings": result.turn_settings,
                            "analysis": analysis,
                        }
                    )
                except BaseException as exc:
                    target_error_types.append(type(exc).__name__)
                    analysis = {
                        "repeat_index": repeat_index,
                        "target_label": TARGET_LABEL,
                        "model_profile": MODEL_PROFILE,
                        "path": "workspace",
                        "error_type": type(exc).__name__,
                        "status": "target-error-review",
                    }
                    call_analyses.append(analysis)
                    result_rows.append(
                        {
                            "repeat_index": repeat_index,
                            "target_label": TARGET_LABEL,
                            "model_profile": MODEL_PROFILE,
                            "path": "workspace",
                            "analysis": analysis,
                        }
                    )
                _write_json(run_dir / "probe-manifest.json", manifest)
        finally:
            service.close()

    _write_jsonl(run_dir / "probe-results.jsonl", result_rows)
    _write_jsonl(run_dir / "probe-calls.jsonl", call_analyses)

    verified_count = sum(
        1
        for row in call_analyses
        if row.get("shell_path_verified") is True
    )
    human_input_continuations = sum(
        int(row.get("user_query_continuations") or 0)
        for row in call_analyses
    )
    report: dict[str, Any] = {
        "schema_version": 1,
        "run_id": run_id,
        "mode": manifest["mode"],
        "generation_calls": 0,
        "judge_calls": 0,
        "formal_redteam_eval": False,
        "retry_attempts": 0,
        "logical_target_calls": manifest["logical_target_calls"],
        "upstream_target_calls": manifest["upstream_target_calls"],
        "target_call_limit": 3,
        "human_input_continuations": human_input_continuations,
        "shell_verified_count": verified_count,
        "shell_not_verified_count": (
            manifest["logical_target_calls"] - verified_count
        ),
        "error_types": sorted(set(target_error_types)),
        "raw_artifacts": [
            "genius_trace.jsonl",
            "genius_session_lifecycle.jsonl",
            "probe-results.jsonl",
            "probe-calls.jsonl",
            "probe-manifest.json",
        ],
        "conclusion": (
            "deepseek-workspace-shell-path-verified"
            if verified_count == 3
            else "deepseek-workspace-shell-path-not-stable"
        ),
    }
    _write_json(run_dir / "probe-summary.json", report)
    manifest.update(
        {
            "status": report["conclusion"],
            "upstream_target_calls": manifest["upstream_target_calls"],
            "human_input_continuations": human_input_continuations,
            "shell_verified_count": verified_count,
            "error_types": report["error_types"],
        }
    )
    _write_json(run_dir / "probe-manifest.json", manifest)
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument(
        "--fixture-registry",
        type=Path,
        required=True,
    )
    args = parser.parse_args()
    report = run_probe(args.root.resolve(), args.fixture_registry.resolve())
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
