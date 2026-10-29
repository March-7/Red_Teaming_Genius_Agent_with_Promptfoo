"""Confirmed general A/B management receipts using the observed first-party client API."""
from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
from typing import Any
from urllib.parse import quote

from sweep import runtime
from .budget import Ledger, require_confirmation
from .evidence import read_ref
from .http_accounting import meter_client
from .schema import canonical_hash, load_suite


def authorize(run: Path, message_ref: str) -> dict[str, Any]:
    """Record an actual human reply; this function never supplies consent itself."""
    suite = load_suite(run / "suite.snapshot.yaml")
    manifest = json.loads((run / "run-manifest.json").read_text())
    if suite.get("target_context") != "global-general" or manifest["status"] != "prepared-offline":
        raise ValueError("fresh prepared general A/B run required")
    if not message_ref or suite["confirmation"] is not None:
        raise ValueError("fresh human reply reference required")
    suite["confirmation"] = {"actor": "human-user", "decision": "start", "phase": suite["phase"],
        "run_id": manifest["run_id"], "scope_hash": canonical_hash({k:v for k,v in suite.items() if k != "confirmation"}),
        "message_ref": message_ref, "confirmed_at": runtime.utc_now()}
    import yaml
    (run / "suite.snapshot.yaml").write_text(yaml.safe_dump(suite, allow_unicode=True, sort_keys=False))
    manifest.update(status="confirmed-general-" + suite["phase"], authorization=suite["confirmation"], started_at=runtime.utc_now())
    manifest["artifact_hashes"]["suite.snapshot.yaml"] = runtime.sha256_file(run / "suite.snapshot.yaml")
    runtime.write_json(run / "run-manifest.json", manifest)
    return suite["confirmation"]


class ManagementSession:
    """Caller holds the project lock; every HTTP attempt is metered, without retries."""
    def __init__(self, root: Path, run: Path, lease: runtime.RunLease):
        lease.require_active()
        if lease.root != root.resolve() or run.resolve().parent.parent.parent != (root / "skill-suites").resolve():
            raise ValueError("active lease and run must belong to this project")
        self.root, self.run, self.lease = root, run, lease
        self.suite = load_suite(run / "suite.snapshot.yaml")
        self.manifest = json.loads((run / "run-manifest.json").read_text())
        require_confirmation(self.suite, self.manifest["run_id"])
        if self.suite.get("target_context") != "global-general" or self.suite["phase"] not in {"A", "B"}:
            raise ValueError("only confirmed general A/B management is enabled")
        if runtime.sha256_file(run / "approval-policy.json") != self.manifest["policy_hash"]:
            raise ValueError("policy drift")
        if runtime.sha256_file(runtime.GUARD_PATH) != self.manifest["sensitive_output_guard"]["sha256"]:
            raise ValueError("guard drift")
        for path, expected_hash in self.manifest.get("code_hashes", {}).items():
            if runtime.sha256_file(Path(path)) != expected_hash:
                raise ValueError("prepared execution code changed: " + path)
        plan = read_ref(run, self.manifest["preparation_ref"])
        for ref in plan["source_refs"]: read_ref(run, ref) if ref["file"].endswith(".json") else self._verify_file(ref)
        for ref in plan.get("prior_receipts", []): read_ref(run, ref)
        # Credentials are loaded only after the phase/run/scope and lease gates.
        from dotenv import load_dotenv
        from shim.genius_service import GeniusService, ShimConfig
        load_dotenv(root / ".env", override=True)
        config = replace(ShimConfig.from_env(), upstream_retry_attempts=0, token_refresh_margin_s=0,
            hard_timeout_s=300, stream_activity_limit_s=300, human_input_continue_plugin="", human_input_max_rounds=0,
            approval_policy_file=str(run / "approval-policy.json"), trace_jsonl_path=str(run / "genius_trace.jsonl"),
            lifecycle_jsonl_path=str(run / "session_lifecycle.jsonl"), trace_raw_events=True)
        self.service = GeniusService(config)
        self.ledger = Ledger(run / "call-ledger.json", self.suite["phases"][self.suite["phase"]])

    def _verify_file(self, ref: dict[str, Any]) -> None:
        from .evidence import local_file
        if runtime.sha256_file(local_file(self.run, ref["file"])) != ref["sha256"]:
            raise ValueError("observed API source changed")

    def request(self, name: str, method: str, path: str, body: dict[str, Any] | None = None,
                *, accounting_kind: str = "management") -> dict[str, Any]:
        self.lease.require_active()
        from .schema import identifier
        identifier(name, "management receipt")
        if accounting_kind == "recovery" and method != "GET":
            raise ValueError("recovery is read-only")
        receipt_path = self.run / (name + ".json")
        if receipt_path.exists():
            raise ValueError("zero retries: management receipt already exists")
        records: list[dict[str, Any]] = []
        receipt = {"request": {"method": method, "path": path}, "response": None,
                   "environment": "live", "observed_at": runtime.utc_now()}
        if body is not None: receipt["request"]["body"] = body
        try:
            with meter_client(self.service._client, self.ledger, accounting_kind + ":" + name,
                              management_kind=accounting_kind) as records:
                response = self.service._request_json(method, path, json_body=body)
            receipt["response"] = {"status": records[-1]["status_code"], "body": response}
            return response
        except Exception as exc:
            receipt["error"] = type(exc).__name__
            self.ledger.stop("management-error:" + type(exc).__name__)
            raise
        finally:
            runtime.write_json(receipt_path, receipt)
            self.manifest.setdefault("http_attempts", []).extend(records)
            self.manifest["call_accounting"] = self.ledger.state["counts"]
            self.manifest["status"] = "stopped" if self.ledger.state["stopped"] else "management-running"
            self.manifest["artifact_hashes"][receipt_path.name] = runtime.sha256_file(receipt_path)
            runtime.write_json(self.run / "run-manifest.json", self.manifest)

    def close(self) -> None:
        self.service.close()


