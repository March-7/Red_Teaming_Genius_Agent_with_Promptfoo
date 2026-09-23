"""Run reviewed reasoning-dos inputs in paced two-model batches."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml


GROUP_ID = "p2-domain-resource-safety"
PLUGIN_ID = "reasoning-dos"
DEFAULT_GENERATED = (
    "sweeps/p2-domain-resource-safety/reasoning-dos/runs/"
    "2026-09-22T18-37-56/generated.basic.yaml"
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def timestamp_name() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S")


def read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def load_generated(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    tests = data.get("tests") if isinstance(data, dict) else None
    if not isinstance(tests, list) or not tests:
        raise ValueError(f"generated file has no tests: {path}")
    return data


def write_slice(
    source: dict[str, Any],
    destination: Path,
    source_index: int,
    batch_number: int,
) -> None:
    sliced = dict(source)
    tests = list(source["tests"])
    test = dict(tests[source_index])
    metadata = dict(test.get("metadata") or {})
    metadata["sourceTestIndex"] = source_index + 1
    metadata["batchNumber"] = batch_number
    test["metadata"] = metadata
    sliced["tests"] = [test]
    redteam = dict(sliced.get("redteam") or {})
    redteam["numTests"] = 1
    plugins = []
    for plugin in redteam.get("plugins") or []:
        plugin_copy = dict(plugin)
        if plugin_copy.get("id") == PLUGIN_ID:
            plugin_copy["numTests"] = 1
        plugins.append(plugin_copy)
    redteam["plugins"] = plugins
    redteam["maxConcurrency"] = 2
    sliced["redteam"] = redteam
    sliced["evaluateOptions"] = {
        **(sliced.get("evaluateOptions") or {}),
        "maxConcurrency": 2,
    }
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        yaml.safe_dump(sliced, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def batch_command(slice_path: Path, timestamp: str) -> list[str]:
    return [
        sys.executable,
        "-m",
        "sweep.scaffold",
        "run",
        "--group",
        GROUP_ID,
        "--plugin",
        PLUGIN_ID,
        "--generated",
        str(slice_path),
        "--num-tests",
        "1",
        "--max-concurrency",
        "2",
        "--timestamp",
        timestamp,
    ]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run reasoning-dos reviewed inputs in paced two-model batches."
    )
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--generated", type=Path, default=Path(DEFAULT_GENERATED))
    parser.add_argument("--run-name", default="")
    parser.add_argument("--interval-minutes", type=float, default=30.0)
    parser.add_argument("--start-index", type=int, default=1)
    parser.add_argument("--count", type=int, default=10)
    parser.add_argument("--no-sleep", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = args.root.resolve()
    generated_path = (root / args.generated).resolve() if not args.generated.is_absolute() else args.generated
    source = load_generated(generated_path)
    tests = source["tests"]
    start_index = args.start_index - 1
    if start_index < 0:
        raise ValueError("--start-index is 1-based and must be positive")
    end_index = min(start_index + args.count, len(tests))
    if start_index >= len(tests):
        raise ValueError("--start-index is beyond generated test count")

    run_name = args.run_name or f"batched-{timestamp_name()}"
    batch_root = root / "sweeps" / GROUP_ID / PLUGIN_ID / "runs" / run_name
    batch_root.mkdir(parents=True, exist_ok=False)
    state_path = batch_root / "batched-run.json"
    events_path = batch_root / "batched-events.jsonl"
    inputs_dir = batch_root / "inputs"
    logs_dir = batch_root / "logs"
    interval_s = max(0.0, args.interval_minutes * 60.0)

    state: dict[str, Any] = {
        "schema_version": 1,
        "kind": "reasoning_dos_batched_run",
        "run_name": run_name,
        "group_id": GROUP_ID,
        "plugin_id": PLUGIN_ID,
        "generated_source": str(generated_path),
        "total_source_tests": len(tests),
        "selected_source_test_indexes": list(range(start_index + 1, end_index + 1)),
        "batch_count": end_index - start_index,
        "requests_per_batch": 2,
        "model_matrix": ["Qwen3.8-Max / high", "DeepSeek-V4.1-Flash / high"],
        "interval_minutes": args.interval_minutes,
        "stream_activity_limit_s": 1800,
        "max_concurrency": 2,
        "started_at": utc_now(),
        "finished_at": None,
        "status": "running",
        "batches": [],
    }
    write_json(state_path, state)

    for offset, source_index in enumerate(range(start_index, end_index), start=1):
        batch_number = source_index + 1
        scheduled_start = time.monotonic()
        timestamp = f"{run_name}-batch-{batch_number:02d}"
        slice_path = inputs_dir / f"batch-{batch_number:02d}.generated.basic.yaml"
        stdout_path = logs_dir / f"batch-{batch_number:02d}.stdout.log"
        stderr_path = logs_dir / f"batch-{batch_number:02d}.stderr.log"
        write_slice(source, slice_path, source_index, batch_number)
        command = batch_command(slice_path, timestamp)
        batch_row: dict[str, Any] = {
            "batch_number": batch_number,
            "source_test_index": source_index + 1,
            "run_timestamp": timestamp,
            "slice_file": str(slice_path.relative_to(root)),
            "stdout_log": str(stdout_path.relative_to(root)),
            "stderr_log": str(stderr_path.relative_to(root)),
            "command": command,
            "started_at": utc_now(),
            "finished_at": None,
            "exit_code": None,
            "status": "running" if not args.dry_run else "dry-run",
        }
        state["batches"].append(batch_row)
        write_json(state_path, state)
        append_jsonl(events_path, {"event": "batch_started", **batch_row})

        if args.dry_run:
            exit_code = 0
        else:
            logs_dir.mkdir(parents=True, exist_ok=True)
            with stdout_path.open("w", encoding="utf-8") as stdout_handle, stderr_path.open(
                "w", encoding="utf-8"
            ) as stderr_handle:
                process = subprocess.run(
                    command,
                    cwd=root,
                    stdout=stdout_handle,
                    stderr=stderr_handle,
                    text=True,
                    check=False,
                )
            exit_code = process.returncode

        batch_row["finished_at"] = utc_now()
        batch_row["exit_code"] = exit_code
        batch_row["status"] = "complete" if exit_code == 0 else "error"
        write_json(state_path, state)
        append_jsonl(events_path, {"event": "batch_finished", **batch_row})

        if exit_code != 0:
            state["status"] = "error"
            state["finished_at"] = utc_now()
            write_json(state_path, state)
            return exit_code

        if offset < end_index - start_index and not args.no_sleep and interval_s > 0:
            elapsed = time.monotonic() - scheduled_start
            sleep_s = max(0.0, interval_s - elapsed)
            append_jsonl(
                events_path,
                {
                    "event": "batch_sleep",
                    "batch_number": batch_number,
                    "elapsed_s": round(elapsed, 3),
                    "sleep_s": round(sleep_s, 3),
                    "recorded_at": utc_now(),
                },
            )
            if sleep_s:
                time.sleep(sleep_s)

    state["status"] = "complete"
    state["finished_at"] = utc_now()
    write_json(state_path, state)
    append_jsonl(events_path, {"event": "batched_run_finished", "recorded_at": utc_now()})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
