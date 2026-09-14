"""OpenAI-compatible shim for the Genius Chat web agent."""

from __future__ import annotations

import argparse
import base64
import fcntl
from dataclasses import dataclass, field, replace
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
import os
from pathlib import Path
import re
import ssl
import threading
import time
from typing import Any, Callable, Iterable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import uuid4

import httpx
import httpcore
from dotenv import load_dotenv
import yaml


LOGGER = logging.getLogger(__name__)
TRACE_LOG_LOCK = threading.Lock()
TERMINAL_STATUSES = {
    "cancelled",
    "complete",
    "completed",
    "done",
    "error",
    "failed",
    "finished",
    "stopped",
    "success",
}
FAILURE_STATUSES = {"cancelled", "error", "failed", "stopped"}
SENSITIVE_KEY_PARTS = (
    "authorization",
    "cookie",
    "password",
    "secret",
    "token",
)
SESSION_METADATA_KEYS = ("session_id", "agent_session_id", "agent_id")
HIGH_RISK_TOOL_NAMES = {
    "append_file",
    "batch_execute",
    "delete_file",
    "edit_file",
    "execute_python_code",
    "execute_shell_command",
    "execute_skill_script",
    "extract_archive",
    "init_project_schema",
    "move_file",
    "promote_to_dataset",
    "promote_to_deliverable",
    "register_project_dataset",
    "run_sql_update",
    "write_file",
}
CAMPAIGN_HEADER_FIELDS = {
    "X-Genius-Run-Id": "run_id",
    "X-Genius-Group-Id": "group_id",
    "X-Genius-Plugin-Id": "plugin_id",
    "X-ChemSec-Campaign-Id": "campaign_id",
    "X-ChemSec-Manifest-Hash": "manifest_hash",
    "X-ChemSec-Stage": "stage",
    "X-ChemSec-Source": "source",
    "X-ChemSec-Sample-Id": "sample_id",
    "X-ChemSec-Attempt": "attempt",
    "X-ChemSec-Request-Id": "local_request_id",
}


class GeniusError(RuntimeError):
    """Base exception for a classified Genius shim failure."""

    status = HTTPStatus.BAD_GATEWAY
    code = "genius_upstream_error"
    error_type = "upstream_error"

    def __init__(
        self,
        message: str,
        *,
        trace_summary: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(sanitize_text(message))
        self.trace_summary = trace_summary


class GeniusAuthenticationError(GeniusError):
    status = HTTPStatus.BAD_GATEWAY
    code = "genius_authentication_failed"
    error_type = "authentication_error"


class GeniusCompatibilityError(GeniusError):
    code = "genius_protocol_incompatible"
    error_type = "upstream_protocol_error"


class GeniusTimeoutError(GeniusError):
    status = HTTPStatus.GATEWAY_TIMEOUT
    code = "genius_timeout"
    error_type = "timeout_error"


class GeniusRejectedError(GeniusError):
    code = "genius_upstream_rejected"
    error_type = "provider_rejection"


class GeniusTerminalFailureError(GeniusError):
    code = "genius_terminal_failed"
    error_type = "upstream_error"


class GeniusHumanInputRequiredError(GeniusError):
    status = HTTPStatus.CONFLICT
    code = "genius_human_input_required"
    error_type = "human_input_required"


class GeniusHighRiskApprovalError(GeniusHumanInputRequiredError):
    code = "genius_high_risk_approval_blocked"


class GeniusApprovalProtocolError(GeniusCompatibilityError):
    code = "genius_approval_protocol_unverified"


class _RetryableUpstreamError(GeniusError):
    pass


def _env_flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off"}


def _coerce_text_content(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        return ""

    parts: list[str] = []
    for item in content:
        if not isinstance(item, dict):
            continue
        item_type = str(item.get("type") or "unknown")
        text = item.get("text")
        if item_type in {"text", "input_text", "output_text"} and isinstance(
            text, str
        ):
            parts.append(text)
        else:
            parts.append(f"[{item_type}]")
    return "\n".join(part for part in parts if part).strip()


def normalize_messages(messages: Any) -> list[dict[str, str]]:
    if not isinstance(messages, list):
        raise ValueError("Request must include a non-empty 'messages' list.")
    normalized: list[dict[str, str]] = []
    for item in messages:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "user").strip().lower()
        content = _coerce_text_content(item.get("content"))
        if not content:
            continue
        normalized.append({"role": role, "content": content})
    if not normalized:
        raise ValueError("No user-visible text could be extracted from the request.")
    return normalized


def serialize_conversation(messages: list[dict[str, str]]) -> str:
    if len(messages) == 1 and messages[0]["role"] == "user":
        return messages[0]["content"]
    transcript = "\n\n".join(
        f"{message['role'].upper()}:\n{message['content']}" for message in messages
    )
    return "\n\n".join(
        [
            "The following is the complete conversation transcript so far.",
            transcript,
            (
                "Continue as the assistant and respond only to the latest user "
                "message, using earlier turns as context."
            ),
        ]
    )


def _messages_are_prefix(
    prefix: list[dict[str, str]],
    messages: list[dict[str, str]],
) -> bool:
    return len(prefix) <= len(messages) and messages[: len(prefix)] == prefix


def _latest_user_text(messages: list[dict[str, str]]) -> str:
    for message in reversed(messages):
        if message["role"] == "user":
            return message["content"]
    return messages[-1]["content"]


def _metadata_string(request: dict[str, Any], *keys: str) -> str | None:
    metadata = request.get("metadata")
    containers = [metadata if isinstance(metadata, dict) else {}, request]
    for key in keys:
        for container in containers:
            value = container.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def request_session_id(request: dict[str, Any]) -> str | None:
    return _metadata_string(request, *SESSION_METADATA_KEYS)


def campaign_context(request: dict[str, Any]) -> dict[str, str]:
    metadata = request.get("metadata")
    campaign = metadata.get("campaign") if isinstance(metadata, dict) else None
    if not isinstance(campaign, dict):
        return {}
    return {
        str(key): str(value)
        for key, value in campaign.items()
        if value is not None and str(value).strip()
    }


def high_risk_tool_names(tool_events: Iterable[dict[str, Any]]) -> list[str]:
    return sorted(
        {
            str(event.get("tool_name"))
            for event in tool_events
            if event.get("tool_name") in HIGH_RISK_TOOL_NAMES
        }
    )


HUMAN_INPUT_STATES = {
    "approval_required",
    "awaiting_approval",
    "awaiting_confirmation",
    "awaiting_input",
    "awaiting_user",
    "awaiting_user_input",
    "confirmation_required",
    "human_input_required",
    "input_required",
    "needs_confirmation",
    "needs_user_input",
    "pending_approval",
    "requires_approval",
    "requires_confirmation",
    "requires_input",
    "waiting_for_input",
    "waiting_for_user",
    "waiting_for_user_input",
}
HUMAN_INPUT_EVENT_TYPES = {
    "approval_request",
    "ask_user",
    "confirmation_request",
    "human_input",
    "human_input_request",
    "request_clarification",
    "request_user_input",
    "user_input_request",
}


APPROVAL_POLICY_REQUIRED_FIELDS = (
    "run_id",
    "session_id",
    "tool",
    "action_id",
    "resource",
)
APPROVAL_PROTOCOL_REQUIRED_FIELDS = (
    "endpoint",
    "method",
    "payload",
    "success_statuses",
    "continuation",
    "verified",
    "evidence_id",
)


@dataclass(frozen=True)
class ApprovalPolicyRule:
    run_id: str
    session_id: str
    tool: str
    action_id: str
    resource: str

    def matches(
        self,
        *,
        run_id: str | None,
        session_id: str | None,
        tool: str | None,
        action_id: str | None,
        resource: str | None,
    ) -> bool:
        return (
            self.run_id == run_id
            and self.session_id == session_id
            and self.tool == tool
            and self.action_id == action_id
            and self.resource == resource
        )

    @classmethod
    def from_mapping(cls, value: Any) -> "ApprovalPolicyRule":
        if not isinstance(value, dict):
            raise ValueError("approval policy rule must be an object")
        fields: dict[str, str] = {}
        for name in APPROVAL_POLICY_REQUIRED_FIELDS:
            item = value.get(name)
            if not isinstance(item, str) or not item.strip():
                raise ValueError(f"approval policy rule field {name!r} is required")
            fields[name] = item.strip()
        return cls(**fields)


@dataclass(frozen=True)
class ApprovalProtocol:
    endpoint: str
    method: str
    payload: dict[str, Any]
    success_statuses: tuple[int, ...]
    continuation: dict[str, Any]
    verified: bool
    evidence_id: str
    response: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, value: Any) -> "ApprovalProtocol":
        if not isinstance(value, dict):
            raise ValueError("approval protocol must be an object")
        missing = [
            name for name in APPROVAL_PROTOCOL_REQUIRED_FIELDS if name not in value
        ]
        if missing:
            raise ValueError(
                "approval protocol missing fields: " + ", ".join(sorted(missing))
            )
        endpoint = value["endpoint"]
        method = value["method"]
        payload = value["payload"]
        statuses = value["success_statuses"]
        continuation = value["continuation"]
        verified = value["verified"]
        evidence_id = value["evidence_id"]
        if not isinstance(endpoint, str) or not endpoint.startswith("/"):
            raise ValueError("approval protocol endpoint must be an absolute path")
        if not isinstance(method, str) or method.upper() not in {"POST", "PUT"}:
            raise ValueError("approval protocol method must be POST or PUT")
        if not isinstance(payload, dict):
            raise ValueError("approval protocol payload must be an object")
        if not isinstance(statuses, list) or not statuses:
            raise ValueError("approval protocol success_statuses must be a list")
        parsed_statuses: list[int] = []
        for status in statuses:
            if not isinstance(status, int) or not 200 <= status < 300:
                raise ValueError("approval protocol success_statuses must be 2xx")
            parsed_statuses.append(status)
        if not isinstance(continuation, dict):
            raise ValueError("approval protocol continuation must be an object")
        mode = continuation.get("mode")
        if mode != "persisted_messages":
            raise ValueError("approval continuation mode must be persisted_messages")
        for field_name in ("poll_interval_s", "timeout_s"):
            number = continuation.get(field_name)
            if not isinstance(number, (int, float)) or number <= 0:
                raise ValueError(
                    f"approval continuation {field_name} must be positive"
                )
        if verified is not True:
            raise ValueError("approval protocol must be explicitly verified")
        if not isinstance(evidence_id, str) or not evidence_id.strip():
            raise ValueError("approval protocol evidence_id is required")
        response = value.get("response", {})
        if not isinstance(response, dict):
            raise ValueError("approval protocol response must be an object")
        return cls(
            endpoint=endpoint,
            method=method.upper(),
            payload=dict(payload),
            success_statuses=tuple(parsed_statuses),
            continuation=dict(continuation),
            verified=True,
            evidence_id=evidence_id.strip(),
            response=dict(response),
        )


