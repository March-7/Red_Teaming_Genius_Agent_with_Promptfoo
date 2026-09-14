"""Read-only local HTTP viewer for Genius trace artifacts."""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import parse_qs, unquote, urlparse


STATIC_ROOT = Path(__file__).resolve().parent / "static"


@dataclass(frozen=True)
class Source:
    path: Path
    kind: str
    run_id: str
    group_id: str
    plugin_id: str


def _read_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict):
                rows.append(row)
    return rows


def _string(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _category(kind: str, raw: dict[str, Any]) -> str:
    normalized = kind.lower()
    summary = raw.get("summary")
    if isinstance(summary, dict):
        event_type = _string(summary.get("event_type"))
        if event_type:
            normalized = event_type.lower()
    nested = summary.get("raw", {}) if isinstance(summary, dict) else {}
    if normalized.startswith("approval"):
        return "approval"
    if normalized in {"user", "user_message", "input_message"} or raw.get("role") == "user":
        return "user"
    if isinstance(nested, dict) and nested.get("tool"):
        return "tool"
    if normalized.startswith("session"):
        return "session"
    if normalized in {"request_completed", "request_failed"}:
        return "terminal"
    if normalized.startswith("request"):
        return "request"
    if "reasoning" in normalized or "thinking" in normalized:
        return "reasoning"
    if "content" in normalized or "answer" in normalized or "reply" in normalized:
        return "assistant"
    if "tool" in normalized or "action" in normalized:
        return "tool"
    if "oracle" in normalized:
        return "oracle"
    if "eval" in normalized:
        return "eval"
    if normalized in {"completed", "failed", "error", "timeout"}:
        return "terminal"
    return "event"


def _event_text(raw: dict[str, Any]) -> str | None:
    summary = raw.get("summary")
    if isinstance(summary, dict):
        nested = summary.get("raw")
        if isinstance(nested, dict):
            for key in ("text", "content", "message", "prompt", "question", "reply"):
                value = nested.get(key) if isinstance(nested.get(key), str) else None
                if value:
                    return value
        for key in ("text", "content", "message", "prompt", "question", "reply"):
            value = _string(summary.get(key))
            if value:
                return value
    for key in ("text", "content", "message", "prompt", "question", "reply"):
        value = _string(raw.get(key))
        if value:
            return value
    approval = raw.get("approval")
    if isinstance(approval, dict):
        value = _string(approval.get("prompt"))
        if value:
            return value
    return None


def _search_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return " ".join(_search_text(item) for item in value.values())
    if isinstance(value, list):
        return " ".join(_search_text(item) for item in value)
    return str(value)


def _normalize_event(
    source: Source,
    file_kind: str,
    line_number: int,
    raw: dict[str, Any],
) -> dict[str, Any]:
    summary = raw.get("summary") if isinstance(raw.get("summary"), dict) else {}
    nested = summary.get("raw") if isinstance(summary.get("raw"), dict) else {}
    if not nested and isinstance(raw.get("raw"), dict):
        nested = raw["raw"]
    kind = (
        _string(raw.get("kind"))
        or _string(raw.get("event_type"))
        or _string(summary.get("event_type"))
        or _string(raw.get("type"))
        or "event"
    )
    trace = raw.get("trace") or raw.get("trace_summary") or {}
    if not isinstance(trace, dict):
        trace = {}
    approval = raw.get("approval") if isinstance(raw.get("approval"), dict) else {}
    session_id = (
        _string(raw.get("upstream_session_id"))
        or _string(raw.get("session_id"))
        or _string(summary.get("session_id"))
        or _string(nested.get("session_id"))
        or _string(trace.get("upstream_session_id"))
    )
    local_session_id = _string(raw.get("local_session_id"))
    request_id = (
        _string(raw.get("request_id"))
        or _string(summary.get("request_id"))
        or _string(nested.get("request_id"))
        or _string(approval.get("request_id"))
        or _string(trace.get("request_id"))
    )
    approval = raw.get("approval") if isinstance(raw.get("approval"), dict) else {}
    confirmation_id = (
        _string(approval.get("confirmation_id"))
        or _string(raw.get("confirmation_id"))
        or _string(summary.get("confirmation_id"))
    )
    tool_name = (
        _string(raw.get("tool_name"))
        or _string(summary.get("tool_name"))
        or _string(nested.get("tool_name"))
        or _string(nested.get("tool"))
    )
    tool_input = (
        raw.get("tool_input")
        if raw.get("tool_input") is not None
        else summary.get("tool_input", nested.get("tool_input", nested.get("input") if nested.get("tool") else None))
    )
    tool_result = (
        raw.get("tool_result")
        if raw.get("tool_result") is not None
        else summary.get("tool_result", nested.get("tool_result", nested.get("result") if nested.get("tool") else None))
    )
    outcome = (
        _string(raw.get("outcome"))
        or _string(raw.get("status"))
        or _string(summary.get("status"))
        or _string(nested.get("status"))
        or _string(raw.get("result"))
        or _string(raw.get("decision"))
        or _string(trace.get("outcome"))
    )
    timestamp = raw.get("timestamp")
    if not isinstance(timestamp, (int, float)):
        timestamp = 0.0
    event_id = f"{source.kind}:{source.run_id}:{file_kind}:{line_number}"
    return {
        "event_id": event_id,
        "source_kind": source.kind,
        "source_path": str(source.path),
        "source_file": file_kind,
        "line_number": line_number,
        "run_id": source.run_id,
        "group_id": source.group_id,
        "plugin_id": source.plugin_id,
        "kind": kind,
        "category": _category(kind, raw),
        "timestamp": float(timestamp),
        "session_id": session_id,
        "local_session_id": local_session_id,
        "request_id": request_id,
        "confirmation_id": confirmation_id,
        "tool_name": tool_name,
        "tool_input": tool_input,
        "tool_result": tool_result,
        "outcome": outcome,
        "text": _event_text(raw),
        "search_text": _search_text(raw),
        "raw": raw,
    }


def _manifest_ids(run_dir: Path) -> tuple[str | None, str | None, str | None]:
    manifest_path = run_dir / "run-manifest.json"
    if not manifest_path.exists():
        return None, None, None
    try:
        manifest = _read_json(manifest_path)
    except (OSError, json.JSONDecodeError):
        return None, None, None
    if not isinstance(manifest, dict):
        return None, None, None
    return (
        _string(manifest.get("run_id")),
        _string(manifest.get("group_id")),
        _string(manifest.get("plugin_id")),
    )


def _link_trace_turns(events: list[dict[str, Any]]) -> None:
    """Recover legacy serial turn boundaries; never guess across overlapping requests."""
    pending: list[dict[str, Any]] = []
    active = 0
    overlapping = False
    for event in events:
        if event["kind"] == "request_started":
            active += 1
            overlapping = overlapping or active > 1
        if active:
            pending.append(event)
        if event["kind"] in {"request_completed", "request_failed"} and active:
            active -= 1
            if active == 0:
                sessions = {e["session_id"] for e in pending if e.get("session_id")}
                requests = {e["request_id"] for e in pending if e.get("request_id")}
                if not overlapping and len(sessions) == len(requests) == 1:
                    for item in pending:
                        item["session_id"] = next(iter(sessions))
                        item["request_id"] = next(iter(requests))
                pending = []
                overlapping = False
    # New shim traces carry a turn identifier even before the upstream request ID exists.
    turns: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        turn_id = _string(event["raw"].get("local_turn_id"))
        if turn_id:
            turns.setdefault(turn_id, []).append(event)
    for group in turns.values():
        for field in ("request_id", "session_id"):
            values = {e[field] for e in group if e.get(field)}
            if len(values) == 1:
                for event in group:
                    event[field] = next(iter(values))


def _eval_user_events(
    source: Source, raw_eval: dict[str, Any], trace_events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Restore rendered inputs with explicit provenance from saved Promptfoo results."""
    rows = raw_eval.get("results")
    if isinstance(rows, dict):
        rows = rows.get("results")
    if not isinstance(rows, list):
        return []
    terminal = [e for e in trace_events if e["kind"] in {"request_completed", "request_failed"}]
    restored = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        prompt = row.get("prompt")
        text = prompt.get("raw") if isinstance(prompt, dict) else None
        if not isinstance(text, str) or not text.strip():
            continue
        response = row.get("response") or {}
        request_id = None
        method = None
        # Error responses retain the shim's request ID even when the provider drops other fields.
        error = response.get("error") or row.get("error")
        if isinstance(error, str):
            try:
                payload = json.loads(error[error.index("{"):])
                request_id = _string(payload.get("genius_trace_summary", {}).get("request_id"))
            except (ValueError, TypeError, AttributeError):
                pass
        candidates = [e for e in terminal if request_id and e["request_id"] == request_id]
        if len(candidates) == 1:
            method = "response_error_request_id"
        elif request_id:
            candidates = []  # Do not override an explicit but unmatched request ID.
        else:
            output = response.get("output")
            matched_ids = {
                e["request_id"] for e in trace_events
                if e.get("request_id") and e.get("text") and isinstance(output, str)
                and e["category"] in {"assistant", "terminal"}
                and e["text"].strip() == output.strip()
            }
            candidates = [e for e in terminal if e["request_id"] in matched_ids]
            if len(candidates) == 1:
                method = "exact_assistant_reply"
            elif not matched_ids:
                # HTTP Date is emitted by the local shim for this exact response.
                headers = response.get("metadata", {}).get("http", {}).get("headers", {})
                date = next((v for k, v in headers.items() if k.lower() == "date"), None)
                try:
                    response_time = parsedate_to_datetime(date).timestamp()
                    candidates = [e for e in terminal if abs(e["timestamp"] - response_time) < 1]
                except (TypeError, ValueError, OverflowError):
                    candidates = []
                if len(candidates) == 1:
                    method = "response_http_date"
        match = candidates[0] if len(candidates) == 1 else None
        request_id = match.get("request_id") if match else None
        starts = [e for e in trace_events if e["kind"] == "request_started" and request_id and e["request_id"] == request_id]
        anchor = starts[0] if len(starts) == 1 else match
        if request_id and any(e["category"] == "user" and e["request_id"] == request_id for e in trace_events):
            continue
        raw = {
            "kind": "user_message", "role": "user", "text": text,
            "origin": "promptfoo_eval", "source_file": "eval.json",
            "source_pointer": f"/results/{'results/' if isinstance(raw_eval.get('results'), dict) else ''}{index}/prompt/raw",
            "test_index": row.get("testIdx", index),
            "association": method if match else "unmatched",
            "timestamp_source": "trace_request_boundary" if anchor else "unrecorded",
            "timestamp": anchor["timestamp"] if anchor else 0,
            "request_id": request_id,
            "upstream_session_id": match.get("session_id") if match else None,
        }
        restored.append(_normalize_event(source, "eval-user", index + 1, raw))
    return restored


def discover_sources(root: Path) -> list[Source]:
    sources: list[Source] = []
    logs_dir = root / "logs"
    if (logs_dir / "genius_trace.jsonl").exists() or (
        logs_dir / "genius_session_lifecycle.jsonl"
    ).exists():
        sources.append(
            Source(logs_dir, "global", "global-logs", "logs", "global")
        )
    if logs_dir.exists():
        for child in sorted(path for path in logs_dir.iterdir() if path.is_dir()):
            if (
                (child / "genius_trace.jsonl").exists()
                or (child / "genius_session_lifecycle.jsonl").exists()
            ):
                sources.append(
                    Source(child, "log-run", child.name, "logs", child.name)
                )
    sweeps_dir = root / "sweeps"
    if sweeps_dir.exists():
        for run_dir in sorted(sweeps_dir.glob("*/*/runs/*")):
            if not run_dir.is_dir():
                continue
            manifest_run, manifest_group, manifest_plugin = _manifest_ids(run_dir)
            relative = run_dir.relative_to(sweeps_dir).parts
            group_id = manifest_group or (
                _string(relative[0]) if len(relative) > 0 else "unknown-group"
            )
            plugin_id = manifest_plugin or (
                _string(relative[1]) if len(relative) > 1 else "unknown-plugin"
            )
            run_id = manifest_run or run_dir.name
            sources.append(
                Source(run_dir, "sweep", run_id, group_id, plugin_id)
            )
    return sources


class ViewerIndex:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.sources = discover_sources(root)
        self.runs: dict[str, dict[str, Any]] = {}
        self.sessions: dict[str, dict[str, Any]] = {}
        self.requests: dict[str, dict[str, Any]] = {}
        self.events: list[dict[str, Any]] = []
        self.errors: list[dict[str, Any]] = []
        self._build()

    def _ensure_run(self, source: Source) -> dict[str, Any]:
        run = self.runs.setdefault(
            source.run_id,
            {
                "run_id": source.run_id,
                "group_id": source.group_id,
                "plugin_id": source.plugin_id,
                "source_kind": source.kind,
                "source_path": str(source.path),
                "sessions": [],
                "requests": [],
                "summary": None,
                "event_count": 0,
            },
        )
        if not run.get("group_id"):
            run["group_id"] = source.group_id
        if not run.get("plugin_id"):
            run["plugin_id"] = source.plugin_id
        return run

    def _ensure_session(self, source: Source, session_id: str | None) -> None:
        if not session_id:
            return
        session = self.sessions.setdefault(
            session_id,
            {
                "session_id": session_id,
                "run_id": source.run_id,
                "group_id": source.group_id,
                "plugin_id": source.plugin_id,
                "requests": [],
                "event_count": 0,
            },
        )
        run = self._ensure_run(source)
        if session_id not in run["sessions"]:
            run["sessions"].append(session_id)

    def _ensure_request(
        self,
        source: Source,
        session_id: str | None,
        request_id: str | None,
    ) -> None:
        if not request_id:
            return
        request = self.requests.setdefault(
            request_id,
            {
                "request_id": request_id,
                "session_id": session_id,
                "run_id": source.run_id,
                "group_id": source.group_id,
                "plugin_id": source.plugin_id,
                "events": [],
                "outcome": None,
                "tool_calls": [],
                "approvals": [],
                "oracle": [],
                "eval": [],
            },
        )
        if session_id and not request.get("session_id"):
            request["session_id"] = session_id
        run = self._ensure_run(source)
        if request_id not in run["requests"]:
            run["requests"].append(request_id)
        if session_id:
            self._ensure_session(source, session_id)
            session = self.sessions[session_id]
            if request_id not in session["requests"]:
                session["requests"].append(request_id)

    def _add_event(self, event: dict[str, Any]) -> None:
        self.events.append(event)
        run = self.runs.get(event["run_id"])
        if run:
            run["event_count"] += 1
        if event.get("session_id"):
            session = self.sessions.get(event["session_id"])
            if session:
                session["event_count"] += 1
        if event.get("request_id"):
            request = self.requests.get(event["request_id"])
            if request:
                request["events"].append(event["event_id"])
                if event["category"] == "tool":
                    request["tool_calls"].append(event["event_id"])
                elif event["category"] == "approval":
                    request["approvals"].append(event["event_id"])
                elif event["category"] == "oracle":
                    request["oracle"].append(event["event_id"])
                elif event["category"] == "eval":
                    request["eval"].append(event["event_id"])
                if event.get("outcome") and not request.get("outcome"):
                    request["outcome"] = event["outcome"]

    def _build(self) -> None:
        for source in self.sources:
            run = self._ensure_run(source)
            trace_path = source.path / "genius_trace.jsonl"
            lifecycle_path = source.path / "genius_session_lifecycle.jsonl"
            if not lifecycle_path.exists():
                lifecycle_path = source.path / "session_lifecycle.jsonl"
            oracle_path = source.path / "oracle.jsonl"
            eval_path = source.path / "eval.json"
            summary_path = source.path / "summary.md"
            if summary_path.exists():
                try:
                    run["summary"] = summary_path.read_text(encoding="utf-8")
                except OSError:
                    pass
            for path, file_kind in (
                (trace_path, "trace"),
                (lifecycle_path, "lifecycle"),
                (oracle_path, "oracle"),
            ):
                if not path.exists():
                    continue
                normalized = [
                    _normalize_event(source, file_kind, line_number, raw)
                    for line_number, raw in enumerate(_read_jsonl(path), start=1)
                ]
                if file_kind == "trace":
                    _link_trace_turns(normalized)
                for event in normalized:
                    self._ensure_session(source, event.get("session_id"))
                    self._ensure_request(
                        source, event.get("session_id"), event.get("request_id")
                    )
                    if not event.get("session_id") and event.get("request_id"):
                        request = self.requests.get(event["request_id"])
                        if request and request.get("session_id"):
                            event["session_id"] = request["session_id"]
                            session = self.sessions.get(event["session_id"])
                            if session and event["request_id"] not in session["requests"]:
                                session["requests"].append(event["request_id"])
                    self._add_event(event)
            if eval_path.exists():
                try:
                    raw_eval = _read_json(eval_path)
                except (OSError, json.JSONDecodeError) as exc:
                    self.errors.append(
                        {"path": str(eval_path), "error": str(exc)}
                    )
                else:
                    trace_events = [e for e in self.events if e["run_id"] == source.run_id and e["source_file"] == "trace"]
                    if isinstance(raw_eval, dict):
                        for user_event in _eval_user_events(source, raw_eval, trace_events):
                            self._ensure_session(source, user_event.get("session_id"))
                            self._ensure_request(source, user_event.get("session_id"), user_event.get("request_id"))
                            self._add_event(user_event)
                    event = _normalize_event(
                        source, "eval", 1, {"kind": "eval", "raw": raw_eval}
                    )
                    self._ensure_request(
                        source, event.get("session_id"), event.get("request_id")
                    )
                    if not event.get("session_id") and event.get("request_id"):
                        request = self.requests.get(event["request_id"])
                        if request and request.get("session_id"):
                            event["session_id"] = request["session_id"]
                    self._add_event(event)
        for event in self.events:
            if not event.get("session_id") and event.get("request_id"):
                request = self.requests.get(event["request_id"])
                if request and request.get("session_id"):
                    event["session_id"] = request["session_id"]
                    session = self.sessions.get(event["session_id"])
                    if session:
                        session["event_count"] += 1
                        if event["request_id"] not in session["requests"]:
                            session["requests"].append(event["request_id"])
        self.events.sort(
            key=lambda event: (
                event["timestamp"],
                0 if event["category"] == "user" else 1,
                event["source_kind"],
                event["source_file"],
                event["line_number"],
            )
        )
        # A successful tool call does not mean that the enclosing request completed.
        # Prefer the final request/approval result over intermediate tool status.
        for event in self.events:
            request = self.requests.get(event.get("request_id"))
            if request and event.get("outcome") and (
                event["category"] == "terminal"
                or event["kind"] == "approval_terminal_result"
            ):
                request["outcome"] = event["outcome"]

    def event(self, event_id: str) -> dict[str, Any] | None:
        for event in self.events:
            if event["event_id"] == event_id:
                return event
        return None


def _filter_events(
    events: Iterable[dict[str, Any]],
    filters: dict[str, str | None],
) -> list[dict[str, Any]]:
    query = (filters.get("q") or "").strip().lower()
    result: list[dict[str, Any]] = []
    for event in events:
        matches = True
        for key in (
            "run_id",
            "group_id",
            "plugin_id",
            "session_id",
            "request_id",
            "outcome",
            "tool_name",
            "confirmation_id",
        ):
            value = filters.get(key)
            if value and event.get(key) != value:
                matches = False
                break
        if query and query not in event.get("search_text", "").lower():
            matches = False
        if matches:
            result.append(event)
    return result


def _filtered_index(
    index: ViewerIndex,
    filters: dict[str, str | None],
) -> dict[str, Any]:
    events = _filter_events(index.events, filters)
    run_ids = sorted({event["run_id"] for event in events})
    session_ids = sorted(
        {event["session_id"] for event in events if event.get("session_id")}
    )
    request_ids = sorted(
        {event["request_id"] for event in events if event.get("request_id")}
    )
    return {
        "runs": [
            {
                key: value
                for key, value in index.runs[run_id].items()
                if key != "summary"
            }
            for run_id in run_ids
            if run_id in index.runs
        ],
        "sessions": [
            index.sessions[session_id]
            for session_id in session_ids
            if session_id in index.sessions
        ],
        "requests": [
            index.requests[request_id]
            for request_id in request_ids
            if request_id in index.requests
        ],
        "event_count": len(events),
        "events": events,
        "errors": index.errors,
    }


class ViewerHTTPHandler(BaseHTTPRequestHandler):
    server: "ViewerHTTPServer"

    def end_headers(self) -> None:
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; connect-src 'self'; img-src 'self' data:; "
            "object-src 'none'; base-uri 'none'; frame-ancestors 'none'",
        )
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        super().end_headers()

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _send_json(
        self,
        status: HTTPStatus,
        payload: Any,
    ) -> None:
        encoded = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status.value)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _send_static(self, path: str) -> None:
        if path in {"/", "/index.html"}:
            file_path = STATIC_ROOT / "index.html"
        else:
            relative = path.lstrip("/")
            file_path = (STATIC_ROOT / relative).resolve()
            static_root = STATIC_ROOT.resolve()
            if not file_path.is_relative_to(static_root):
                self._send_json(
                    HTTPStatus.NOT_FOUND,
                    {"error": "not_found"},
                )
                return
        if not file_path.exists() or not file_path.is_file():
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
            return
        content_type = mimetypes.guess_type(file_path)[0] or "text/plain"
        encoded = file_path.read_bytes()
        self.send_response(HTTPStatus.OK.value)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        query = {
            key: values[-1]
            for key, values in parse_qs(parsed.query).items()
        }
        index = self.server.index
        if path == "/api/index":
            self._send_json(HTTPStatus.OK, _filtered_index(index, query))
            return
        if path == "/api/runs":
            payload = [
                {key: value for key, value in run.items() if key != "summary"}
                for run in index.runs.values()
            ]
            self._send_json(HTTPStatus.OK, payload)
            return
        if path.startswith("/api/run/"):
            run_id = path.removeprefix("/api/run/")
            run = index.runs.get(run_id)
            if run is None:
                self._send_json(HTTPStatus.NOT_FOUND, {"error": "run_not_found"})
                return
            self._send_json(HTTPStatus.OK, run)
            return
        if path.startswith("/api/session/"):
            session_id = path.removeprefix("/api/session/")
            session = index.sessions.get(session_id)
            if session is None:
                self._send_json(
                    HTTPStatus.NOT_FOUND,
                    {"error": "session_not_found"},
                )
                return
            events = [
                event
                for event in index.events
                if event.get("session_id") == session_id
            ]
            self._send_json(
                HTTPStatus.OK,
                {**session, "events": events},
            )
            return
        if path.startswith("/api/request/"):
            request_id = path.removeprefix("/api/request/")
            request = index.requests.get(request_id)
            if request is None:
                self._send_json(
                    HTTPStatus.NOT_FOUND,
                    {"error": "request_not_found"},
                )
                return
            events = [
                event
                for event in index.events
                if event.get("request_id") == request_id
            ]
            self._send_json(
                HTTPStatus.OK,
                {**request, "events": events},
            )
            return
        if path.startswith("/api/event/"):
            event_id = path.removeprefix("/api/event/")
            event = index.event(event_id)
            if event is None:
                self._send_json(HTTPStatus.NOT_FOUND, {"error": "event_not_found"})
                return
            self._send_json(HTTPStatus.OK, event)
            return
        self._send_static(path)


class ViewerHTTPServer(ThreadingHTTPServer):
    def __init__(
        self,
        address: tuple[str, int],
        index: ViewerIndex,
    ) -> None:
        if address[0] != "127.0.0.1":
            raise ValueError("Viewer must bind to 127.0.0.1")
        super().__init__(address, ViewerHTTPHandler)
        self.index = index


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Browse local Genius trace artifacts."
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=4070)
    parser.add_argument(
        "--root",
        default=None,
        help="Project root containing logs/ and sweeps/. Defaults to the current directory.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    root = Path(args.root or Path.cwd()).resolve()
    index = ViewerIndex(root)
    server = ViewerHTTPServer((args.host, args.port), index)
    print(f"Genius trace viewer listening on http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
