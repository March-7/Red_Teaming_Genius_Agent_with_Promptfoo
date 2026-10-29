"""Confirmed, zero-retry Promptfoo generation dispatcher; no Genius target calls."""
from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
import json
import os
from pathlib import Path
import subprocess
from typing import Any

from dotenv import dotenv_values
import yaml

from sweep import runtime
from .budget import Ledger
from .campaign import timestamp
from .schema import content_hash


LIMITS = {"target": 0, "management": 0, "recovery": 0, "cleanup": 0,
          "generation": 10, "judge": 0, "activity_total_s": 0,
          "activity_per_call_s": 0, "skills": 0, "scopes": 0, "sessions": 0}


def authorize(run: Path, message_ref: str) -> dict[str, Any]:
    """Record the user's separate C-generation approval, never infer it."""
    plan_path = run / "generation-plan.json"
    plan = json.loads(plan_path.read_text())
    path = run / "generation-authorization.json"
    prior = json.loads(path.read_text())
    if (prior.get("status") != "not-authorized" or not message_ref
            or plan.get("max_requests") != 10 or plan.get("max_concurrency") != 2
            or plan.get("retry") != 0):
        raise ValueError("fresh reviewed generation plan and human reply required")
    record = {"actor": "human-user", "decision": "start", "phase": "C-generation",
              "plan_sha256": runtime.sha256_file(plan_path),
              "scope_hash": plan["generation_scope_hash"],
              "message_ref": message_ref, "confirmed_at": runtime.utc_now()}
    runtime.write_json(path, record)
    return record


def _preflight(root: Path, run: Path) -> tuple[dict[str, Any], str]:
    if not run.resolve().is_relative_to((root / "skill-suites/skill-task-scope-write/runs").resolve()):
        raise ValueError("Skill generation run must belong to the ignored suite runs")
    plan_path = run / "generation-plan.json"
    plan = json.loads(plan_path.read_text())
    authorization = json.loads((run / "generation-authorization.json").read_text())
    if (plan.get("kind") != "skill-generation-plan" or plan.get("phase") != "C-generation"
            or plan.get("provider_id") != "openai:chat:qwen3.8-max"
            or plan.get("model") != "qwen3.8-max"
            or plan.get("api_base_url") != "https://dashscope.aliyuncs.com/compatible-mode/v1"
            or plan.get("max_requests") != 10 or plan.get("max_concurrency") != 2
            or plan.get("retry") != 0 or plan.get("max_input_tokens") != 4000
            or plan.get("max_output_tokens") != 8000
            or plan.get("http_timeout_seconds") != 300
            or plan.get("worker_timeout_seconds") != 330
            or plan.get("enable_thinking") is not False
            or len(plan.get("jobs", [])) != 10):
        raise ValueError("generation provider or request budget drift")
    if (authorization.get("actor") != "human-user"
            or authorization.get("decision") != "start"
            or authorization.get("phase") != "C-generation"
            or authorization.get("plan_sha256") != runtime.sha256_file(plan_path)
            or authorization.get("scope_hash") != plan.get("generation_scope_hash")
            or not authorization.get("message_ref")):
        raise ValueError("explicit C-generation authorization missing")
    timestamp(authorization.get("confirmed_at"))
    provider_root = root / "skill-suites/skill-task-scope-write/promptfoo"
    if (plan.get("provider_config_sha256") != runtime.sha256_file(run / "provider-config.json")
            or plan.get("execution_code_sha256") != runtime.sha256_file(provider_root / "dashscope-one-shot.mjs")
            or plan.get("network_guard_sha256") != runtime.sha256_file(provider_root / "allow-dashscope.cjs")
            or plan.get("runner_code_sha256") != runtime.sha256_file(Path(__file__))):
        raise ValueError("approved generation code/config drift")
    ids = set()
    for job in plan["jobs"]:
        job_id = job["job_id"]
        if job_id in ids or job_id not in {f"gen-{index:02d}" for index in range(10)}:
            raise ValueError("ten unique reviewed generation jobs required")
        ids.add(job_id)
        directory = run / "jobs" / job_id
        if (job.get("plugin_sha256") != runtime.sha256_file(directory / "plugin.yaml")
                or job.get("live_config_sha256") != runtime.sha256_file(directory / "live-config.yaml")
                or job.get("prompt_sha256") != runtime.sha256_file(directory / "prompt.txt")
                or job.get("prompt_text") != (directory / "prompt.txt").read_text()
                or not isinstance(job.get("max_prompt_chars"), int)
                or job["max_prompt_chars"] > 16000):
            raise ValueError("generation job prompt/plugin/config drift")
        for name in ("generated-live.yaml", "attempt-" + job_id + ".json"):
            if (directory / name).exists() or (run / name).exists():
                raise ValueError("zero retry: generation job already attempted")
    if (run / "generation-ledger.json").exists() or (run / "generation-result.json").exists():
        raise ValueError("zero retry: generation stage already started")
    key = os.environ.get("DASHSCOPE_API_KEY")
    if not key:
        key = dotenv_values(root / ".env").get("DASHSCOPE_API_KEY")
    if not key:
        key = dotenv_values(root / ".env.promptfoo").get("DASHSCOPE_API_KEY")
    if not isinstance(key, str) or not key:
        raise ValueError("DASHSCOPE_API_KEY unavailable; no generation request submitted")
    return plan, key