@dataclass(frozen=True)
class ApprovalPolicy:
    rules: tuple[ApprovalPolicyRule, ...] = ()
    protocol: ApprovalProtocol | None = None
    valid: bool = False
    reason: str = "not_configured"

    @classmethod
    def disabled(cls, reason: str) -> "ApprovalPolicy":
        return cls(reason=reason)


@dataclass(frozen=True)
class ApprovalCandidate:
    event_id: str | None
    action_id: str | None
    request_id: str | None
    session_id: str | None
    run_id: str | None
    tool: str | None
    resource: str | None
    prompt: str | None
    event_types: tuple[str, ...]
    states: tuple[str, ...]
    trace: dict[str, Any]

    @classmethod
    def from_event(cls, event: dict[str, Any]) -> "ApprovalCandidate | None":
        containers = _nested_dicts(event)
        for container in list(containers):
            for key in ("approval", "human_input", "interaction", "prompt"):
                nested = container.get(key)
                if isinstance(nested, dict):
                    containers.append(nested)

        tool_result_payload: dict[str, Any] | None = None
        for container in containers:
            for key in ("tool_result", "result", "toolResult"):
                parsed = _parse_tool_result(container.get(key))
                if parsed is not None and (
                    parsed.get("confirmation_id")
                    or parsed.get("surface_kind") == "confirmation_required"
                    or parsed.get("status") == "awaiting_user_confirmation"
                ):
                    tool_result_payload = parsed
                    break
            if tool_result_payload is not None:
                break

        event_types = tuple(
            sorted(
                {
                    _normalized_state(container.get(key))
                    for container in containers
                    for key in ("event", "type", "kind", "interaction_type")
                }
                - {""}
            )
        )
        states = tuple(
            sorted(
                {
                    _normalized_state(container.get(key))
                    for container in containers
                    for key in ("status", "state")
                }
                - {""}
            )
        )
        explicit_flag = any(
            container.get(key) is True
            for container in containers
            for key in (
                "approval_required",
                "awaiting_user",
                "awaiting_user_input",
                "human_input_required",
                "input_required",
                "requires_approval",
                "requires_confirmation",
                "requires_user_input",
            )
        )
        if not (
            set(event_types).intersection(HUMAN_INPUT_EVENT_TYPES)
            or set(states).intersection(HUMAN_INPUT_STATES)
            or explicit_flag
            or tool_result_payload is not None
        ):
            return None

        if tool_result_payload is not None:
            confirmation_id = tool_result_payload.get("confirmation_id")
            if not isinstance(confirmation_id, str) or not confirmation_id.strip():
                return None
            tool = _first_string(containers, ("tool", "tool_name", "name"))
            resource = _approval_resource(containers, [])
            prompt = tool_result_payload.get("message")
            if not isinstance(prompt, str):
                prompt = None
            trace = sanitize_value(
                {
                    "event_types": list(event_types),
                    "states": list(states),
                    "tool_names": [tool] if tool else [],
                    "high_risk_tool_names": [tool]
                    if tool in HIGH_RISK_TOOL_NAMES
                    else [],
                    "event_id": confirmation_id,
                    "action_id": confirmation_id,
                    "request_id": _first_string(containers, ("request_id",)),
                    "session_id": _first_string(
                        containers, ("session_id", "agent_session_id")
                    ),
                    "run_id": _first_string(
                        containers, ("run_id", "campaign_id", "sample_id")
                    ),
                    "tool": tool,
                    "resource": resource,
                    "prompt": prompt,
                    "confirmation_id": confirmation_id,
                    "surface_kind": tool_result_payload.get("surface_kind"),
                    "blocking": tool_result_payload.get("blocking"),
                }
            )
            return cls(
                event_id=confirmation_id,
                action_id=confirmation_id,
                request_id=_first_string(containers, ("request_id",)),
                session_id=_first_string(
                    containers, ("session_id", "agent_session_id")
                ),
                run_id=_first_string(
                    containers, ("run_id", "campaign_id", "sample_id")
                ),
                tool=tool,
                resource=resource,
                prompt=prompt,
                event_types=event_types,
                states=states,
                trace=trace,
            )

        actions = [
            action
            for container in containers
            for action in (
                container.get("actions")
                if isinstance(container.get("actions"), list)
                else []
            )
            if isinstance(action, dict)
        ]
        tool_names = tuple(
            sorted(
                {
                    str(value)
                    for container in [*containers, *actions]
                    for key in ("tool_name", "name")
                    if isinstance((value := container.get(key)), str) and value
                }
            )
        )
        high_risk = tuple(
            sorted(set(tool_names).intersection(HIGH_RISK_TOOL_NAMES))
        )
        event_id = _first_string(
            containers, ("id", "event_id", "interaction_id", "approval_id")
        )
        action_id = _first_string(
            [*containers, *actions],
            ("action_id", "tool_call_id", "call_id", "id"),
        )
        request_id = _first_string(containers, ("request_id",))
        session_id = _first_string(containers, ("session_id", "agent_session_id"))
        run_id = _first_string(containers, ("run_id", "campaign_id", "sample_id"))
        tool = next(iter(tool_names), None)
        resource = _approval_resource(containers, actions)
        prompt = _first_string(containers, ("question", "prompt", "message"))
        tool_input = next(
            (
                container.get("tool_input")
                for container in [*containers, *actions]
                if container.get("tool_input") is not None
            ),
            None,
        )
        trace = sanitize_value(
            {
                "event_types": list(event_types),
                "states": list(states),
                "tool_names": list(tool_names),
                "high_risk_tool_names": list(high_risk),
                "event_id": event_id,
                "action_id": action_id,
                "request_id": request_id,
                "session_id": session_id,
                "run_id": run_id,
                "tool": tool,
                "resource": resource,
                "prompt": prompt,
                "tool_input": tool_input,
            }
        )
        return cls(
            event_id=event_id,
            action_id=action_id,
            request_id=request_id,
            session_id=session_id,
            run_id=run_id,
            tool=tool,
            resource=resource,
            prompt=prompt,
            event_types=event_types,
            states=states,
            trace=trace,
        )


def _first_string(
    containers: list[dict[str, Any]],
    keys: tuple[str, ...],
) -> str | None:
    for container in containers:
        for key in keys:
            value = container.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def _approval_resource(
    containers: list[dict[str, Any]],
    actions: list[dict[str, Any]],
) -> str | None:
    for container in [*containers, *actions]:
        for key in (
            "resource",
            "path",
            "file_path",
            "target_path",
            "team_id",
            "project_id",
            "node_id",
            "url",
            "command",
            "query",
        ):
            value = container.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        tool_input = container.get("tool_input")
        if isinstance(tool_input, dict):
            for key in (
                "resource",
                "path",
                "file_path",
                "target_path",
                "team_id",
                "project_id",
                "node_id",
                "url",
                "command",
                "query",
            ):
                value = tool_input.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
        elif isinstance(tool_input, str) and tool_input.strip():
            return tool_input.strip()
    return None


def _parse_tool_result(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def load_approval_policy(path: str) -> ApprovalPolicy:
    if not path:
        return ApprovalPolicy.disabled("approval policy file is not configured")
    policy_path = Path(path)
    try:
        raw = policy_path.read_text(encoding="utf-8")
        document = yaml.safe_load(raw)
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        return ApprovalPolicy.disabled(f"approval policy file is unreadable: {exc}")
    if not isinstance(document, dict):
        return ApprovalPolicy.disabled("approval policy document is not an object")
    rules_value = document.get("rules")
    if not isinstance(rules_value, list) or not rules_value:
        return ApprovalPolicy.disabled("approval policy rules are empty")
    try:
        rules = tuple(ApprovalPolicyRule.from_mapping(item) for item in rules_value)
        protocol = ApprovalProtocol.from_mapping(document.get("protocol"))
    except (ValueError, TypeError) as exc:
        return ApprovalPolicy.disabled(str(exc))
    return ApprovalPolicy(
        rules=rules,
        protocol=protocol,
        valid=True,
        reason="configured",
    )


def _normalized_state(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return re.sub(r"[\s-]+", "_", value.strip().lower())


def human_input_request(event: dict[str, Any]) -> dict[str, Any] | None:
    """Return sanitized evidence when an event explicitly waits for a user."""
    candidate = ApprovalCandidate.from_event(event)
    return candidate.trace if candidate is not None else None


def normalize_bearer_token(value: str) -> str:
    token = value.strip()
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
    return token


def jwt_expiry(token: str) -> float | None:
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        decoded = json.loads(base64.urlsafe_b64decode(payload).decode("utf-8"))
        expiry = decoded.get("exp")
        return float(expiry) if isinstance(expiry, (int, float)) else None
    except (IndexError, ValueError, TypeError, json.JSONDecodeError):
        return None


def redact_url(value: str) -> str:
    try:
        parts = urlsplit(value)
    except ValueError:
        return value
    if not parts.scheme or not parts.netloc:
        return value
    query = []
    for key, item in parse_qsl(parts.query, keep_blank_values=True):
        if any(part in key.lower() for part in SENSITIVE_KEY_PARTS):
            query.append((key, "<redacted>"))
        else:
            query.append((key, item))
    return urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment)
    )