def catalogue_identity(run: Path, profile: str, asset: dict[str, Any], principal_id: str) -> dict[str, Any]:
    """Validate actual observed GET Skill + sharing responses, not saved booleans."""
    metadata = json.loads((run / ("A-read-" + profile + ".json")).read_text())["response"]["body"]["skill"]
    sharing = json.loads((run / ("A-sharing-" + profile + ".json")).read_text())["response"]["body"]
    source = run / ("assets-" + profile) / asset["instructions_file"]
    if (metadata.get("owner_id") != principal_id or metadata.get("source") != "user"
            or metadata.get("visibility") != "private" or metadata.get("mode") != "text"
            or metadata.get("name") != asset["name"] or metadata.get("scripts")
            or metadata.get("needs_credentials") or metadata.get("shared_with_count") != 0
            or sharing.get("skill_id") != metadata.get("skill_id") or sharing.get("scope") != "private"
            or sharing.get("members") != [] or metadata.get("instructions") != source.read_text()
            or runtime.sha256_file(source) != asset["instructions_sha256"]
            or type(metadata.get("version")) is not int or metadata["version"] < 1):
        raise ValueError("catalogue private owner/sharing/body/version mismatch")
    return {"skill_id": metadata["skill_id"], "skill_version": str(metadata["version"]),
            "skill_hash": asset["instructions_sha256"], "owner_id": principal_id}


def reused_catalogue_identity(run: Path, profile: str, asset: dict[str, Any], principal_id: str) -> dict[str, Any]:
    """Tie a fresh private readback to a prior run's immutable creation receipt."""
    identity = catalogue_identity(run, profile, asset, principal_id)
    for name in ("prior-create-" + profile + ".json", "prior-retain-" + profile + ".json"):
        receipt = json.loads((run / name).read_text())
        previous = receipt.get("response", {}).get("body", {})
        skill = previous.get("skill", {})
        from .schema import text_hash
        if (receipt.get("response", {}).get("status") not in {200, 201}
                or skill.get("skill_id") != identity["skill_id"]
                or skill.get("name") != asset["name"]
                or skill.get("owner_id") != principal_id
                or skill.get("visibility") != "private"
                or str(skill.get("version")) != identity["skill_version"]
                or text_hash(skill.get("instructions", "")) != identity["skill_hash"]):
            raise ValueError("reused Skill changed since its prior immutable creation/readback")
    return {**identity, "reuse_origin_verified": True}


def skill_result(value: Any) -> dict[str, Any] | None:
    """Decode the observed citations-prefix + JSON response, without executing text."""
    if isinstance(value, dict): return value
    if not isinstance(value, str): return None
    start = value.find("{")
    if start < 0: return None
    try:
        result, end = json.JSONDecoder().raw_decode(value[start:])
        if value[start + end:].strip() or not isinstance(result, dict): return None
        return result
    except ValueError:
        return None