def _validate_job(run: Path, job: dict[str, Any]) -> dict[str, Any]:
    job_id = job["job_id"]
    attempt_path = run / ("attempt-" + job_id + ".json")
    attempt = json.loads(attempt_path.read_text())
    ref = attempt.get("raw_response_ref")
    if (attempt.get("environment") != "live" or attempt.get("status") != "completed"
            or attempt.get("job_id") != job_id
            or attempt.get("prompt_sha256") != job["prompt_sha256"]
            or not isinstance(ref, dict) or ref.get("file") != "raw-response-" + job_id + ".json"
            or ref.get("sha256") != runtime.sha256_file(run / ref["file"])):
        raise ValueError("one matching hosted provider response required")
    raw = json.loads((run / ref["file"]).read_text())
    output = raw.get("choices", [{}])[0].get("message", {}).get("content")
    if not isinstance(output, str) or not output.startswith("PromptBlock: "):
        raise ValueError("raw hosted response lacks one Prompt JSON package")
    payload = json.loads(output.removeprefix("PromptBlock: "))
    generated = yaml.safe_load((run / "jobs" / job_id / "generated-live.yaml").read_text())
    tests = generated.get("tests", [])
    if (len(tests) != 1 or set(tests[0].get("vars", {})) != {"skill_payload"}
            or tests[0].get("metadata", {}).get("pluginId") != "file://./plugin.yaml"
            or len(tests[0].get("assert", [])) != 1
            or tests[0]["assert"][0].get("type") != "llm-rubric"
            or tests[0]["assert"][0].get("metric") != "skill-write-candidate"
            or json.loads(tests[0]["vars"]["skill_payload"]) != payload
            or payload.get("skill_key") != job["expected_skill_key"]
            or payload.get("effect_artifact_name") != job["effect_artifact_name"]):
        raise ValueError("raw response and Promptfoo normalized payload drift")
    return {"job_id": job_id, "raw_response_ref": ref,
            "generated_sha256": runtime.sha256_file(run / "jobs" / job_id / "generated-live.yaml"),
            "reported_usage": attempt.get("usage"), "status": "completed"}


def execute(root: Path, run: Path, *, command_runner=subprocess.run) -> dict[str, Any]:
    """Run at most two frozen jobs concurrently; first failure stops new dispatch."""
    plan, key = _preflight(root, run)
    provider_root = root / "skill-suites/skill-task-scope-write/promptfoo"
    with runtime.sweep_lock(root):
        runtime.require_free_shim_port()
        ledger = Ledger(run / "generation-ledger.json", LIMITS)
        jobs = sorted(plan["jobs"], key=lambda job: job["job_id"])
        results: list[dict[str, Any]] = []
        failed = False
        def worker(job):
            job_id = job["job_id"]
            operation = "generation:" + job_id
            ledger.reserve("generation", operation)
            directory = run / "jobs" / job_id
            env = {name: os.environ[name] for name in ("PATH", "HOME", "LANG") if name in os.environ}
            env.update({"DASHSCOPE_API_KEY": key, "SKILL_GENERATION_RUN_DIR": str(run.resolve()),
                "SKILL_GENERATION_JOB_ID": job_id, "SKILL_GENERATION_MODE": "live",
                "PROMPTFOO_DISABLE_REDTEAM_REMOTE_GENERATION": "1",
                "PROMPTFOO_DISABLE_UPDATE": "true",
                "PROMPTFOO_DISABLE_TELEMETRY": "1",
                "NODE_OPTIONS": "--require=" + str(provider_root / "allow-dashscope.cjs")})
            command = [str(root / "node_modules/.bin/promptfoo"), "redteam", "generate",
                "-c", str(directory / "live-config.yaml"),
                "-o", str(directory / "generated-live.yaml"),
                "--no-cache", "--force", "--no-progress-bar", "--strict"]
            try:
                response = command_runner(command, cwd=root, env=env,
                                          capture_output=True, text=True,
                                          timeout=plan["worker_timeout_seconds"])
                (directory / "cli-stdout.txt").write_text(response.stdout)
                (directory / "cli-stderr.txt").write_text(response.stderr)
                if response.returncode != 0:
                    raise ValueError("Promptfoo generation failed with exit " + str(response.returncode))
                detail = _validate_job(run, job)
                ledger.finish(operation, "completed")
                return detail
            except Exception as exc:
                ledger.finish(operation, "generation-error")
                return {"job_id": job_id, "status": "error", "error_type": type(exc).__name__}
        with ThreadPoolExecutor(max_workers=2) as pool:
            pending = {}
            next_index = 0
            while next_index < len(jobs) and len(pending) < 2:
                job = jobs[next_index]; next_index += 1
                pending[pool.submit(worker, job)] = job["job_id"]
            while pending:
                completed, _ = wait(pending, return_when=FIRST_COMPLETED)
                for future in completed:
                    pending.pop(future)
                    detail = future.result()
                    results.append(detail)
                    if detail["status"] != "completed":
                        failed = True
                while not failed and next_index < len(jobs) and len(pending) < 2:
                    job = jobs[next_index]; next_index += 1
                    pending[pool.submit(worker, job)] = job["job_id"]
        status = "generation-complete-needs-review" if not failed and len(results) == 10 else "generation-stopped"
        report = {"kind": "skill-generation-dispatch", "status": status,
            "plan_sha256": runtime.sha256_file(run / "generation-plan.json"),
            "provider_id": plan["provider_id"], "max_concurrency": 2, "retry": 0,
            "job_results": sorted(results, key=lambda row: row["job_id"]),
            "call_accounting": ledger.state["counts"],
            "genius_target_calls": 0, "judge_calls": 0, "formal_ready": False}
        runtime.write_json(run / "generation-result.json", report)
        return report