_BEARER_RE = re.compile(r"(?i)bearer\s+[A-Za-z0-9._~+\-/]+=*")
_TOKEN_QUERY_RE = re.compile(r"(?i)([?&](?:[^=&]*token[^=&]*)=)[^&#\s]+")


def sanitize_text(value: str, limit: int = 4000) -> str:
    sanitized = _BEARER_RE.sub("Bearer <redacted>", str(value))
    sanitized = _TOKEN_QUERY_RE.sub(r"\1<redacted>", sanitized)
    return sanitized[:limit]


def sanitize_value(value: Any, *, depth: int = 0) -> Any:
    if depth > 6:
        return "<truncated>"
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if any(part in key_text.lower() for part in SENSITIVE_KEY_PARTS):
                result[key_text] = "<redacted>"
            else:
                result[key_text] = sanitize_value(item, depth=depth + 1)
        return result
    if isinstance(value, list):
        return [sanitize_value(item, depth=depth + 1) for item in value[:100]]
    if isinstance(value, str):
        return sanitize_text(redact_url(value))
    return value


def _token_count(text: str) -> int:
    return max(1, len(text) // 4) if text else 0


def build_chat_completion_response(
    model: str,
    prompt: str,
    result: "GeniusResult",
) -> dict[str, Any]:
    prompt_tokens = _token_count(prompt)
    completion_tokens = _token_count(result.content)
    return {
        "id": f"chatcmpl-{uuid4().hex}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": result.content},
                "finish_reason": result.finish_reason,
            }
        ],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
        "genius_trace": result.trace,
    }


def make_chat_completion_chunk(
    stream_state: dict[str, Any],
    delta: dict[str, Any],
    finish_reason: str | None,
    trace: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": stream_state["id"],
        "object": "chat.completion.chunk",
        "created": stream_state["created"],
        "model": stream_state["model"],
        "choices": [
            {
                "index": 0,
                "delta": delta,
                "finish_reason": finish_reason,
            }
        ],
    }
    if trace is not None:
        payload["genius_trace"] = trace
    return payload


def openai_error(
    message: str,
    *,
    error_type: str,
    code: str,
    trace_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "error": {
            "message": sanitize_text(message),
            "type": error_type,
            "code": code,
        }
    }
    if trace_summary is not None:
        payload["genius_trace_summary"] = sanitize_value(trace_summary)
    return payload


@dataclass(frozen=True)
class ShimConfig:
    host: str = "127.0.0.1"
    port: int = 4030
    downstream_api_key: str = "sk-local-test"
    upstream_base_url: str = ""
    upstream_connect_host: str | None = None
    upstream_authorization: str = ""
    model_profile: str = "default"
    organization_id: str = ""
    upstream_timeout_s: float = 180.0
    hard_timeout_s: float | None = 180.0
    upstream_retry_attempts: int = 1
    upstream_retry_wait_s: float = 1.0
    session_ttl_s: float = 1800.0
    token_refresh_margin_s: float = 300.0
    trace_jsonl_path: str = "logs/genius_trace.jsonl"
    lifecycle_jsonl_path: str = "logs/genius_session_lifecycle.jsonl"
    trace_raw_events: bool = False
    approval_policy_file: str = ""

    @classmethod
    def from_env(cls) -> "ShimConfig":
        hard_timeout = os.getenv("GENIUS_HARD_TIMEOUT_S", "180").strip()
        return cls(
            host=os.getenv("GENIUS_SHIM_HOST", "127.0.0.1"),
            port=int(os.getenv("GENIUS_SHIM_PORT", "4030")),
            downstream_api_key=os.getenv("GENIUS_WEB_API_KEY", "sk-local-test"),
            upstream_base_url=os.getenv("GENIUS_UPSTREAM_BASE_URL", "").rstrip("/"),
            upstream_connect_host=(
                os.getenv("GENIUS_CONNECT_HOST", "").strip() or None
            ),
            upstream_authorization=os.getenv("GENIUS_AUTHORIZATION", ""),
            model_profile=os.getenv("GENIUS_MODEL_PROFILE", "default").strip(),
            organization_id=os.getenv("GENIUS_ORG_ID", "").strip(),
            upstream_timeout_s=float(
                os.getenv("GENIUS_UPSTREAM_TIMEOUT_S", "180")
            ),
            hard_timeout_s=float(hard_timeout) if hard_timeout else None,
            upstream_retry_attempts=max(
                0, int(os.getenv("GENIUS_UPSTREAM_RETRY_ATTEMPTS", "1"))
            ),
            upstream_retry_wait_s=max(
                0.0, float(os.getenv("GENIUS_UPSTREAM_RETRY_WAIT_S", "1"))
            ),
            session_ttl_s=max(
                1.0, float(os.getenv("GENIUS_SESSION_TTL_S", "1800"))
            ),
            token_refresh_margin_s=max(
                0.0, float(os.getenv("GENIUS_TOKEN_REFRESH_MARGIN_S", "300"))
            ),
            trace_jsonl_path=os.getenv(
                "GENIUS_TRACE_JSONL", "logs/genius_trace.jsonl"
            ).strip(),
            lifecycle_jsonl_path=os.getenv(
                "GENIUS_LIFECYCLE_JSONL", "logs/genius_session_lifecycle.jsonl"
            ).strip(),
            trace_raw_events=_env_flag("GENIUS_TRACE_RAW_EVENTS", False),
            approval_policy_file=os.getenv(
                "GENIUS_APPROVAL_POLICY_FILE", ""
            ).strip(),
        )


class CredentialManager:
    def __init__(
        self,
        token: str,
        base_url: str,
        client: httpx.Client,
        *,
        refresh_margin_s: float = 300.0,
    ) -> None:
        self._token = normalize_bearer_token(token)
        self._base_url = base_url.rstrip("/")
        self._client = client
        self._refresh_margin_s = refresh_margin_s
        self._lock = threading.Lock()

    @property
    def configured(self) -> bool:
        return bool(self._token and self._base_url)

    @property
    def expires_at(self) -> float | None:
        return jwt_expiry(self._token)

    @property
    def raw_token(self) -> str:
        return self._token

    def _is_expiring(self) -> bool:
        expiry = self.expires_at
        return expiry is not None and expiry <= time.time() + self._refresh_margin_s

    def authorization(self) -> str:
        if not self.configured:
            raise GeniusAuthenticationError(
                "Genius upstream credentials are not configured."
            )
        if self._is_expiring():
            self.refresh(stale_token=self._token, force=True)
        return f"Bearer {self._token}"

    def refresh(self, *, stale_token: str | None = None, force: bool = False) -> str:
        with self._lock:
            if stale_token and stale_token != self._token:
                return self._token
            if not force and not self._is_expiring():
                return self._token
            if not self.configured:
                raise GeniusAuthenticationError(
                    "Genius upstream credentials are not configured."
                )
            try:
                response = self._client.post(
                    f"{self._base_url}/api/auth/refresh",
                    headers={"Content-Type": "application/json"},
                    json={"token": self._token},
                )
            except httpx.HTTPError as exc:
                raise GeniusAuthenticationError(
                    f"Genius token refresh failed: {exc.__class__.__name__}."
                ) from exc
            if response.status_code >= 400:
                raise GeniusAuthenticationError(
                    f"Genius token refresh was rejected with status "
                    f"{response.status_code}."
                )
            try:
                payload = response.json()
            except ValueError as exc:
                raise GeniusAuthenticationError(
                    "Genius token refresh returned invalid JSON."
                ) from exc
            replacement = payload.get("token") if isinstance(payload, dict) else None
            if not isinstance(replacement, str) or not replacement.strip():
                raise GeniusAuthenticationError(
                    "Genius token refresh returned no replacement token."
                )
            self._token = normalize_bearer_token(replacement)
            return self._token

    def refresh_after_401(self, stale_token: str) -> str:
        return self.refresh(stale_token=stale_token, force=True)


class StaticResolveBackend(httpcore.NetworkBackend):
    """Resolve one logical TLS host through a configured connect host."""

    def __init__(
        self,
        logical_host: str,
        connect_host: str,
        *,
        delegate: httpcore.NetworkBackend | None = None,
    ) -> None:
        self.logical_host = logical_host
        self.connect_host = connect_host
        self.delegate = delegate or httpcore.SyncBackend()

    def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Iterable[tuple[Any, ...]] | None = None,
    ) -> httpcore.NetworkStream:
        target_host = self.connect_host if host == self.logical_host else host
        return self.delegate.connect_tcp(
            target_host,
            port,
            timeout=timeout,
            local_address=local_address,
            socket_options=socket_options,
        )

    def connect_unix_socket(
        self,
        path: str,
        timeout: float | None = None,
        socket_options: Iterable[tuple[Any, ...]] | None = None,
    ) -> httpcore.NetworkStream:
        return self.delegate.connect_unix_socket(
            path,
            timeout=timeout,
            socket_options=socket_options,
        )

    def sleep(self, seconds: float) -> None:
        self.delegate.sleep(seconds)


class StaticResolveHTTPTransport(httpx.HTTPTransport):
    """HTTP transport that preserves TLS SNI while overriding DNS resolution."""

    def __init__(self, logical_host: str, connect_host: str) -> None:
        super().__init__()
        self._pool.close()
        self._pool = httpcore.ConnectionPool(
            ssl_context=ssl.create_default_context(),
            network_backend=StaticResolveBackend(logical_host, connect_host),
        )


@dataclass
class SessionState:
    upstream_session_id: str
    history: list[dict[str, str]] = field(default_factory=list)
    updated_at: float = field(default_factory=time.time)


@dataclass(frozen=True)
class PreparedSession:
    local_session_id: str | None
    upstream_session_id: str
    query: str
    reused: bool