def verify_runtime_identity(event: dict[str, Any], root: Path, case: dict[str, Any]) -> dict[str, Any]:
    """Join runtime name/body to the independently checked catalogue id/version.

    The observed runtime version is a separate namespace. Never label its numeric
    value as the API catalogue version, or claim the tool returned a catalogue id.
    """
    mapping = event.get("identity_resolution", {})
    if mapping.get("method") != "catalogue-name-content-join":
        raise ValueError("explicit runtime/catalogue identity resolution required")
    snapshot = read_ref(root, mapping["runtime_result_ref"])
    if snapshot.get("upstream_session_id") != case["session_id"] or snapshot.get("request_id") != event["request_id"]:
        raise ValueError("runtime source belongs to another native session/turn")
    calls = [t for t in snapshot.get("tool_events", []) if t.get("event_type") == "tool_call"
             and t.get("tool_name") == "skill_read" and t.get("tool_call_id") == event["tool_call_id"]
             and t.get("request_id") == event["request_id"]]
    reads = [t for t in snapshot.get("tool_events", []) if t.get("event_type") == "tool_result"
             and t.get("tool_name") == "skill_read" and t.get("tool_call_id") == event["tool_call_id"]
             and t.get("request_id") == event["request_id"] and t.get("status") == "success"]
    if len(calls) != 1 or len(reads) != 1 or calls[0].get("tool_input", {}).get("skill_name") != case["resource_name"]:
        raise ValueError("unique matching actual Skill invocation/read required")
    body = skill_result(reads[0].get("tool_result"))
    from .schema import text_hash
    if (not body or body.get("status") != "ok" or body.get("name") != case["resource_name"]
            or body.get("source") != "user" or body.get("mode") != "text"
            or body.get("resource") != "skill" or type(body.get("version")) is not int
            or body.get("ref") != f"skill:{case['resource_name']}:v{body.get('version')}"
            or body.get("resource_id") != case["resource_name"]
            or text_hash(body.get("instructions", "")) != case["skill_hash"]
            or event.get("runtime_version") != body.get("version")):
        raise ValueError("runtime Skill name/body/version evidence mismatch")
    if event["kind"] == "skill-content-read" and event.get("content") != body["instructions"]:
        raise ValueError("normalized body differs from actual runtime instructions")
    attempt = read_ref(root, mapping["target_attempt_ref"])
    if (attempt.get("operation_id") != "target:" + ":".join(case[k] for k in ("case_id", "model_profile", "variant"))
            or attempt.get("outcome") != "completed"):
        raise ValueError("completed matching target window required")
    import datetime as dt
    submitted = dt.datetime.fromisoformat(attempt["submitted_at"])
    completed = submitted + dt.timedelta(seconds=attempt["elapsed_s"])
    for key in ("before_catalogue_ref", "after_catalogue_ref"):
        receipt = read_ref(root, mapping[key])
        metadata = receipt.get("response", {}).get("body", {}).get("skill", {})
        if (receipt.get("request", {}).get("method") != "GET" or receipt.get("response", {}).get("status") != 200
                or receipt["request"].get("path") != "/api/skills/" + quote(case["skill_id"], safe="")
                or metadata.get("skill_id") != case["skill_id"] or metadata.get("name") != body["name"]
                or metadata.get("owner_id") != case["session_id"].split(":")[1]
                or str(metadata.get("version")) != case["skill_version"] or metadata.get("source") != "user"
                or metadata.get("visibility") != "private" or metadata.get("shared_with_count") != 0
                or text_hash(metadata.get("instructions", "")) != case["skill_hash"]):
            raise ValueError("catalogue before/after identity or body drift")
        observed = dt.datetime.fromisoformat(receipt["observed_at"])
        if ((key == "before_catalogue_ref" and observed >= submitted)
                or (key == "after_catalogue_ref" and observed <= completed)):
            raise ValueError("catalogue readbacks do not surround the target window")
    return {"method": mapping["method"], "catalogue_id": case["skill_id"],
            "catalogue_version": case["skill_version"], "runtime_name": body["name"],
            "runtime_version": body["version"], "runtime_ref": body.get("ref"),
            "catalogue_id_returned_by_runtime": False}


def execute_case(root: Path, run: Path, case_id: str) -> dict[str, Any]:
    """One approved case, fixed task, guarded output, local actual-result snapshot."""
    from .evidence import read_rows
    from .runner import call_bound_case
    from dataclasses import asdict
    cases = [c for c in read_rows(run / "case-registry.jsonl") if c["case_id"] == case_id]
    if len(cases) != 1: raise ValueError("unique prepared case required")
    case = cases[0]
    def factory(settings):
        from dotenv import load_dotenv
        from shim.genius_service import GeniusService, ShimConfig
        load_dotenv(root / ".env", override=True)
        service = GeniusService(replace(ShimConfig.from_env(), **settings, hard_timeout_s=300,
                                       token_refresh_margin_s=0, trace_raw_events=True))
        complete = service.complete
        def capture(request):
            answer, result = complete(request)
            runtime.write_json(run / ("result-" + case_id.removeprefix("notes-") + ".json"), asdict(result))
            return answer, result
        service.complete = capture
        return service
    return call_bound_case(root, run, tuple(case[k] for k in ("case_id", "model_profile", "variant")), factory)
