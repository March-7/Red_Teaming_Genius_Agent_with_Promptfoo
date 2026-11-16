"""Offline commands and preparation; general A execution requires separate run confirmation."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import subprocess
import time
from typing import Any

from sweep import runtime
from .audit import lifecycle_gate, verified_lifecycle_rows
from .budget import Ledger, require_confirmation
from .evidence import read_rows
from .registry import validate_interface
from .registry import ResourceRegistry, validate_absent_locator, validate_skill
from .report import replay
from .schema import canonical_hash, identifier, load_suite
from .schema import validate_isolation
from .transport import case_request
from .http_accounting import meter_client

DEFAULT_SUITE = "skill-suites/skill-task-scope-write/suite.yaml"


def call_bound_case(root: Path, run_dir: Path, key: tuple[str, str, str], service_factory: Any,
                    *, live: bool = True, consumer: Any = None, consumer_kind: str = "local") -> dict[str, Any]:
    """Single fixed case through injected transport; general_a supplies the approved live factory.

    live=False is exclusively for contract fixtures. A human confirmation is still
    required, and fixture output can never establish live acceptance.
    """
    if run_dir.resolve().parent.parent.parent != (root / "skill-suites").resolve():
        raise ValueError("Skill run must belong to the locked project skill-suites directory")
    with runtime.sweep_lock(root):
        suite = load_suite(run_dir / "suite.snapshot.yaml")
        if suite["phase"] not in {"A", "B"}:
            raise ValueError("only confirmed A/B fixed-case transport is implemented")
        manifest = json.loads((run_dir / "run-manifest.json").read_text())
        require_confirmation(suite, manifest["run_id"])
        if live and (suite["schema_version"] != 2 or suite.get("target_context") != "global-general"
                     or manifest.get("target_context") != "global-general"):
            raise ValueError("live main-study calls require explicit global-general scope; historical Workspace runs are replay-only")
        if manifest["suite_scope_hash"] != canonical_hash({k: v for k, v in suite.items() if k != "confirmation"}):
            raise ValueError("suite scope drift")
        for name in ("suite.snapshot.yaml", "approval-policy.json"):
            if runtime.sha256_file(run_dir / name) != manifest["artifact_hashes"][name]:
                raise ValueError("prepared snapshot changed")
        if runtime.sha256_file(runtime.GUARD_PATH) != manifest["sensitive_output_guard"]["sha256"]:
            raise ValueError("prepared guard changed")
        if live:
            for path, expected_hash in manifest["code_hashes"].items():
                if runtime.sha256_file(Path(path)) != expected_hash:
                    raise ValueError("prepared execution code changed: " + path)
        rows = read_rows(run_dir / "case-registry.jsonl")
        validate_isolation(rows, suite)
        matches = [r for r in rows if tuple(r[k] for k in ("case_id", "model_profile", "variant")) == key]
        if len(matches) != 1 or matches[0]["run_id"] != manifest["run_id"]:
            raise ValueError("unique run-bound case required")
        case = matches[0]
        if suite["schema_version"] == 2 and not case["session_id"].startswith("chat:"):
            raise ValueError("general target requires a registered native chat session")
        interfaces = [r for r in read_rows(run_dir / "skill-interface-audit.jsonl")
                      if r.get("attestation_id") == suite["interface_attestation"]]
        if len(interfaces) != 1:
            raise ValueError("observed interface missing")
        validate_interface(interfaces[0], run_dir, live=live)
        if suite["schema_version"] == 2 and interfaces[0]["scope_type"] != "private-user-catalogue":
            raise ValueError("general target requires a private user catalogue interface")
        resources = ResourceRegistry(run_dir / "resource-registry.jsonl", manifest["run_id"])
        for rid, kind in ((case["scope_id"], "scope"), (case["session_id"], "session")):
            if resources.owned(rid)["kind"] != kind:
                raise ValueError("case resources are not isolated and owned")
        if case["variant"] != "absent":
            skills = [r for r in read_rows(run_dir / "skill-registry.jsonl")
                      if (r.get("skill_id"), r.get("case_id"), r.get("model_profile"), r.get("variant"))
                      == (case["skill_id"], case["case_id"], case["model_profile"], case["variant"]) ]
            if len(skills) != 1:
                raise ValueError("unique Skill import/binding evidence required")
            validate_skill(skills[0], run_dir, case)
        elif suite["schema_version"] == 2:
            controls = [r for r in read_rows(run_dir / "absence-registry.jsonl") if r.get("case_id") == case["case_id"]]
            if len(controls) != 1:
                raise ValueError("absent catalogue locator proof required")
            validate_absent_locator(controls[0], run_dir, case, live=live)
        ledger = Ledger(run_dir / "call-ledger.json", suite["phases"][suite["phase"]])
        operation = "target:" + ":".join(key)
        settings = {"upstream_retry_attempts": 0, "human_input_continue_plugin": "", "human_input_max_rounds": 0,
                    "stream_activity_limit_s": ledger.limits["activity_per_call_s"],
                    "skill_case_registry_path": str(run_dir / "case-registry.jsonl"),
                    "skill_case_registry_hash": runtime.sha256_file(run_dir / "case-registry.jsonl"),
                    "approval_policy_file": str(run_dir / "approval-policy.json"),
                    "trace_jsonl_path": str(run_dir / "genius_trace.jsonl"),
                    "lifecycle_jsonl_path": str(run_dir / "session_lifecycle.jsonl")}
        service = service_factory(settings)
        http_records: list[dict[str, Any]] = []
        meter = None
        sample = {**{k: case[k] for k in ("run_id", "case_id", "model_profile", "variant", "skill_id", "skill_version", "skill_hash", "scope_id", "session_id")},
                  "principal_id": case["session_id"].split(":")[1] if case["session_id"].startswith("chat:") else None,
                  "target_context": case.get("target_context", "historical-unspecified"),
                  "session_type": "general" if case["session_id"].startswith("chat:") else "workspace",
                  "environment": "live" if live else "offline-fixture", "source_verified": False,
                  "submitted": False, "target_error": None, "guard_error": None, "judge": None, "output": None}
        try:
            if any(getattr(service.config, k, None) != v for k, v in settings.items()):
                raise ValueError("transport changed required runtime settings")
            if live:
                from shim.genius_service import GeniusService
                if not isinstance(service, GeniusService):
                    raise ValueError("live execution requires the shared metered GeniusService")
            ledger.reserve("target", operation)
            sample["submitted"] = True
            sample["target_started_at"] = runtime.utc_now()
            meter = meter_client(getattr(service, "_client", None), ledger, operation, fixture=not live)
            http_records = meter.__enter__()
            started = time.monotonic()
            try:
                _, result = service.complete(case_request(case))
                elapsed = time.monotonic() - started
                terminal = result.terminal_status
                sample["terminal_status"] = terminal
                sample["target_finished_at"] = runtime.utc_now()
                if result.upstream_session_id != case["session_id"] or terminal not in {"completed", "failed", "cancelled"}:
                    raise RuntimeError("upstream session/terminal unverified")
                sample["request_id"] = result.request_id
                if terminal != "completed":
                    sample["target_error"] = "upstream-" + terminal
                    ledger.finish(operation, sample["target_error"], elapsed_s=elapsed)
                else:
                    try:
                        sample["output"] = runtime.guard_output(result.content, known_hashes=runtime.sensitive_value_hashes(root) if live else "")
                    except runtime.SensitiveOutputError:
                        sample["guard_error"] = "SENSITIVE_OUTPUT_REVIEW_REQUIRED"
                    ledger.finish(operation, "guard-error" if sample["guard_error"] else "completed", elapsed_s=elapsed)
            except Exception as exc:
                ledger.finish(operation, "target-error", elapsed_s=time.monotonic() - started)
                sample["target_error"] = type(exc).__name__
                runtime.record_pending(root, manifest["run_id"], case["session_id"], operation)
            if consumer is not None and sample["output"] is not None:
                if consumer_kind not in {"local", "judge", "generation"}:
                    raise ValueError("unknown output consumer")
                if consumer_kind != "local":
                    ledger.reserve(consumer_kind, operation + ":" + consumer_kind)
                consumer(sample["output"])
                if consumer_kind != "local":
                    ledger.finish(operation + ":" + consumer_kind, "completed")
        except Exception as exc:
            if not sample["submitted"]:
                sample["target_error"] = "preflight-" + type(exc).__name__
            raise
        finally:
            if meter is not None:
                meter.__exit__(None, None, None)
            service.close()
            path = run_dir / "samples.json"
            existing = json.loads(path.read_text())
            if sample["submitted"]:
                existing.append(sample)
            runtime.write_json(path, existing)
            manifest["call_accounting"] = ledger.state["counts"]
            manifest.setdefault("http_attempts", []).extend(http_records)
            manifest["status"] = "needs-review" if ledger.state["stopped"] else "running"
            manifest["artifact_hashes"].update({p.name: runtime.sha256_file(p) for p in run_dir.iterdir()
                if p.is_file() and p.name != "run-manifest.json"})
            runtime.write_json(run_dir / "run-manifest.json", manifest)
        return sample


def recover_pending(root: Path, run_dir: Path, read_terminal: Any) -> dict[str, Any]:
    """Injected read-only terminal reader, budgeted separately from target submission."""
    if run_dir.resolve().parent.parent.parent != (root / "skill-suites").resolve():
        raise ValueError("recovery run must belong to the locked project")
    manifest = json.loads((run_dir / "run-manifest.json").read_text())
    run_id = manifest["run_id"]
    with runtime.sweep_lock(root, recovery_run=run_id):
        suite = load_suite(run_dir / "suite.snapshot.yaml")
        require_confirmation(suite, run_id)
        ledger = Ledger(run_dir / "call-ledger.json", suite["phases"][suite["phase"]])
        try:
            for row in list(runtime.read_ownership(root).values()):
                session = row["session_id"]
                operation = "terminal-read:" + session + ":" + str(ledger.state["counts"]["recovery"] + 1)
                ledger.reserve("recovery", operation)
                try:
                    terminal = read_terminal(session)
                    if terminal.get("session_id") != session or terminal.get("read_only") is not True:
                        raise ValueError("matching read-only upstream terminal response required")
                    path = run_dir / ("terminal-read-" + str(ledger.state["counts"]["recovery"]) + ".json")
                    runtime.write_json(path, terminal)
                    if terminal.get("status") in {"completed", "failed", "cancelled"}:
                        runtime.resolve_pending(root, run_id, session, {"session_id": session, "status": terminal["status"],
                            "evidence_path": str(path), "evidence_hash": runtime.sha256_file(path)})
                    ledger.finish(operation, "completed")
                except Exception:
                    ledger.finish(operation, "terminal-read-error")
                    raise
        finally:
            manifest["call_accounting"] = ledger.state["counts"]
            manifest["status"] = "pending-upstream" if runtime.read_ownership(root) else "recovery-complete-needs-review"
            manifest["artifact_hashes"].update({p.name: runtime.sha256_file(p) for p in run_dir.iterdir()
                if p.is_file() and p.name != "run-manifest.json"})
            runtime.write_json(run_dir / "run-manifest.json", manifest)
        return {"pending": runtime.read_ownership(root), "calls": ledger.state["counts"]}


def preview(suite: dict[str, Any]) -> dict[str, Any]:
    phase = suite["phase"]
    return {"kind": "skill-suite-preview", "offline": True, "suite_id": suite["suite_id"],
            "risk_id": suite["risk_id"], "phase": phase, "model_matrix": suite["model_matrix"],
            "limits": suite["phases"][phase], "max_concurrency": suite["max_concurrency"],
            "retry": 0, "allowed_behavior": suite["allowed_behavior"],
            "failure_criterion": suite["failure_criterion"],
            "phase_success_criterion": "两模型的正常 Skill 导入/绑定/选择/读取/行为及缺席对照都有可核对证据" if phase == "A" else "完成本阶段证据 gate",
            "phase_failure_criterion": "身份/内容/作用域或正常行为证据缺失，或缺席对照无效，即 blocked；不报告攻击 ASR" if phase == "A" else suite["failure_criterion"],
            "example_2_scope": "A 的缺席任务说明用途；真实执行覆盖两模型各正常/缺席一条",
            "examples": [{"purpose": "说明用途，不是在线请求", "text": text} for text in suite["examples"]],
            "lifecycle": suite["lifecycle"], "target_calls": 0, "generation_calls": 0, "judge_calls": 0,
            "effective_backend_settings": "unverified", "target_context": suite.get("target_context", "historical-unspecified"),
            "session_type": "general" if suite.get("target_context") == "global-general" else "historical-unspecified"}


def gate(suite: dict[str, Any], run_dir: Path | None = None) -> dict[str, Any]:
    missing = []
    if suite.get("target_context") != "global-general":
        missing.append("historical/unspecified assistant context cannot unlock the main global study")
    if run_dir is None:
        missing.extend(["run-local interface attestation", "phase-bound user start confirmation",
                        "actual normal Skill lifecycle", "actual absent controls"])
        if suite["lifecycle"] == "unselected": missing.append("retain/cleanup choice")
    else:
        try:
            manifest = json.loads((run_dir / "run-manifest.json").read_text())
            if manifest.get("suite_scope_hash") != canonical_hash({k: v for k, v in suite.items() if k != "confirmation"}):
                raise ValueError("suite preparation changed")
            if manifest.get("target_context") != "global-general" or manifest.get("session_type") != "general":
                raise ValueError("manifest does not identify the global general assistant")
            require_confirmation(suite, manifest["run_id"])
        except (OSError, ValueError, KeyError, RuntimeError) as exc:
            missing.append(str(exc))
        interface_path = run_dir / "skill-interface-audit.jsonl"
        try:
            candidates = [r for r in read_rows(interface_path) if r.get("attestation_id") == suite["interface_attestation"]]
            if len(candidates) != 1:
                raise ValueError("observed interface attestation missing")
            validate_interface(candidates[0], run_dir)
            if suite["schema_version"] == 2 and candidates[0]["scope_type"] != "private-user-catalogue":
                raise ValueError("general interface cannot claim a Project binding")
        except (OSError, ValueError, KeyError) as exc:
            missing.append(str(exc))
        try:
            rows = verified_lifecycle_rows(run_dir, suite)
            missing.extend(lifecycle_gate(rows)["missing"])
        except (OSError, ValueError, KeyError, TypeError) as exc:
            missing.append("lifecycle evidence: " + str(exc))
    if suite["phase"] in {"B", "C"}:
        missing.append("verified write/readback and first pair evidence")
    return {"status": "blocked-prerequisite" if missing else "ready", "missing": missing,
            "offline": True, "online_execution": "general-A-internal-api" if suite.get("target_context") == "global-general"
                and suite["phase"] == "A" else "not-implemented", "target_calls": 0,
            "generation_calls": 0, "judge_calls": 0}


def prepare(root: Path, suite_path: Path, run_id: str) -> Path:
    """Only local artifact creation; no capability/confirmation facts are generated."""
    suite = load_suite(suite_path)
    if suite_path.resolve().parent != (root / "skill-suites" / suite["risk_id"]).resolve():
        raise ValueError("prepared raw run must live in the project Skill suite")
    identifier(run_id, "run_id")
    policy = (suite_path.parent / suite["approval_policy"]).read_bytes()
    # Validate before making a partial run directory.
    errors = runtime.validate_policy_document(json.loads(policy), "suite policy")
    if errors or any(not json.loads(policy)["rules"][0][k].startswith("unbound-")
                     for k in runtime.POLICY_REQUIRED_FIELDS[1:]):
        raise ValueError("valid unbound suite policy required")
    run_dir = suite_path.parent / "runs" / run_id
    with runtime.sweep_lock(root):
        run_dir.mkdir(parents=True, exist_ok=False)
        (run_dir / "suite.snapshot.yaml").write_bytes(suite_path.read_bytes())
        policy_hash = runtime.snapshot_policy(policy, run_dir / "approval-policy.json", unbound=True)
        for name in ("case-registry.jsonl", "skill-registry.jsonl", "skill-interface-audit.jsonl",
                     "skill-source-audit.jsonl", "genius_trace.jsonl", "session_lifecycle.jsonl",
                     "oracle.jsonl", "lifecycle-audit.jsonl", "absence-registry.jsonl"):
            (run_dir / name).touch()
        ledger = Ledger(run_dir / "call-ledger.json", suite["phases"][suite["phase"]])
        revision = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, text=True, capture_output=True)
        package_path = root / "node_modules/promptfoo/package.json"
        promptfoo_version = json.loads(package_path.read_text())["version"] if package_path.exists() else "not-installed-in-this-root"
        source_root = Path(__file__).resolve().parent.parent
        code_files = [runtime.GUARD_PATH, Path(runtime.__file__),
                      source_root / "shim/genius_service.py", source_root / "sweep/models.py",
                      *Path(__file__).parent.glob("*.py")]
        manifest = {"schema_version": 1, "kind": "skill-suite", "run_id": run_id,
                    "suite_id": suite["suite_id"], "risk_id": suite["risk_id"], "phase": suite["phase"],
                    "status": "prepared-offline", "started_at": None, "finished_at": None,
                    "model_matrix": suite["model_matrix"], "model_catalogue": "not-queried",
                    "effective_backend_settings": "unverified", "retry": 0,
                    "suite_scope_hash": canonical_hash({k: v for k, v in suite.items() if k != "confirmation"}),
                    "limits": ledger.limits, "call_accounting": ledger.state["counts"],
                    "policy_hash": policy_hash, "lifecycle": suite["lifecycle"],
                    "sensitive_output_guard": {"path": str(runtime.GUARD_PATH), "sha256": runtime.sha256_file(runtime.GUARD_PATH)},
                    "artifact_hashes": {"suite.snapshot.yaml": runtime.sha256_file(run_dir / "suite.snapshot.yaml"),
                                        "approval-policy.json": policy_hash},
                    "dynamic_acceptance": "not-run"}
        manifest["target_context"] = suite.get("target_context", "historical-unspecified")
        manifest["session_type"] = "general" if suite.get("target_context") == "global-general" else "historical-unspecified"
        manifest.update(git_commit=revision.stdout.strip() if revision.returncode == 0 else None,
                        promptfoo_version=promptfoo_version, python_version=sys.version.split()[0],
                        code_hashes={str(p): runtime.sha256_file(p) for p in code_files})
        runtime.write_json(run_dir / "run-manifest.json", manifest)
        runtime.write_json(run_dir / "samples.json", [])
    return run_dir


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Offline Genius Skill suite facilities")
    parser.add_argument("command", choices=("preview", "validate", "gate", "prepare", "replay"))
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--suite", type=Path)
    parser.add_argument("--run-id")
    parser.add_argument("--run-dir", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "replay":
            if not args.run_dir or not args.output:
                raise ValueError("replay requires --run-dir and --output")
            result = replay(args.run_dir, args.output)
        else:
            path = args.suite or args.root / DEFAULT_SUITE
            suite = load_suite(path)
            if args.command == "preview":
                result = preview(suite)
            elif args.command == "validate":
                policy = json.loads((path.parent / suite["approval_policy"]).read_text())
                errors = runtime.validate_policy_document(policy, "suite policy")
                if errors or any(not policy["rules"][0][k].startswith("unbound-") for k in runtime.POLICY_REQUIRED_FIELDS[1:]):
                    raise ValueError("valid unbound policy required")
                result = {"status": "valid", "offline": True, "dynamic_acceptance": "not-run"}
            elif args.command == "gate":
                result = gate(suite, args.run_dir)
            else:
                if not args.run_id:
                    raise ValueError("prepare requires --run-id")
                result = {"status": "prepared-offline", "run_dir": str(prepare(args.root, path, args.run_id)), "target_calls": 0}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, RuntimeError, KeyError) as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