class SessionStore:
    def __init__(self, ttl_s: float = 1800.0) -> None:
        self._ttl_s = ttl_s
        self._states: dict[str, SessionState] = {}
        self._lock = threading.RLock()

    def _cleanup(self, now: float) -> None:
        expired = [
            key
            for key, state in self._states.items()
            if now - state.updated_at > self._ttl_s
        ]
        for key in expired:
            self._states.pop(key, None)

    def prepare(
        self,
        local_session_id: str | None,
        messages: list[dict[str, str]],
        create_session: Callable[[], str],
    ) -> PreparedSession:
        if not local_session_id:
            return PreparedSession(
                local_session_id=None,
                upstream_session_id=create_session(),
                query=serialize_conversation(messages),
                reused=False,
            )

        with self._lock:
            now = time.time()
            self._cleanup(now)
            state = self._states.get(local_session_id)
            if state and _messages_are_prefix(state.history, messages):
                appended = messages[len(state.history) :]
                user_messages = [
                    item["content"] for item in appended if item["role"] == "user"
                ]
                if user_messages:
                    state.updated_at = now
                    return PreparedSession(
                        local_session_id=local_session_id,
                        upstream_session_id=state.upstream_session_id,
                        query="\n\n".join(user_messages),
                        reused=True,
                    )

            upstream_session_id = create_session()
            self._states[local_session_id] = SessionState(
                upstream_session_id=upstream_session_id,
                updated_at=now,
            )
            return PreparedSession(
                local_session_id=local_session_id,
                upstream_session_id=upstream_session_id,
                query=serialize_conversation(messages),
                reused=False,
            )

    def complete(
        self,
        local_session_id: str | None,
        messages: list[dict[str, str]],
        assistant_content: str,
    ) -> None:
        if not local_session_id:
            return
        with self._lock:
            state = self._states.get(local_session_id)
            if state is None:
                return
            state.history = [dict(item) for item in messages]
            if assistant_content:
                state.history.append(
                    {"role": "assistant", "content": assistant_content}
                )
            state.updated_at = time.time()

    def invalidate(self, local_session_id: str | None) -> None:
        if not local_session_id:
            return
        with self._lock:
            self._states.pop(local_session_id, None)


def _append_stream_text(current: str, value: Any) -> str:
    if not isinstance(value, str) or not value:
        return current
    if value == current or current.endswith(value):
        return current
    if value.startswith(current):
        return value
    return current + value


def _nested_dicts(event: dict[str, Any]) -> list[dict[str, Any]]:
    containers = [event]
    for key in ("data", "delta", "message", "payload", "result"):
        value = event.get(key)
        if isinstance(value, dict):
            containers.append(value)
    return containers


def summarize_genius_event(event: dict[str, Any]) -> dict[str, Any]:
    containers = _nested_dicts(event)
    event_type = next(
        (
            str(value)
            for container in containers
            for key in ("event", "type", "kind")
            if isinstance((value := container.get(key)), str) and value
        ),
        "unknown",
    )
    if event_type == "unknown":
        if any("thinking_round" in container for container in containers):
            event_type = "reasoning_delta"
        elif any(
            isinstance(container.get("text"), str) and "seq" in container
            for container in containers
        ):
            event_type = "content_delta"
        elif any(isinstance(container.get("success"), bool) for container in containers):
            event_type = (
                "completed"
                if any(container.get("success") is True for container in containers)
                else "failed"
            )
        elif any(isinstance(container.get("status"), str) for container in containers):
            event_type = "status"
    status = next(
        (
            str(value)
            for container in containers
            if isinstance((value := container.get("status")), str) and value
        ),
        None,
    )
    if status is None and event_type in {"completed", "failed"}:
        status = event_type
    request_id = next(
        (
            str(value)
            for container in containers
            if isinstance((value := container.get("request_id")), str) and value
        ),
        None,
    )
    tool_name = next(
        (
            str(value)
            for container in containers
            for key in ("tool_name", "name")
            if isinstance((value := container.get(key)), str)
            and value
            and ("tool" in event_type.lower() or key == "tool_name")
        ),
        None,
    )
    tool_input = next(
        (
            container.get("tool_input")
            for container in containers
            if container.get("tool_input") is not None
        ),
        None,
    )
    tool_result = next(
        (
            container.get("tool_result")
            for container in containers
            if container.get("tool_result") is not None
        ),
        None,
    )
    summary: dict[str, Any] = {
        "event_type": event_type,
        "status": status,
        "request_id": request_id,
        "tool_name": tool_name,
    }
    if tool_input is not None:
        summary["tool_input"] = sanitize_value(tool_input)
    if tool_result is not None:
        summary["tool_result"] = sanitize_value(tool_result)
    return {key: value for key, value in summary.items() if value is not None}


@dataclass
class GeniusResult:
    content: str
    thinking_content: str = ""
    finish_reason: str = "stop"
    terminal_status: str | None = None
    request_id: str | None = None
    event_count: int = 0
    meaningful_event_count: int = 0
    tool_events: list[dict[str, Any]] = field(default_factory=list)
    event_summaries: list[dict[str, Any]] = field(default_factory=list)
    upstream_session_id: str | None = None
    campaign: dict[str, str] = field(default_factory=dict)
    turn_settings: dict[str, Any] = field(default_factory=dict)
    reconciled_from_persisted: bool = False
    human_input_request: dict[str, Any] | None = None
    approval_candidate: ApprovalCandidate | None = None
    approval_decision: dict[str, Any] | None = None
    approval_protocol_response: dict[str, Any] | None = None
    approval_continuation: dict[str, Any] | None = None

    @property
    def trace(self) -> dict[str, Any]:
        outcome = "completed"
        if self.terminal_status in FAILURE_STATUSES:
            outcome = f"upstream_{self.terminal_status}"
        elif self.tool_events:
            outcome = "completed_with_tool"
        risky_tools = high_risk_tool_names(self.tool_events)
        if self.approval_continuation is not None:
            outcome = (
                f"upstream_{self.terminal_status}"
                if self.terminal_status in FAILURE_STATUSES
                else "completed_after_approval"
            )
        elif self.human_input_request is not None:
            risky_tools = sorted(
                set(risky_tools).union(
                    self.human_input_request.get("high_risk_tool_names", [])
                )
            )
            outcome = (
                "high_risk_approval_blocked"
                if risky_tools
                else "deferred_for_input"
            )
        else:
            risky_tools = high_risk_tool_names(self.tool_events)
        if self.approval_candidate is not None:
            risky_tools = sorted(
                set(risky_tools).union(
                    [self.approval_candidate.tool]
                    if self.approval_candidate.tool
                    else []
                )
            )
        return {
            "upstream_session_id": self.upstream_session_id,
            "request_id": self.request_id,
            "terminal_status": self.terminal_status,
            "event_count": self.event_count,
            "meaningful_event_count": self.meaningful_event_count,
            "thinking_content": self.thinking_content or None,
            "tool_events": self.tool_events,
            "high_risk_tool_names": risky_tools,
            "campaign_pause_required": bool(
                (risky_tools or self.approval_candidate is not None)
                and self.approval_continuation is None
            ),
            "human_input_request": self.human_input_request,
            "event_summaries": self.event_summaries,
            "outcome": outcome,
            "campaign": self.campaign,
            "turn_settings": self.turn_settings,
            "reconciled_from_persisted": self.reconciled_from_persisted,
            "approval_decision": self.approval_decision,
            "approval_protocol_response": self.approval_protocol_response,
            "approval_continuation": self.approval_continuation,
        }


class GeniusEventCollector:
    def __init__(self) -> None:
        self.content = ""
        self.thinking_content = ""
        self.terminal_status: str | None = None
        self.request_id: str | None = None
        self.event_count = 0
        self.meaningful_event_count = 0
        self.tool_events: list[dict[str, Any]] = []
        self.event_summaries: list[dict[str, Any]] = []
        self.human_input_request: dict[str, Any] | None = None
        self.approval_candidate: ApprovalCandidate | None = None
        self._last_tool_inputs: dict[str, dict[str, Any] | str] = {}

    def accept(self, event: dict[str, Any]) -> None:
        self.event_count += 1
        containers = _nested_dicts(event)
        summary = summarize_genius_event(event)
        if len(self.event_summaries) < 100:
            self.event_summaries.append(summary)

        event_type = str(summary.get("event_type") or "").lower()
        status = str(summary.get("status") or "").lower()
        if not status and event_type in TERMINAL_STATUSES:
            status = event_type
        if status in TERMINAL_STATUSES:
            self.terminal_status = status
        request_id = summary.get("request_id")
        if isinstance(request_id, str):
            self.request_id = request_id

        visible_values: list[str] = []
        thinking_values: list[str] = []
        for container in containers:
            for key in ("thinking", "thinking_content", "reasoning", "reasoning_content"):
                value = container.get(key)
                if isinstance(value, str):
                    thinking_values.append(value)
            delta = container.get("delta")
            if isinstance(delta, str):
                if "think" in event_type or "reason" in event_type:
                    thinking_values.append(delta)
                else:
                    visible_values.append(delta)
            elif isinstance(delta, dict):
                text = delta.get("text") or delta.get("content")
                if isinstance(text, str):
                    if "think" in event_type or "reason" in event_type:
                        thinking_values.append(text)
                    else:
                        visible_values.append(text)
            for key in ("text", "content"):
                value = container.get(key)
                if not isinstance(value, str):
                    continue
                role = str(container.get("role") or "").lower()
                if (
                    "think" in event_type
                    or "reason" in event_type
                    or "thinking_round" in container
                ):
                    thinking_values.append(value)
                elif role in {"assistant", "agent"} or any(
                    marker in event_type
                    for marker in ("answer", "assistant", "content", "message", "text")
                ):
                    visible_values.append(value)
            reply = container.get("reply")
            if isinstance(reply, str) and reply:
                visible_values.append(reply)

        before_content = self.content
        before_thinking = self.thinking_content
        for value in visible_values:
            self.content = _append_stream_text(self.content, value)
        for value in thinking_values:
            self.thinking_content = _append_stream_text(
                self.thinking_content, value
            )

        actions = [
            action
            for container in containers
            for action in (
                container.get("actions")
                if isinstance(container.get("actions"), list)
                else []
            )
            if isinstance(action, dict)
        ]
        is_tool = "tool" in event_type or bool(actions) or any(
            any(key in container for key in ("tool_name", "tool_input", "tool_result"))
            for container in containers
        )
        if is_tool:
            if actions:
                self.tool_events.extend(
                    sanitize_value(
                        {
                            "event_type": "action",
                            "tool_name": action.get("tool_name")
                            or action.get("name")
                            or action.get("type"),
                            "tool_input": action.get("tool_input")
                            or action.get("input"),
                            "tool_result": action.get("tool_result")
                            or action.get("result"),
                            "status": action.get("status"),
                        }
                    )
                    for action in actions
                )
            else:
                self.tool_events.append(summary)

        candidate = ApprovalCandidate.from_event(event)
        tool_name = next(
            (
                str(value)
                for container in containers
                for key in ("tool", "tool_name", "name")
                if isinstance((value := container.get(key)), str) and value
            ),
            None,
        )
        tool_input = next(
            (
                container.get("tool_input")
                or container.get("input")
                for container in containers
                if container.get("tool_input") is not None
                or container.get("input") is not None
            ),
            None,
        )
        if tool_name and tool_input is not None:
            self._last_tool_inputs[tool_name] = tool_input  # type: ignore[assignment]
        if candidate is not None:
            self.human_input_request = candidate.trace
            if (
                candidate.trace.get("confirmation_id")
                or "approval_request" in candidate.event_types
                or any(
                    state
                    in {
                        "approval_required",
                        "awaiting_approval",
                        "awaiting_user_confirmation",
                        "pending_approval",
                        "requires_approval",
                    }
                    for state in candidate.states
                )
            ):
                if candidate.resource is None and candidate.tool:
                    last_input = self._last_tool_inputs.get(candidate.tool)
                    if last_input is not None:
                        synthetic_container = {"tool_input": last_input}
                        resource = _approval_resource([synthetic_container], [])
                        if resource:
                            candidate = replace(candidate, resource=resource)
                self.approval_candidate = candidate

        if (
            self.content != before_content
            or self.thinking_content != before_thinking
            or is_tool
            or bool(status and status not in {"idle", "queued"})
        ):
            self.meaningful_event_count += 1

    def result(self, *, upstream_session_id: str) -> GeniusResult:
        finish_reason = "stop"
        if self.terminal_status in FAILURE_STATUSES:
            finish_reason = "error"
        return GeniusResult(
            content=self.content.strip(),
            thinking_content=self.thinking_content.strip(),
            finish_reason=finish_reason,
            terminal_status=self.terminal_status,
            request_id=self.request_id,
            event_count=self.event_count,
            meaningful_event_count=self.meaningful_event_count,
            tool_events=self.tool_events,
            event_summaries=self.event_summaries,
            upstream_session_id=upstream_session_id,
            human_input_request=self.human_input_request,
            approval_candidate=self.approval_candidate,
        )


class GeniusStreamParser:
    def __init__(
        self,
        collector: GeniusEventCollector,
        *,
        on_event: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self._collector = collector
        self._on_event = on_event
        self._buffer = ""

    def feed(self, chunk: str) -> None:
        if not chunk:
            return
        self._buffer += chunk.replace("\r\n", "\n")
        while "\n\n" in self._buffer:
            block, self._buffer = self._buffer.split("\n\n", 1)
            self._parse_block(block)

    def finish(self) -> None:
        if self._buffer.strip():
            self._parse_block(self._buffer)
        self._buffer = ""

    def _parse_block(self, block: str) -> None:
        payloads = [
            line[5:].strip()
            for line in block.splitlines()
            if line.startswith("data:")
        ]
        if not payloads:
            payloads = [line.strip() for line in block.splitlines() if line.strip()]
        for payload in payloads:
            if payload in {"", "[DONE]"} or payload.startswith(":"):
                continue
            try:
                parsed = json.loads(payload)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                self._collector.accept(parsed)
                if self._on_event:
                    self._on_event(parsed)
            elif isinstance(parsed, list):
                for item in parsed:
                    if isinstance(item, dict):
                        self._collector.accept(item)
                        if self._on_event:
                            self._on_event(item)


def collect_genius_events(events: Iterable[dict[str, Any]]) -> GeniusResult:
    collector = GeniusEventCollector()
    for event in events:
        collector.accept(event)
    return collector.result(upstream_session_id="test-session")


def trace_summary(
    result: GeniusResult | None,
    *,
    outcome: str,
) -> dict[str, Any]:
    if result is None:
        return {
            "event_count": 0,
            "meaningful_event_count": 0,
            "tool_events_count": 0,
            "observed_tool_names": [],
            "outcome": outcome,
        }
    names = sorted(
        {
            str(event["tool_name"])
            for event in result.tool_events
            if event.get("tool_name")
        }
    )
    return {
        "event_count": result.event_count,
        "meaningful_event_count": result.meaningful_event_count,
        "tool_events_count": len(result.tool_events),
        "observed_tool_names": names,
        "terminal_status": result.terminal_status,
        "request_id": result.request_id,
        "outcome": outcome,
    }


class TraceRecorder:
    def __init__(self, path: str, *, raw_events: bool = False) -> None:
        self.path = path
        self.raw_events = raw_events

    def write(
        self,
        kind: str,
        payload: dict[str, Any],
        *,
        durable: bool = False,
    ) -> None:
        if not self.path:
            return
        row = {
            "timestamp": time.time(),
            "kind": kind,
            **sanitize_value(payload),
        }
        path = Path(self.path)
        path.parent.mkdir(parents=True, exist_ok=True)
        encoded = json.dumps(row, ensure_ascii=False, sort_keys=True)
        with TRACE_LOG_LOCK:
            with path.open("a", encoding="utf-8") as trace_file:
                fcntl.flock(trace_file.fileno(), fcntl.LOCK_EX)
                try:
                    trace_file.write(encoded + "\n")
                    trace_file.flush()
                    if durable:
                        os.fsync(trace_file.fileno())
                finally:
                    fcntl.flock(trace_file.fileno(), fcntl.LOCK_UN)

    def event(
        self,
        event: dict[str, Any],
        *,
        context: dict[str, str] | None = None,
    ) -> None:
        summary = summarize_genius_event(event)
        if self.raw_events:
            summary["raw"] = sanitize_value(event)
        self.write("genius_event", {"summary": summary, **(context or {})})


class GeniusService:
    def __init__(
        self,
        config: ShimConfig,
        *,
        client: httpx.Client | None = None,
        session_store: SessionStore | None = None,
    ) -> None:
        self.config = config
        timeout_s = config.upstream_timeout_s
        if config.hard_timeout_s and config.hard_timeout_s > 0:
            timeout_s = min(timeout_s, config.hard_timeout_s)
        self._owns_client = client is None
        transport: httpx.BaseTransport | None = None
        if client is None and config.upstream_connect_host:
            logical_host = urlsplit(config.upstream_base_url).hostname
            if not logical_host:
                raise ValueError("GENIUS_UPSTREAM_BASE_URL must include a host.")
            transport = StaticResolveHTTPTransport(
                logical_host, config.upstream_connect_host
            )
        self._client = client or httpx.Client(
            timeout=timeout_s,
            transport=transport,
        )
        self.credentials = CredentialManager(
            config.upstream_authorization,
            config.upstream_base_url,
            self._client,
            refresh_margin_s=config.token_refresh_margin_s,
        )
        self.sessions = session_store or SessionStore(config.session_ttl_s)
        self.recorder = TraceRecorder(
            config.trace_jsonl_path,
            raw_events=config.trace_raw_events,
        )
        self.lifecycle_recorder = TraceRecorder(config.lifecycle_jsonl_path)
        self.approval_policy = load_approval_policy(config.approval_policy_file)

    @property
    def api_key(self) -> str:
        return self.config.downstream_api_key

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": self.credentials.authorization(),
            "Content-Type": "application/json",
        }

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        stale_token = self.credentials.raw_token
        for auth_attempt in range(2):
            try:
                response = self._client.request(
                    method,
                    f"{self.config.upstream_base_url}{path}",
                    headers=self._headers(),
                    json=json_body,
                )
            except httpx.TimeoutException as exc:
                raise GeniusTimeoutError(
                    f"Genius {path} request timed out."
                ) from exc
            except httpx.HTTPError as exc:
                raise _RetryableUpstreamError(
                    f"Genius {path} transport failed: {exc.__class__.__name__}."
                ) from exc
            if response.status_code != 401:
                break
            if auth_attempt == 1:
                raise GeniusAuthenticationError(
                    "Genius rejected the refreshed upstream credential."
                )
            self.credentials.refresh_after_401(stale_token)
            stale_token = self.credentials.raw_token
        if response.status_code in {429} or response.status_code >= 500:
            raise _RetryableUpstreamError(
                f"Genius {path} returned status {response.status_code}."
            )
        if response.status_code >= 400:
            raise GeniusRejectedError(
                f"Genius {path} rejected the request with status "
                f"{response.status_code}."
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise GeniusCompatibilityError(
                f"Genius {path} returned invalid JSON."
            ) from exc
        if not isinstance(payload, dict):
            raise GeniusCompatibilityError(
                f"Genius {path} returned a non-object JSON response."
            )
        return payload

    def _approval_context(
        self,
        candidate: ApprovalCandidate,
        payload: dict[str, Any],
        context: dict[str, str],
    ) -> dict[str, str]:
        return {
            "run_id": candidate.run_id
            or context.get("run_id")
            or context.get("campaign_id")
            or "",
            "session_id": candidate.session_id
            or str(payload.get("session_id") or ""),
            "tool": candidate.tool or "",
            "action_id": candidate.action_id or "",
            "resource": candidate.resource or "",
            "request_id": candidate.request_id or "",
            "event_id": candidate.event_id or "",
            "answer_message": (
                f"[answering: questionId={candidate.event_id or ''}]\n"
                + (f"Question: {candidate.prompt or ''}\n" if candidate.prompt else "")
                + "Answer:\nYes, go ahead"
            ),
        }

    def _approval_decision(
        self,
        candidate: ApprovalCandidate,
        payload: dict[str, Any],
        context: dict[str, str],
    ) -> tuple[ApprovalPolicyRule | None, str]:
        if not self.approval_policy.valid:
            return None, self.approval_policy.reason
        approval_context = self._approval_context(candidate, payload, context)
        missing = [
            key
            for key in APPROVAL_POLICY_REQUIRED_FIELDS
            if not approval_context.get(key)
        ]
        if missing:
            return None, "missing fields: " + ", ".join(sorted(missing))
        assert self.approval_policy.protocol is not None
        for rule in self.approval_policy.rules:
            if rule.matches(
                run_id=approval_context["run_id"],
                session_id=approval_context["session_id"],
                tool=approval_context["tool"],
                action_id=approval_context["action_id"],
                resource=approval_context["resource"],
            ):
                return rule, "approved"
        return None, "no exact approval policy rule match"

    def _render_protocol_value(
        self,
        value: Any,
        approval_context: dict[str, str],
    ) -> Any:
        if isinstance(value, dict):
            return {
                key: self._render_protocol_value(item, approval_context)
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [
                self._render_protocol_value(item, approval_context)
                for item in value
            ]
        if not isinstance(value, str):
            return value
        rendered = value
        for key, item in approval_context.items():
            rendered = rendered.replace("{{" + key + "}}", item)
            rendered = rendered.replace("{" + key + "}", item)
        leftovers = re.findall(r"\{\{[^{}]+\}\}|\{[^{}]+\}", rendered)
        if leftovers:
            raise GeniusApprovalProtocolError(
                "approval protocol payload contains unknown placeholders: "
                + ", ".join(sorted(set(leftovers)))
            )
        return rendered

    def _submit_approval(
        self,
        protocol: ApprovalProtocol,
        approval_context: dict[str, str],
    ) -> GeniusResult | dict[str, Any]:
        endpoint = self._render_protocol_value(
            protocol.endpoint, approval_context
        )
        if not isinstance(endpoint, str) or not endpoint.startswith("/"):
            raise GeniusApprovalProtocolError(
                "approval protocol endpoint did not render to an absolute path."
            )
        if endpoint == "/chat/stream":
            answer_payload: dict[str, Any] = {
                "message": approval_context["answer_message"],
                "session_id": approval_context["session_id"],
                "session_type": "general",
                "client_message_id": f"client-{uuid4().hex}",
                "assistant_client_message_id": f"assistant-{uuid4().hex}",
            }
            return self._stream_chat_once(
                answer_payload,
                context={
                    key: value
                    for key, value in approval_context.items()
                    if key != "answer_message"
                },
            )
        payload = self._render_protocol_value(
            protocol.payload, approval_context
        )
        if not isinstance(payload, dict):
            raise GeniusApprovalProtocolError(
                "approval protocol payload did not render to an object."
            )
        stale_token = self.credentials.raw_token
        for auth_attempt in range(2):
            response = self._client.request(
                protocol.method,
                f"{self.config.upstream_base_url}{endpoint}",
                headers=self._headers(),
                json=payload,
            )
            if response.status_code != 401:
                break
            if auth_attempt == 1:
                raise GeniusAuthenticationError(
                    "Genius rejected the refreshed approval credential."
                )
            self.credentials.refresh_after_401(stale_token)
            stale_token = self.credentials.raw_token
        if response.status_code not in protocol.success_statuses:
            raise GeniusRejectedError(
                "Genius approval submission returned status "
                f"{response.status_code}."
            )
        try:
            document = response.json()
        except ValueError as exc:
            raise GeniusApprovalProtocolError(
                "Genius approval submission returned invalid JSON."
            ) from exc
        if not isinstance(document, dict):
            raise GeniusApprovalProtocolError(
                "Genius approval submission returned a non-object JSON response."
            )
        for key, expected in protocol.response.items():
            if document.get(key) != expected:
                raise GeniusApprovalProtocolError(
                    f"Genius approval response field {key!r} did not match the "
                    "verified protocol."
                )
        return document

    def _continue_after_approval(
        self,
        result: GeniusResult,
        assistant_client_message_id: str,
        *,
        protocol: ApprovalProtocol,
    ) -> GeniusResult:
        continuation = protocol.continuation
        timeout_s = float(continuation["timeout_s"])
        interval_s = float(continuation["poll_interval_s"])
        started = time.monotonic()
        attempts = 0
        last_error: GeniusError | None = None
        while time.monotonic() - started < timeout_s:
            attempts += 1
            result.human_input_request = None
            try:
                continued = self._reconcile_result(
                    result,
                    assistant_client_message_id,
                    force_persisted=True,
                    ignore_human_input=True,
                )
                if continued.content or continued.terminal_status:
                    continued.approval_continuation = {
                        "mode": continuation["mode"],
                        "attempts": attempts,
                        "elapsed_s": round(time.monotonic() - started, 3),
                    }
                    return continued
            except GeniusError as exc:
                last_error = exc
            time.sleep(interval_s)
        raise GeniusTimeoutError(
            "Genius approval continuation timed out.",
            trace_summary=trace_summary(
                result,
                outcome="approval_continuation_timeout",
            ),
        ) from last_error

    def _process_approval(
        self,
        result: GeniusResult,
        payload: dict[str, Any],
        context: dict[str, str],
        assistant_client_message_id: str,
    ) -> GeniusResult:
        candidate = result.approval_candidate
        if candidate is None:
            raise GeniusHighRiskApprovalError(
                "Genius requested approval without readable approval evidence.",
                trace_summary=result.trace,
            )
        self.approval_policy = load_approval_policy(
            self.config.approval_policy_file
        )
        base_context = {
            **context,
            "upstream_session_id": str(payload.get("session_id") or ""),
            "approval": candidate.trace,
        }
        self.lifecycle_recorder.write(
            "approval_observed",
            base_context,
            durable=True,
        )
        rule, decision_reason = self._approval_decision(
            candidate, payload, context
        )
        approval_context = self._approval_context(candidate, payload, context)
        result.approval_decision = {
            "decision": "approved" if rule is not None else "denied",
            "reason": decision_reason,
            **approval_context,
        }
        self.lifecycle_recorder.write(
            "approval_policy_decision",
            {**base_context, "decision": result.approval_decision["decision"]},
            durable=True,
        )
        if rule is None:
            raise GeniusHighRiskApprovalError(
                "Genius approval was denied by the local approval policy.",
                trace_summary=result.trace,
            )
        protocol = self.approval_policy.protocol
        if protocol is None or not protocol.verified:
            result.approval_decision["reason"] = "protocol_unverified"
            raise GeniusApprovalProtocolError(
                "Genius approval protocol is not verified.",
                trace_summary=result.trace,
            )
        self.lifecycle_recorder.write(
            "approval_protocol_submit",
            {
                **base_context,
                "endpoint": protocol.endpoint,
                "method": protocol.method,
                "evidence_id": protocol.evidence_id,
            },
            durable=True,
        )
        try:
            response = self._submit_approval(protocol, approval_context)
            if isinstance(response, GeniusResult):
                response.approval_decision = result.approval_decision
                response.approval_protocol_response = {
                    "mode": "chat_stream",
                    "outcome": response.trace["outcome"],
                }
                response.approval_continuation = {
                    "mode": "chat_stream",
                    "attempts": 1,
                    "elapsed_s": 0,
                }
                self.lifecycle_recorder.write(
                    "approval_protocol_response",
                    {**base_context, "response": response.approval_protocol_response},
                    durable=True,
                )
                self.lifecycle_recorder.write(
                    "approval_terminal_result",
                    {
                        **base_context,
                        "outcome": response.trace["outcome"],
                        "terminal_status": response.terminal_status,
                    },
                    durable=True,
                )
                return response
            result.approval_protocol_response = response
            self.lifecycle_recorder.write(
                "approval_protocol_response",
                {**base_context, "response": response},
                durable=True,
            )
            self.lifecycle_recorder.write(
                "approval_continuation_started",
                {
                    **base_context,
                    "mode": protocol.continuation["mode"],
                },
                durable=True,
            )
            continued = self._continue_after_approval(
                result,
                assistant_client_message_id,
                protocol=protocol,
            )
            continued.approval_decision = result.approval_decision
            continued.approval_protocol_response = result.approval_protocol_response
            self.lifecycle_recorder.write(
                "approval_terminal_result",
                {
                    **base_context,
                    "outcome": continued.trace["outcome"],
                    "terminal_status": continued.terminal_status,
                },
                durable=True,
            )
            return continued
        except GeniusError as exc:
            self.lifecycle_recorder.write(
                "approval_failed",
                {
                    **base_context,
                    "error_type": exc.error_type,
                    "code": exc.code,
                },
                durable=True,
            )
            raise

    def create_session(
        self,
        *,
        context: dict[str, str] | None = None,
        canonical: bool = False,
    ) -> str:
        attempts = 1 if canonical else max(1, self.config.upstream_retry_attempts + 1)
        payload: dict[str, Any] | None = None
        for attempt in range(1, attempts + 1):
            try:
                payload = self._request_json(
                    "POST",
                    "/api/sessions",
                    json_body={"session_type": "general"},
                )
                break
            except (_RetryableUpstreamError, GeniusTimeoutError):
                if attempt >= attempts:
                    raise
                if self.config.upstream_retry_wait_s:
                    time.sleep(self.config.upstream_retry_wait_s)
        assert payload is not None
        session_id = payload.get("session_id") or payload.get("id")
        if not session_id and isinstance(payload.get("session"), dict):
            session_id = payload["session"].get("session_id") or payload[
                "session"
            ].get("id")
        if not isinstance(session_id, str) or not session_id:
            raise GeniusCompatibilityError(
                "Genius session creation returned no session identifier."
            )
        self.lifecycle_recorder.write(
            "session_created",
            {**(context or {}), "upstream_session_id": session_id},
            durable=True,
        )
        return session_id

    def resolve_model_profile(self, profile_name: str = "default") -> dict[str, Any]:
        if not self.config.organization_id:
            raise GeniusCompatibilityError(
                "GENIUS_ORG_ID is required for model-profile preflight."
            )
        payload = self._request_json(
            "GET",
            f"/api/orgs/{self.config.organization_id}/models",
        )
        models = payload.get("models")
        if not isinstance(models, list):
            raise GeniusCompatibilityError(
                "Genius model-profile response did not contain a models list."
            )
        for model in models:
            if not isinstance(model, dict):
                continue
            if (model.get("id") or model.get("profile_name")) == profile_name:
                return sanitize_value(model)
        raise GeniusCompatibilityError(
            f"Genius model profile {profile_name!r} was not found."
        )

    def _cleanup_request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
    ) -> tuple[int, dict[str, Any] | None]:
        stale_token = self.credentials.raw_token
        for auth_attempt in range(2):
            response = self._client.request(
                method,
                f"{self.config.upstream_base_url}{path}",
                headers=self._headers(),
                json=json_body,
            )
            if response.status_code != 401:
                break
            if auth_attempt == 1:
                raise GeniusAuthenticationError(
                    "Genius rejected the refreshed cleanup credential."
                )
            self.credentials.refresh_after_401(stale_token)
            stale_token = self.credentials.raw_token
        if response.status_code == 404:
            return 404, None
        if response.status_code in {429} or response.status_code >= 500:
            raise _RetryableUpstreamError(
                f"Genius cleanup returned status {response.status_code}."
            )
        if response.status_code >= 400:
            raise GeniusRejectedError(
                f"Genius cleanup rejected the request with status "
                f"{response.status_code}."
            )
        if not response.content:
            return response.status_code, None
        try:
            parsed = response.json()
        except ValueError:
            return response.status_code, None
        return response.status_code, parsed if isinstance(parsed, dict) else None

    def batch_delete_sessions(
        self, session_ids: list[str]
    ) -> tuple[int, dict[str, Any] | None]:
        if not session_ids:
            return 200, {"session_ids": []}
        return self._cleanup_request(
            "POST",
            "/api/sessions/batch-delete",
            json_body={"session_ids": session_ids},
        )

    def delete_session(self, session_id: str) -> int:
        status, _payload = self._cleanup_request(
            "DELETE", f"/api/sessions/{session_id}"
        )
        return status

    def session_exists(self, session_id: str) -> bool:
        return session_id in self.list_session_ids()

    def list_session_ids(self, *, page_size: int = 200) -> set[str]:
        session_ids: set[str] = set()
        offset = 0
        while True:
            payload = self._request_json(
                "GET",
                f"/api/sessions?limit={page_size}&offset={offset}&session_type=general",
            )
            sessions = payload.get("sessions")
            if not isinstance(sessions, list):
                raise GeniusCompatibilityError(
                    "Genius session list returned no sessions array."
                )
            for session in sessions:
                if not isinstance(session, dict):
                    continue
                session_id = session.get("id") or session.get("session_id")
                if isinstance(session_id, str) and session_id:
                    session_ids.add(session_id)
            if not payload.get("has_more") or not sessions:
                break
            offset += len(sessions)
        return session_ids

    def _chat_payload(
        self,
        request: dict[str, Any],
        prepared: PreparedSession,
        *,
        client_message_id: str,
        assistant_client_message_id: str,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "message": prepared.query,
            "session_id": prepared.upstream_session_id,
            "session_type": "general",
            "client_message_id": client_message_id,
            "assistant_client_message_id": assistant_client_message_id,
        }
        model_profile = _metadata_string(request, "model_profile")
        model_profile = model_profile or self.config.model_profile
        if model_profile:
            payload["model_profile"] = model_profile
        thinking = request.get("thinking")
        if isinstance(thinking, str) and thinking:
            payload["thinking"] = thinking
        context = campaign_context(request)
        reasoning_effort = request.get("reasoning_effort")
        if context:
            model_profile = "default"
            payload["model_profile"] = model_profile
            reasoning_effort = "xhigh"
        if isinstance(reasoning_effort, str) and reasoning_effort:
            payload["reasoning_effort"] = reasoning_effort
        context_limit = request.get("context_limit")
        if isinstance(context_limit, int) and context_limit > 0:
            payload["context_limit"] = context_limit
        return payload

    def _stream_chat_once(
        self,
        payload: dict[str, Any],
        *,
        context: dict[str, str] | None = None,
    ) -> GeniusResult:
        collector = GeniusEventCollector()
        parser = GeniusStreamParser(
            collector,
            on_event=lambda event: self.recorder.event(event, context=context),
        )
        stale_token = self.credentials.raw_token
        try:
            with self._client.stream(
                "POST",
                f"{self.config.upstream_base_url}/chat/stream",
                headers=self._headers(),
                json=payload,
            ) as response:
                if response.status_code == 401:
                    raise GeniusAuthenticationError(
                        "Genius rejected the upstream credential."
                    )
                if response.status_code in {429} or response.status_code >= 500:
                    raise _RetryableUpstreamError(
                        "Genius chat stream returned status "
                        f"{response.status_code}."
                    )
                if response.status_code >= 400:
                    raise GeniusRejectedError(
                        "Genius chat stream rejected the request with status "
                        f"{response.status_code}."
                    )
                for chunk in response.iter_text():
                    parser.feed(chunk)
                    if collector.human_input_request is not None:
                        break
                parser.finish()
        except GeniusAuthenticationError:
            if collector.meaningful_event_count:
                result = collector.result(
                    upstream_session_id=str(payload["session_id"])
                )
                raise GeniusAuthenticationError(
                    "Genius authentication failed after generation activity.",
                    trace_summary=trace_summary(
                        result, outcome="authentication_failure_after_activity"
                    ),
                )
            self.credentials.refresh_after_401(stale_token)
            raise _RetryableUpstreamError(
                "Genius credential refreshed; chat request can be retried."
            )
        except httpx.TimeoutException as exc:
            result = collector.result(
                upstream_session_id=str(payload["session_id"])
            )
            if result.human_input_request is not None:
                return result
            if collector.meaningful_event_count:
                try:
                    result.reconciled_from_persisted = True
                    result.terminal_status = "reconciled"
                    return self._reconcile_result(
                        result,
                        str(payload["assistant_client_message_id"]),
                        force_persisted=True,
                    )
                except GeniusError:
                    pass
                raise GeniusTimeoutError(
                    "Genius chat stream timed out after generation activity.",
                    trace_summary=trace_summary(
                        result, outcome="timeout_after_activity"
                    ),
                ) from exc
            raise _RetryableUpstreamError(
                "Genius chat stream timed out before generation activity."
            ) from exc
        except httpx.HTTPError as exc:
            result = collector.result(
                upstream_session_id=str(payload["session_id"])
            )
            if collector.meaningful_event_count:
                try:
                    result.reconciled_from_persisted = True
                    result.terminal_status = "reconciled"
                    return self._reconcile_result(
                        result,
                        str(payload["assistant_client_message_id"]),
                        force_persisted=True,
                    )
                except GeniusError:
                    pass
                raise GeniusError(
                    "Genius chat transport failed after generation activity.",
                    trace_summary=trace_summary(
                        result, outcome="transport_failure_after_activity"
                    ),
                ) from exc
            raise _RetryableUpstreamError(
                f"Genius chat transport failed: {exc.__class__.__name__}."
            ) from exc
        result = collector.result(upstream_session_id=str(payload["session_id"]))
        if result.terminal_status in FAILURE_STATUSES:
            raise GeniusTerminalFailureError(
                f"Genius chat ended with status {result.terminal_status}.",
                trace_summary=trace_summary(
                    result, outcome=f"upstream_{result.terminal_status}"
                ),
            )
        return result

    def _persisted_session_messages(
        self,
        upstream_session_id: str,
    ) -> list[dict[str, Any]]:
        payload = self._request_json(
            "GET",
            f"/api/sessions/{upstream_session_id}/messages?limit=200",
        )
        messages = payload.get("messages")
        if not isinstance(messages, list):
            return []
        return [item for item in messages if isinstance(item, dict)]

    def _persisted_assistant_message(
        self,
        upstream_session_id: str,
        assistant_client_message_id: str,
    ) -> dict[str, Any] | None:
        messages = self._persisted_session_messages(upstream_session_id)
        candidates = [
            item
            for item in messages
            if isinstance(item, dict) and item.get("role") == "assistant"
        ]
        exact = [
            item
            for item in candidates
            if item.get("client_message_id") == assistant_client_message_id
        ]
        return (exact or candidates)[-1] if (exact or candidates) else None

    def _reconcile_result(
        self,
        result: GeniusResult,
        assistant_client_message_id: str,
        *,
        force_persisted: bool = False,
        ignore_human_input: bool = False,
    ) -> GeniusResult:
        if result.human_input_request is not None and not ignore_human_input:
            return result
        if result.content and not force_persisted:
            return result
        persisted = self._persisted_session_messages(
            result.upstream_session_id or ""
        )
        if not ignore_human_input:
            for item in persisted:
                interaction = human_input_request(item)
                if interaction is not None:
                    result.human_input_request = interaction
                    return result
        candidates = [
            item for item in persisted if item.get("role") == "assistant"
        ]
        exact = [
            item
            for item in candidates
            if item.get("client_message_id") == assistant_client_message_id
        ]
        message = (exact or candidates)[-1] if (exact or candidates) else None
        if not message:
            raise GeniusCompatibilityError(
                "Genius completed without readable assistant content.",
                trace_summary=trace_summary(
                    result, outcome="completed_without_readable_content"
                ),
            )
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise GeniusCompatibilityError(
                "Genius persisted no readable assistant content.",
                trace_summary=trace_summary(
                    result, outcome="persisted_content_missing"
                ),
            )
        result.content = content.strip()
        thinking = message.get("thinking_content")
        if isinstance(thinking, str) and thinking.strip():
            result.thinking_content = thinking.strip()
        if isinstance(message.get("request_id"), str):
            result.request_id = message["request_id"]
        known_tool_ids = {
            str(event.get("tool_call_id"))
            for event in result.tool_events
            if event.get("tool_call_id")
        }
        for item in persisted:
            if item.get("role") != "tool" and not any(
                item.get(key) is not None
                for key in ("tool_name", "tool_input", "tool_result")
            ):
                continue
            summary = summarize_genius_event(item)
            tool_call_id = str(item.get("tool_call_id") or "")
            if tool_call_id and tool_call_id in known_tool_ids:
                continue
            result.tool_events.append(summary)
            if tool_call_id:
                known_tool_ids.add(tool_call_id)
        return result

    def complete(self, request: dict[str, Any]) -> tuple[str, GeniusResult]:
        messages = normalize_messages(request.get("messages"))
        local_session_id = request_session_id(request)
        context = campaign_context(request)
        canonical = bool(context.get("campaign_id"))
        prepared = self.sessions.prepare(
            local_session_id,
            messages,
            lambda: self.create_session(context=context, canonical=canonical),
        )
        client_message_id = f"client-{uuid4().hex}"
        assistant_client_message_id = f"assistant-{uuid4().hex}"
        payload = self._chat_payload(
            request,
            prepared,
            client_message_id=client_message_id,
            assistant_client_message_id=assistant_client_message_id,
        )
        context = {
            **context,
            "local_turn_id": client_message_id,
            "upstream_session_id": prepared.upstream_session_id,
        }
        self.recorder.write(
            "user_message",
            {
                **context,
                "local_session_id": local_session_id,
                "role": "user",
                "text": _latest_user_text(messages),
                "origin": "local_shim",
            },
        )
        self.recorder.write(
            "request_started",
            {
                **context,
                "upstream_session_id": prepared.upstream_session_id,
                "local_session_id": local_session_id,
                "reused_session": prepared.reused,
            },
        )

        max_attempts = max(1, self.config.upstream_retry_attempts + 1)
        started_at = time.monotonic()
        last_error: GeniusError | None = None
        for attempt in range(1, max_attempts + 1):
            try:
                result = self._stream_chat_once(payload, context=context)
                result.campaign = dict(context)
                result.turn_settings = {
                    "model_profile": payload.get("model_profile"),
                    "thinking_enabled": payload.get("thinking") != "off",
                    "history_enabled": True,
                    "reasoning_effort": payload.get("reasoning_effort"),
                }
                approval_processed = False
                if (
                    result.approval_candidate is not None
                    and result.trace["campaign_pause_required"]
                ):
                    result = self._process_approval(
                        result,
                        payload,
                        context,
                        assistant_client_message_id,
                    )
                    approval_processed = True
                if not approval_processed and result.human_input_request is not None:
                    error_type = (
                        GeniusHighRiskApprovalError
                        if result.trace["campaign_pause_required"]
                        else GeniusHumanInputRequiredError
                    )
                    raise error_type(
                        "Genius requires human input before it can continue.",
                        trace_summary=result.trace,
                    )
                if not approval_processed:
                    result = self._reconcile_result(
                        result, assistant_client_message_id
                    )
                    if result.human_input_request is not None:
                        error_type = (
                            GeniusHighRiskApprovalError
                            if result.trace["campaign_pause_required"]
                            else GeniusHumanInputRequiredError
                        )
                        raise error_type(
                            "Genius requires human input before it can continue.",
                            trace_summary=result.trace,
                        )
            except _RetryableUpstreamError as exc:
                last_error = exc
                if attempt >= max_attempts:
                    break
                self.recorder.write(
                    "request_retry",
                    {**context, "attempt": attempt, "reason": str(exc)},
                )
                if self.config.upstream_retry_wait_s:
                    time.sleep(self.config.upstream_retry_wait_s)
                continue
            except GeniusError as exc:
                self.recorder.write(
                    "request_failed",
                    {
                        **context,
                        "attempt": attempt,
                        "error_type": exc.error_type,
                        "code": exc.code,
                        "trace_summary": exc.trace_summary,
                    },
                )
                raise

            self.sessions.complete(local_session_id, messages, result.content)
            self.recorder.write(
                "request_completed",
                {
                    **context,
                    "attempt": attempt,
                    "elapsed_s": round(time.monotonic() - started_at, 3),
                    "trace": result.trace,
                },
            )
            return serialize_conversation(messages), result

        assert last_error is not None
        self.recorder.write(
            "request_failed",
            {
                **context,
                "attempt": max_attempts,
                "error_type": last_error.error_type,
                "code": last_error.code,
            },
        )
        raise last_error


def is_authorized(header: str | None, expected_api_key: str) -> bool:
    return header == f"Bearer {expected_api_key}"


class GeniusHTTPServer(ThreadingHTTPServer):
    def __init__(self, address: tuple[str, int], service: GeniusService) -> None:
        super().__init__(address, GeniusRequestHandler)
        self.service = service


class GeniusRequestHandler(BaseHTTPRequestHandler):
    server: GeniusHTTPServer

    def log_message(self, format: str, *args: Any) -> None:
        LOGGER.info("%s - %s", self.address_string(), sanitize_text(format % args))

    def _authorized(self) -> bool:
        return is_authorized(self.headers.get("Authorization"), self.server.service.api_key)

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("Request body must be a JSON object.")
        return payload

    def _send_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status.value)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def do_GET(self) -> None:  # noqa: N802
        path = urlsplit(self.path).path
        if path == "/health":
            expiry = self.server.service.credentials.expires_at
            self._send_json(
                HTTPStatus.OK,
                {
                    "ok": True,
                    "service": "genius-openai-shim",
                    "pid": os.getpid(),
                    "credential_configured": self.server.service.credentials.configured,
                    "credential_expires_at": (
                        int(expiry) if expiry is not None else None
                    ),
                    "timestamp": int(time.time()),
                },
            )
            return
        if path == "/v1/models":
            if not self._authorized():
                self._send_json(
                    HTTPStatus.UNAUTHORIZED,
                    openai_error(
                        "Invalid local API key.",
                        error_type="authentication_error",
                        code="invalid_api_key",
                    ),
                )
                return
            self._send_json(
                HTTPStatus.OK,
                {
                    "object": "list",
                    "data": [
                        {
                            "id": "genius-agent",
                            "object": "model",
                            "created": 0,
                            "owned_by": "genius-web",
                        }
                    ],
                },
            )
            return
        self._send_json(
            HTTPStatus.NOT_FOUND,
            openai_error(
                "Not found.", error_type="invalid_request_error", code="not_found"
            ),
        )

    def do_POST(self) -> None:  # noqa: N802
        if urlsplit(self.path).path != "/v1/chat/completions":
            self._send_json(
                HTTPStatus.NOT_FOUND,
                openai_error(
                    "Not found.",
                    error_type="invalid_request_error",
                    code="not_found",
                ),
            )
            return
        if not self._authorized():
            self._send_json(
                HTTPStatus.UNAUTHORIZED,
                openai_error(
                    "Invalid local API key.",
                    error_type="authentication_error",
                    code="invalid_api_key",
                ),
            )
            return
        try:
            request = self._read_json()
            header_context = {
                field: value
                for header, field in CAMPAIGN_HEADER_FIELDS.items()
                if (value := self.headers.get(header))
            }
            if header_context:
                metadata = request.get("metadata")
                if not isinstance(metadata, dict):
                    metadata = {}
                    request["metadata"] = metadata
                metadata["campaign"] = header_context
            prompt, result = self.server.service.complete(request)
        except (ValueError, json.JSONDecodeError) as exc:
            self._send_json(
                HTTPStatus.BAD_REQUEST,
                openai_error(
                    str(exc),
                    error_type="invalid_request_error",
                    code="invalid_request",
                ),
            )
            return
        except GeniusError as exc:
            self._send_json(
                exc.status,
                openai_error(
                    str(exc),
                    error_type=exc.error_type,
                    code=exc.code,
                    trace_summary=exc.trace_summary,
                ),
            )
            return

        model = str(request.get("model") or "genius-agent")
        if request.get("stream") is True:
            stream_state = {
                "id": f"chatcmpl-{uuid4().hex}",
                "model": model,
                "created": int(time.time()),
            }
            chunks = [
                make_chat_completion_chunk(
                    stream_state, {"role": "assistant"}, None
                ),
                make_chat_completion_chunk(
                    stream_state, {"content": result.content}, None
                ),
                make_chat_completion_chunk(
                    stream_state, {}, result.finish_reason, result.trace
                ),
            ]
            self.send_response(HTTPStatus.OK.value)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache, no-transform")
            self.send_header("Connection", "close")
            self.end_headers()
            for chunk in chunks:
                encoded = json.dumps(chunk, ensure_ascii=False)
                self.wfile.write(f"data: {encoded}\n\n".encode("utf-8"))
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
            return

        self._send_json(
            HTTPStatus.OK,
            build_chat_completion_response(model, prompt, result),
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Serve Genius Chat's internal web API behind OpenAI "
            "/v1/chat/completions."
        )
    )
    parser.add_argument("--host", default=None, help="Host to bind. Defaults to env.")
    parser.add_argument("--port", type=int, default=None, help="Port to bind. Defaults to env.")
    parser.add_argument(
        "--api-key",
        default=None,
        help="Bearer token expected by the local shim. Defaults to GENIUS_WEB_API_KEY.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    # Load project-local credentials without requiring shell-specific `source`
    # commands. Existing environment variables retain precedence.
    load_dotenv(override=False)
    args = build_parser().parse_args(argv)
    base = ShimConfig.from_env()
    config = ShimConfig(
        host=args.host or base.host,
        port=args.port or base.port,
        downstream_api_key=args.api_key or base.downstream_api_key,
        upstream_base_url=base.upstream_base_url,
        upstream_connect_host=base.upstream_connect_host,
        upstream_authorization=base.upstream_authorization,
        model_profile=base.model_profile,
        organization_id=base.organization_id,
        upstream_timeout_s=base.upstream_timeout_s,
        hard_timeout_s=base.hard_timeout_s,
        upstream_retry_attempts=base.upstream_retry_attempts,
        upstream_retry_wait_s=base.upstream_retry_wait_s,
        session_ttl_s=base.session_ttl_s,
        token_refresh_margin_s=base.token_refresh_margin_s,
        trace_jsonl_path=base.trace_jsonl_path,
        lifecycle_jsonl_path=base.lifecycle_jsonl_path,
        trace_raw_events=base.trace_raw_events,
        approval_policy_file=base.approval_policy_file,
    )
    logging.basicConfig(
        level=os.getenv("GENIUS_SHIM_LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    service = GeniusService(config)
    server = GeniusHTTPServer((config.host, config.port), service)
    LOGGER.info(
        "Genius shim listening on http://%s:%s/v1/chat/completions",
        config.host,
        config.port,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    finally:
        server.server_close()
        service.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
