from __future__ import annotations

import base64
from contextlib import contextmanager
import json
import os
from pathlib import Path
import threading
import tempfile
import time
from typing import Iterator
import unittest
from unittest.mock import patch

import httpx

from shim.genius_service import (
    ApprovalCandidate,
    ApprovalPolicy,
    CredentialManager,
    GeniusApprovalProtocolError,
    GeniusAuthenticationError,
    GeniusEventCollector,
    GeniusHighRiskApprovalError,
    GeniusHumanInputRequiredError,
    GeniusHTTPServer,
    GeniusRejectedError,
    GeniusService,
    GeniusStreamParser,
    GeniusTimeoutError,
    SessionStore,
    ShimConfig,
    StaticResolveBackend,
    build_chat_completion_response,
    collect_genius_events,
    is_authorized,
    jwt_expiry,
    load_approval_policy,
    make_chat_completion_chunk,
    normalize_messages,
    redact_url,
    sanitize_value,
    serialize_conversation,
    trace_summary,
)


def _jwt(expiry: int) -> str:
    header = base64.urlsafe_b64encode(b'{"alg":"none"}').decode().rstrip("=")
    payload = base64.urlsafe_b64encode(
        json.dumps({"exp": expiry, "sub": "test-user"}).encode()
    ).decode().rstrip("=")
    return f"{header}.{payload}.signature"


def _sse(*events: dict[str, object]) -> str:
    return "".join(
        f"data: {json.dumps(event)}\n\n" for event in events
    ) + "data: [DONE]\n\n"


def _config(
    *,
    token: str = "test-token",
    retries: int = 1,
    trace_path: str = "",
) -> ShimConfig:
    return ShimConfig(
        downstream_api_key="local-key",
        upstream_base_url="https://genius.example",
        upstream_authorization=f"Bearer {token}",
        model_profile="default",
        upstream_timeout_s=2,
        hard_timeout_s=2,
        upstream_retry_attempts=retries,
        upstream_retry_wait_s=0,
        session_ttl_s=60,
        token_refresh_margin_s=5,
        trace_jsonl_path=trace_path,
        lifecycle_jsonl_path="",
    )


def _approval_policy_document(
    *,
    run_id: str = "run-1",
    session_id: str = "session-1",
    tool: str = "write_file",
    action_id: str = "action-1",
    resource: str = "/workspace/redteam-smoke/marker.txt",
) -> dict[str, object]:
    return {
        "rules": [
            {
                "run_id": run_id,
                "session_id": session_id,
                "tool": tool,
                "action_id": action_id,
                "resource": resource,
            }
        ],
        "protocol": {
            "endpoint": "/api/sessions/{{session_id}}/approvals",
            "method": "POST",
            "payload": {
                "action_id": "{{action_id}}",
                "approved": True,
                "run_id": "{{run_id}}",
                "session_id": "{{session_id}}",
            },
            "success_statuses": [200],
            "response": {"accepted": True},
            "continuation": {
                "mode": "persisted_messages",
                "poll_interval_s": 0.01,
                "timeout_s": 0.2,
            },
            "verified": True,
            "evidence_id": "protocol-evidence-1",
        },
    }


def _write_approval_policy(
    path: str,
    document: dict[str, object] | None = None,
) -> str:
    payload = document or _approval_policy_document()
    Path(path).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return path


def _success_stream(content: str = "GENIUS_CONNECTIVITY_OK") -> str:
    return _sse(
        {"type": "reasoning", "delta": "brief thought"},
        {"type": "content_delta", "delta": {"text": content}},
        {"status": "completed", "request_id": "req-test"},
    )


class _FailingStream(httpx.SyncByteStream):
    def __init__(self, *, emit_activity: bool) -> None:
        self.emit_activity = emit_activity

    def __iter__(self) -> Iterator[bytes]:
        if self.emit_activity:
            yield b'data: {"type":"content_delta","delta":"partial"}\n\n'
        raise httpx.ReadTimeout("simulated timeout")


@contextmanager
def _running_server(service: GeniusService):
    server = GeniusHTTPServer(("127.0.0.1", 0), service)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


class GeniusMessageTests(unittest.TestCase):
    def test_normalize_messages_preserves_text_and_placeholders(self) -> None:
        messages = normalize_messages(
            [
                {"role": "system", "content": "Be concise."},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Analyze this"},
                        {"type": "image_url", "image_url": {"url": "x"}},
                    ],
                },
            ]
        )
        self.assertEqual(messages[0], {"role": "system", "content": "Be concise."})
        self.assertEqual(messages[1]["content"], "Analyze this\n[image_url]")

    def test_serialize_conversation_uses_direct_single_user_prompt(self) -> None:
        self.assertEqual(
            serialize_conversation([{"role": "user", "content": "hello"}]),
            "hello",
        )
        transcript = serialize_conversation(
            [
                {"role": "user", "content": "hello"},
                {"role": "assistant", "content": "hi"},
                {"role": "user", "content": "continue"},
            ]
        )
        self.assertIn("USER:\ncontinue", transcript)
        self.assertIn("respond only to the latest user message", transcript)

    def test_openai_response_and_chunk_shapes(self) -> None:
        result = collect_genius_events(
            [
                {"type": "content_delta", "delta": "answer"},
                {"status": "completed"},
            ]
        )
        response = build_chat_completion_response("genius-agent", "prompt", result)
        self.assertEqual(response["choices"][0]["message"]["content"], "answer")
        self.assertEqual(response["choices"][0]["finish_reason"], "stop")
        chunk = make_chat_completion_chunk(
            {"id": "id", "model": "genius-agent", "created": 1},
            {"content": "a"},
            None,
        )
        self.assertEqual(chunk["object"], "chat.completion.chunk")

    def test_local_authentication_is_exact(self) -> None:
        self.assertTrue(is_authorized("Bearer local-key", "local-key"))
        self.assertFalse(is_authorized(None, "local-key"))
        self.assertFalse(is_authorized("Bearer wrong", "local-key"))


class GeniusCredentialTests(unittest.TestCase):
    def test_jwt_expiry_and_refresh_success(self) -> None:
        expired = _jwt(int(time.time()) - 10)
        replacement = _jwt(int(time.time()) + 3600)
        seen: list[dict[str, object]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(json.loads(request.content))
            return httpx.Response(200, json={"token": replacement})

        client = httpx.Client(transport=httpx.MockTransport(handler))
        manager = CredentialManager(
            expired,
            "https://genius.example",
            client,
            refresh_margin_s=30,
        )
        self.assertLess(jwt_expiry(expired) or 0, time.time())
        self.assertEqual(manager.authorization(), f"Bearer {replacement}")
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0]["token"], expired)
        client.close()

    def test_concurrent_refresh_only_calls_upstream_once(self) -> None:
        expired = _jwt(int(time.time()) - 10)
        replacement = _jwt(int(time.time()) + 3600)
        call_count = 0
        call_lock = threading.Lock()

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            with call_lock:
                call_count += 1
            time.sleep(0.02)
            return httpx.Response(200, json={"token": replacement})

        client = httpx.Client(transport=httpx.MockTransport(handler))
        manager = CredentialManager(
            expired,
            "https://genius.example",
            client,
            refresh_margin_s=30,
        )
        results: list[str] = []
        threads = [
            threading.Thread(target=lambda: results.append(manager.authorization()))
            for _ in range(6)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(call_count, 1)
        self.assertEqual(results, [f"Bearer {replacement}"] * 6)
        client.close()

    def test_refresh_failure_is_a_distinct_authentication_error(self) -> None:
        expired = _jwt(int(time.time()) - 10)
        client = httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(401, json={"detail": "expired"})
            )
        )
        manager = CredentialManager(
            expired,
            "https://genius.example",
            client,
            refresh_margin_s=30,
        )
        with self.assertRaises(GeniusAuthenticationError) as caught:
            manager.authorization()
        self.assertEqual(caught.exception.code, "genius_authentication_failed")
        client.close()

    def test_secret_redaction_covers_headers_and_query_tokens(self) -> None:
        value = sanitize_value(
            {
                "Authorization": "Bearer secret-value",
                "url": "https://example.test/events?token=secret-value&since=1",
                "nested": {"api_token": "secret-value"},
            }
        )
        encoded = json.dumps(value)
        self.assertNotIn("secret-value", encoded)
        self.assertIn("redacted", encoded)
        self.assertEqual(
            redact_url("https://example.test/events?token=x&since=1"),
            "https://example.test/events?token=%3Credacted%3E&since=1",
        )

    def test_static_resolver_changes_tcp_host_only(self) -> None:
        calls: list[tuple[str, int]] = []

        class Delegate:
            def connect_tcp(self, host, port, **kwargs):
                calls.append((host, port))
                return object()

            def connect_unix_socket(self, path, **kwargs):
                return object()

            def sleep(self, seconds):
                return None

        backend = StaticResolveBackend(
            "genius.xtalpi.com",
            "public-alb.example",
            delegate=Delegate(),
        )
        stream = backend.connect_tcp("genius.xtalpi.com", 443)
        self.assertIsNotNone(stream)
        self.assertEqual(calls, [("public-alb.example", 443)])


class GeniusSessionTests(unittest.TestCase):
    def test_explicit_session_reuses_only_matching_history(self) -> None:
        store = SessionStore(ttl_s=60)
        created: list[str] = []

        def create() -> str:
            session_id = f"session-{len(created) + 1}"
            created.append(session_id)
            return session_id

        first_history = [{"role": "user", "content": "hello"}]
        first = store.prepare("case-1", first_history, create)
        store.complete("case-1", first_history, "hi")
        second_history = [
            *first_history,
            {"role": "assistant", "content": "hi"},
            {"role": "user", "content": "continue"},
        ]
        second = store.prepare("case-1", second_history, create)
        other = store.prepare("case-2", first_history, create)

        self.assertFalse(first.reused)
        self.assertTrue(second.reused)
        self.assertEqual(second.upstream_session_id, first.upstream_session_id)
        self.assertEqual(second.query, "continue")
        self.assertNotEqual(other.upstream_session_id, first.upstream_session_id)

    def test_missing_or_diverged_session_is_isolated(self) -> None:
        store = SessionStore(ttl_s=60)
        counter = 0

        def create() -> str:
            nonlocal counter
            counter += 1
            return f"session-{counter}"

        messages = [{"role": "user", "content": "hello"}]
        first = store.prepare(None, messages, create)
        second = store.prepare(None, messages, create)
        mapped = store.prepare("case", messages, create)
        store.complete("case", messages, "hi")
        diverged = store.prepare(
            "case", [{"role": "user", "content": "different"}], create
        )
        self.assertNotEqual(first.upstream_session_id, second.upstream_session_id)
        self.assertNotEqual(mapped.upstream_session_id, diverged.upstream_session_id)


class GeniusEventTests(unittest.TestCase):
    def test_parser_collects_text_reasoning_tools_and_status(self) -> None:
        collector = GeniusEventCollector()
        parser = GeniusStreamParser(collector)
        parser.feed(
            _sse(
                {"type": "reasoning", "delta": "think"},
                {"type": "content_delta", "delta": {"text": "answer"}},
                {
                    "type": "tool_call",
                    "tool_name": "search",
                    "tool_input": {"query": "chemistry", "token": "secret"},
                },
                {"status": "completed", "request_id": "req-1"},
            )
        )
        parser.finish()
        result = collector.result(upstream_session_id="session-1")
        self.assertEqual(result.content, "answer")
        self.assertEqual(result.thinking_content, "think")
        self.assertEqual(result.terminal_status, "completed")
        self.assertEqual(result.request_id, "req-1")
        self.assertEqual(result.tool_events[0]["tool_name"], "search")
        self.assertEqual(result.tool_events[0]["tool_input"]["token"], "<redacted>")
        self.assertEqual(trace_summary(result, outcome="test")["tool_events_count"], 1)

    def test_parser_supports_observed_genius_stream_shape(self) -> None:
        collector = GeniusEventCollector()
        parser = GeniusStreamParser(collector)
        parser.feed(
            _sse(
                {"status": "processing"},
                {
                    "request_id": "req-live",
                    "seq": 1,
                    "text": "brief thought",
                    "thinking_round": 0,
                },
                {"request_id": "req-live", "seq": 2, "text": "answer"},
                {
                    "success": True,
                    "reply": "answer",
                    "streamed": True,
                    "persisted": True,
                    "actions": [],
                },
            )
        )
        parser.finish()
        result = collector.result(upstream_session_id="session-live")
        self.assertEqual(result.content, "answer")
        self.assertEqual(result.thinking_content, "brief thought")
        self.assertEqual(result.terminal_status, "completed")
        self.assertGreaterEqual(result.meaningful_event_count, 3)

    def test_read_only_human_input_is_deferred_without_pause(self) -> None:
        result = collect_genius_events(
            [
                {
                    "type": "request_user_input",
                    "status": "awaiting_user_input",
                    "tool_name": "query",
                    "question": "Which project contains this table?",
                }
            ]
        )
        self.assertEqual(result.trace["outcome"], "deferred_for_input")
        self.assertFalse(result.trace["campaign_pause_required"])
        self.assertEqual(
            result.trace["human_input_request"]["tool_names"], ["query"]
        )

    def test_high_risk_approval_sets_pause_signal(self) -> None:
        result = collect_genius_events(
            [
                {
                    "type": "approval_request",
                    "status": "approval_required",
                    "question": "Allow this write?",
                    "actions": [
                        {"tool_name": "write_file", "status": "pending_approval"}
                    ],
                }
            ]
        )
        self.assertEqual(result.trace["outcome"], "high_risk_approval_blocked")
        self.assertEqual(result.trace["high_risk_tool_names"], ["write_file"])
        self.assertTrue(result.trace["campaign_pause_required"])


class GeniusApprovalTests(unittest.TestCase):
    def test_policy_loader_validates_rules_and_verified_protocol(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            valid_path = _write_approval_policy(f"{tmpdir}/valid.json")
            valid = load_approval_policy(valid_path)
            self.assertTrue(valid.valid)
            self.assertEqual(valid.rules[0].tool, "write_file")
            self.assertIsNotNone(valid.protocol)

            self.assertFalse(load_approval_policy("").valid)
            self.assertFalse(load_approval_policy(f"{tmpdir}/missing.json").valid)

            invalid_json = Path(f"{tmpdir}/invalid.json")
            invalid_json.write_text("{not-json", encoding="utf-8")
            self.assertFalse(load_approval_policy(str(invalid_json)).valid)

            empty_rules = _approval_policy_document()
            empty_rules["rules"] = []
            empty_path = _write_approval_policy(
                f"{tmpdir}/empty-rules.json", empty_rules
            )
            self.assertIn("empty", load_approval_policy(empty_path).reason)

            unverified = _approval_policy_document()
            unverified["protocol"]["verified"] = False  # type: ignore[index]
            unverified_path = _write_approval_policy(
                f"{tmpdir}/unverified.json", unverified
            )
            self.assertIn("verified", load_approval_policy(unverified_path).reason)

            missing_protocol = _approval_policy_document()
            del missing_protocol["protocol"]
            missing_path = _write_approval_policy(
                f"{tmpdir}/missing-protocol.json", missing_protocol
            )
            self.assertFalse(load_approval_policy(missing_path).valid)

    def test_approval_candidate_captures_ids_and_redacts_sensitive_values(self) -> None:
        event = {
            "type": "approval_request",
            "status": "approval_required",
            "event_id": "event-1",
            "request_id": "request-1",
            "run_id": "run-1",
            "session_id": "session-1",
            "actions": [
                {
                    "id": "action-1",
                    "tool_name": "write_file",
                    "tool_input": {
                        "path": "/workspace/redteam-smoke/marker.txt",
                        "token": "secret-value",
                    },
                }
            ],
        }
        candidate = ApprovalCandidate.from_event(event)
        assert candidate is not None
        self.assertEqual(candidate.action_id, "action-1")
        self.assertEqual(candidate.resource, "/workspace/redteam-smoke/marker.txt")
        encoded = json.dumps(candidate.trace)
        self.assertNotIn("secret-value", encoded)
        self.assertIn("redacted", encoded)

    def test_policy_mismatch_fails_closed_without_submit(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            policy_path = _write_approval_policy(
                f"{tmpdir}/policy.json",
                _approval_policy_document(resource="/workspace/different.txt"),
            )
            submitted: list[str] = []

            def handler(request: httpx.Request) -> httpx.Response:
                if request.url.path == "/api/sessions":
                    return httpx.Response(200, json={"id": "session-1"})
                if request.url.path == "/chat/stream":
                    return httpx.Response(
                        200,
                        text=_sse(
                            {
                                "type": "approval_request",
                                "status": "approval_required",
                                "run_id": "run-1",
                                "session_id": "session-1",
                                "actions": [
                                    {
                                        "id": "action-1",
                                        "tool_name": "write_file",
                                        "tool_input": {
                                            "path": "/workspace/redteam-smoke/marker.txt"
                                        },
                                    }
                                ],
                            }
                        ),
                        headers={"Content-Type": "text/event-stream"},
                    )
                if request.url.path.endswith("/messages"):
                    return httpx.Response(200, json={"messages": []})
                submitted.append(request.url.path)
                raise AssertionError(request.url)

            client = httpx.Client(transport=httpx.MockTransport(handler))
            config = ShimConfig(
                **{**_config().__dict__, "approval_policy_file": policy_path}
            )
            service = GeniusService(config, client=client)
            with self.assertRaises(GeniusHighRiskApprovalError) as caught:
                service.complete(
                    {
                        "messages": [{"role": "user", "content": "probe"}],
                        "metadata": {"session_id": "session-1"},
                    }
                )
            self.assertEqual(submitted, [])
            self.assertEqual(
                caught.exception.trace_summary["approval_decision"]["decision"],
                "denied",
            )
            self.assertIn(
                "no exact approval policy rule match",
                caught.exception.trace_summary["approval_decision"]["reason"],
            )
            service.close()
            client.close()

    def test_exact_policy_submits_and_continues_without_replaying_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            policy_path = _write_approval_policy(f"{tmpdir}/policy.json")
            lifecycle = f"{tmpdir}/lifecycle.jsonl"
            chat_count = 0
            approval_requests: list[dict[str, object]] = []

            def handler(request: httpx.Request) -> httpx.Response:
                nonlocal chat_count
                if request.url.path == "/api/sessions":
                    return httpx.Response(200, json={"id": "session-1"})
                if request.url.path == "/chat/stream":
                    chat_count += 1
                    return httpx.Response(
                        200,
                        text=_sse(
                            {
                                "type": "approval_request",
                                "status": "approval_required",
                                "run_id": "run-1",
                                "session_id": "session-1",
                                "request_id": "request-1",
                                "actions": [
                                    {
                                        "id": "action-1",
                                        "tool_name": "write_file",
                                        "tool_input": {
                                            "path": "/workspace/redteam-smoke/marker.txt"
                                        },
                                    }
                                ],
                            }
                        ),
                        headers={"Content-Type": "text/event-stream"},
                    )
                if request.url.path == "/api/sessions/session-1/approvals":
                    approval_requests.append(json.loads(request.content))
                    return httpx.Response(200, json={"accepted": True})
                if request.url.path.endswith("/messages"):
                    return httpx.Response(
                        200,
                        json={
                            "messages": [
                                {
                                    "role": "assistant",
                                    "content": "approved answer",
                                    "request_id": "request-1",
                                },
                                {
                                    "role": "tool",
                                    "tool_name": "write_file",
                                    "tool_status": "finished",
                                },
                            ]
                        },
                    )
                raise AssertionError(request.url)

            client = httpx.Client(transport=httpx.MockTransport(handler))
            config = ShimConfig(
                **{
                    **_config().__dict__,
                    "approval_policy_file": policy_path,
                    "lifecycle_jsonl_path": lifecycle,
                }
            )
            service = GeniusService(config, client=client)
            _, result = service.complete(
                {
                    "messages": [{"role": "user", "content": "probe"}],
                    "metadata": {
                        "session_id": "session-1",
                        "campaign": {"run_id": "run-1"},
                    },
                }
            )
            self.assertEqual(chat_count, 1)
            self.assertEqual(result.content, "approved answer")
            self.assertEqual(result.trace["outcome"], "completed_after_approval")
            self.assertFalse(result.trace["campaign_pause_required"])
            self.assertEqual(
                result.trace["approval_decision"]["decision"], "approved"
            )
            self.assertEqual(approval_requests[0]["action_id"], "action-1")
            self.assertTrue(approval_requests[0]["approved"])

            rows = [
                json.loads(line)
                for line in Path(lifecycle).read_text(encoding="utf-8").splitlines()
            ]
            kinds = [row["kind"] for row in rows]
            for expected in (
                "approval_observed",
                "approval_policy_decision",
                "approval_protocol_submit",
                "approval_continuation_started",
                "approval_terminal_result",
            ):
                self.assertIn(expected, kinds)
            service.close()
            client.close()

    def test_approval_protocol_rejection_is_upstream_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            policy_path = _write_approval_policy(f"{tmpdir}/policy.json")

            def handler(request: httpx.Request) -> httpx.Response:
                if request.url.path == "/api/sessions":
                    return httpx.Response(200, json={"id": "session-1"})
                if request.url.path == "/chat/stream":
                    return httpx.Response(
                        200,
                        text=_sse(
                            {
                                "type": "approval_request",
                                "status": "approval_required",
                                "run_id": "run-1",
                                "session_id": "session-1",
                                "actions": [
                                    {
                                        "id": "action-1",
                                        "tool_name": "write_file",
                                        "tool_input": {
                                            "path": "/workspace/redteam-smoke/marker.txt"
                                        },
                                    }
                                ],
                            }
                        ),
                        headers={"Content-Type": "text/event-stream"},
                    )
                if request.url.path == "/api/sessions/session-1/approvals":
                    return httpx.Response(403, json={"detail": "denied"})
                raise AssertionError(request.url)

            client = httpx.Client(transport=httpx.MockTransport(handler))
            config = ShimConfig(
                **{**_config(retries=0).__dict__, "approval_policy_file": policy_path}
            )
            service = GeniusService(config, client=client)
            with self.assertRaises(GeniusRejectedError):
                service.complete(
                    {"messages": [{"role": "user", "content": "probe"}]}
                )
            service.close()
            client.close()

    def test_approval_protocol_invalid_response_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            policy_path = _write_approval_policy(f"{tmpdir}/policy.json")

            def handler(request: httpx.Request) -> httpx.Response:
                if request.url.path == "/api/sessions":
                    return httpx.Response(200, json={"id": "session-1"})
                if request.url.path == "/chat/stream":
                    return httpx.Response(
                        200,
                        text=_sse(
                            {
                                "type": "approval_request",
                                "status": "approval_required",
                                "run_id": "run-1",
                                "session_id": "session-1",
                                "actions": [
                                    {
                                        "id": "action-1",
                                        "tool_name": "write_file",
                                        "tool_input": {
                                            "path": "/workspace/redteam-smoke/marker.txt"
                                        },
                                    }
                                ],
                            }
                        ),
                        headers={"Content-Type": "text/event-stream"},
                    )
                if request.url.path == "/api/sessions/session-1/approvals":
                    return httpx.Response(200, json={"accepted": False})
                raise AssertionError(request.url)

            client = httpx.Client(transport=httpx.MockTransport(handler))
            config = ShimConfig(
                **{**_config(retries=0).__dict__, "approval_policy_file": policy_path}
            )
            service = GeniusService(config, client=client)
            with self.assertRaises(GeniusApprovalProtocolError):
                service.complete(
                    {"messages": [{"role": "user", "content": "probe"}]}
                )
            service.close()
            client.close()

    def test_approval_continuation_timeout_does_not_replay_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            policy_path = _write_approval_policy(f"{tmpdir}/policy.json")
            chat_count = 0

            def handler(request: httpx.Request) -> httpx.Response:
                nonlocal chat_count
                if request.url.path == "/api/sessions":
                    return httpx.Response(200, json={"id": "session-1"})
                if request.url.path == "/chat/stream":
                    chat_count += 1
                    return httpx.Response(
                        200,
                        text=_sse(
                            {
                                "type": "approval_request",
                                "status": "approval_required",
                                "run_id": "run-1",
                                "session_id": "session-1",
                                "actions": [
                                    {
                                        "id": "action-1",
                                        "tool_name": "write_file",
                                        "tool_input": {
                                            "path": "/workspace/redteam-smoke/marker.txt"
                                        },
                                    }
                                ],
                            }
                        ),
                        headers={"Content-Type": "text/event-stream"},
                    )
                if request.url.path == "/api/sessions/session-1/approvals":
                    return httpx.Response(200, json={"accepted": True})
                if request.url.path.endswith("/messages"):
                    return httpx.Response(200, json={"messages": []})
                raise AssertionError(request.url)

            client = httpx.Client(transport=httpx.MockTransport(handler))
            config = ShimConfig(
                **{**_config(retries=0).__dict__, "approval_policy_file": policy_path}
            )
            service = GeniusService(config, client=client)
            with self.assertRaises(GeniusTimeoutError):
                service.complete(
                    {"messages": [{"role": "user", "content": "probe"}]}
                )
            self.assertEqual(chat_count, 1)
            service.close()
            client.close()

    def test_normal_human_input_is_not_auto_approved(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            policy_path = _write_approval_policy(f"{tmpdir}/policy.json")
            submitted: list[str] = []

            def handler(request: httpx.Request) -> httpx.Response:
                if request.url.path == "/api/sessions":
                    return httpx.Response(200, json={"id": "session-1"})
                if request.url.path == "/chat/stream":
                    return httpx.Response(
                        200,
                        text=_sse(
                            {
                                "type": "request_user_input",
                                "status": "awaiting_user_input",
                                "tool_name": "query",
                                "question": "Which project?",
                            }
                        ),
                        headers={"Content-Type": "text/event-stream"},
                    )
                submitted.append(request.url.path)
                raise AssertionError(request.url)

            client = httpx.Client(transport=httpx.MockTransport(handler))
            config = ShimConfig(
                **{**_config().__dict__, "approval_policy_file": policy_path}
            )
            service = GeniusService(config, client=client)
            with self.assertRaises(GeniusHumanInputRequiredError):
                service.complete(
                    {"messages": [{"role": "user", "content": "probe"}]}
                )
            self.assertEqual(submitted, [])
            service.close()
            client.close()

    def test_tool_result_approval_candidate_is_detected(self) -> None:
        event = {
            "request_id": "request-1",
            "session_id": "session-1",
            "tool": "team_delete",
            "tool_input": {"team_id": "team-1"},
            "result": json.dumps(
                {
                    "status": "awaiting_user_confirmation",
                    "action": "team_delete",
                    "confirmation_id": "confirmation-1",
                    "surface_kind": "confirmation_required",
                    "message": "Waiting for your confirmation: Delete team?",
                    "blocking": True,
                }
            ),
        }
        candidate = ApprovalCandidate.from_event(event)
        assert candidate is not None
        self.assertEqual(candidate.event_id, "confirmation-1")
        self.assertEqual(candidate.action_id, "confirmation-1")
        self.assertEqual(candidate.tool, "team_delete")
        self.assertEqual(candidate.resource, "team-1")
        self.assertEqual(candidate.prompt, "Waiting for your confirmation: Delete team?")

    def test_chat_stream_approval_uses_answer_prefix_without_new_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            document = _approval_policy_document(
                tool="team_delete",
                action_id="confirmation-1",
                resource="team-1",
            )
            document["protocol"]["endpoint"] = "/chat/stream"
            document["protocol"]["payload"] = {"message": "{{answer_message}}"}
            document["protocol"]["response"] = {}
            policy_path = _write_approval_policy(
                f"{tmpdir}/policy.json", document
            )
            chat_requests: list[dict[str, object]] = []

            def handler(request: httpx.Request) -> httpx.Response:
                if request.url.path == "/api/sessions":
                    return httpx.Response(200, json={"id": "session-1"})
                if request.url.path == "/chat/stream":
                    payload = json.loads(request.content)
                    chat_requests.append(payload)
                    message = str(payload.get("message") or "")
                    if message.startswith("[answering:"):
                        self.assertIn("questionId=confirmation-1", message)
                        self.assertIn("Yes, go ahead", message)
                        return httpx.Response(
                            200,
                            text=_success_stream("approved answer"),
                            headers={"Content-Type": "text/event-stream"},
                        )
                    return httpx.Response(
                        200,
                        text=_sse(
                            {
                                "request_id": "request-1",
                                "session_id": "session-1",
                                "tool": "team_delete",
                                "tool_input": {"team_id": "team-1"},
                                "result": json.dumps(
                                    {
                                        "status": "awaiting_user_confirmation",
                                        "action": "team_delete",
                                        "confirmation_id": "confirmation-1",
                                        "surface_kind": "confirmation_required",
                                        "message": "Waiting for your confirmation: Delete team?",
                                        "blocking": True,
                                    }
                                ),
                            }
                        ),
                        headers={"Content-Type": "text/event-stream"},
                    )
                raise AssertionError(request.url)

            client = httpx.Client(transport=httpx.MockTransport(handler))
            config = ShimConfig(
                **{
                    **_config(retries=0).__dict__,
                    "approval_policy_file": policy_path,
                }
            )
            service = GeniusService(config, client=client)
            _, result = service.complete(
                {
                    "messages": [{"role": "user", "content": "probe"}],
                    "metadata": {
                        "session_id": "session-1",
                        "campaign": {"run_id": "run-1"},
                    },
                }
            )
            self.assertEqual(len(chat_requests), 2)
            self.assertEqual(result.content, "approved answer")
            self.assertEqual(result.trace["outcome"], "completed_after_approval")
            self.assertEqual(
                result.trace["approval_protocol_response"]["mode"],
                "chat_stream",
            )
            service.close()
            client.close()

    def test_high_risk_action_sets_campaign_pause_signal(self) -> None:
        result = collect_genius_events(
            [
                {
                    "success": True,
                    "reply": "done",
                    "actions": [{"name": "write_file", "status": "finished"}],
                }
            ]
        )
        self.assertEqual(result.trace["high_risk_tool_names"], ["write_file"])
        self.assertTrue(result.trace["campaign_pause_required"])


class GeniusServiceTests(unittest.TestCase):
    def test_user_turn_is_recorded_with_redaction_and_turn_correlation(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/api/sessions":
                return httpx.Response(200, json={"id": "session-1"})
            if request.url.path == "/chat/stream":
                return httpx.Response(200, text=_success_stream("answer"), headers={"Content-Type": "text/event-stream"})
            raise AssertionError(request.url)

        with tempfile.TemporaryDirectory() as tmpdir:
            trace = Path(tmpdir) / "trace.jsonl"
            with httpx.Client(transport=httpx.MockTransport(handler)) as client:
                service = GeniusService(_config(trace_path=str(trace)), client=client)
                service.complete({"messages": [{"role": "user", "content": "Inspect Bearer sensitive-example-token"}], "metadata": {"campaign": {"run_id": "test-run"}}})
                service.close()
            rows = [json.loads(line) for line in trace.read_text().splitlines()]
            user = next(row for row in rows if row["kind"] == "user_message")
            start = next(row for row in rows if row["kind"] == "request_started")
            terminal = next(row for row in rows if row["kind"] == "request_completed")
            self.assertEqual(user["text"], "Inspect Bearer <redacted>")
            self.assertEqual(user["origin"], "local_shim")
            self.assertEqual(user["upstream_session_id"], "session-1")
            self.assertEqual(user["run_id"], "test-run")
            self.assertEqual(user["local_turn_id"], terminal["local_turn_id"])
            self.assertLess(rows.index(user), rows.index(start))
            self.assertNotIn("sensitive-example-token", trace.read_text())

    def test_human_input_stream_stops_without_answer_or_approval(self) -> None:
        paths: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            paths.append(request.url.path)
            if request.url.path == "/api/sessions":
                return httpx.Response(200, json={"id": "session-1"})
            if request.url.path == "/chat/stream":
                return httpx.Response(
                    200,
                    text=_sse(
                        {
                            "type": "request_user_input",
                            "status": "awaiting_user_input",
                            "tool_name": "query",
                            "question": "Which project should I use?",
                        }
                    ),
                    headers={"Content-Type": "text/event-stream"},
                )
            raise AssertionError(request.url)

        client = httpx.Client(transport=httpx.MockTransport(handler))
        service = GeniusService(_config(retries=2), client=client)
        with self.assertRaises(GeniusHumanInputRequiredError) as caught:
            service.complete({"messages": [{"role": "user", "content": "probe"}]})
        self.assertEqual(caught.exception.trace_summary["outcome"], "deferred_for_input")
        self.assertEqual(paths, ["/api/sessions", "/chat/stream"])
        service.close()
        client.close()

    def test_persisted_high_risk_approval_is_not_submitted(self) -> None:
        methods_and_paths: list[tuple[str, str]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            methods_and_paths.append((request.method, request.url.path))
            if request.url.path == "/api/sessions":
                return httpx.Response(200, json={"id": "session-1"})
            if request.url.path == "/chat/stream":
                return httpx.Response(
                    200,
                    text=_sse({"status": "completed"}),
                    headers={"Content-Type": "text/event-stream"},
                )
            if request.url.path.endswith("/messages"):
                return httpx.Response(
                    200,
                    json={
                        "messages": [
                            {
                                "type": "approval_request",
                                "status": "approval_required",
                                "tool_name": "execute_shell_command",
                                "question": "Allow this command?",
                            }
                        ]
                    },
                )
            raise AssertionError(request.url)

        client = httpx.Client(transport=httpx.MockTransport(handler))
        service = GeniusService(_config(), client=client)
        with self.assertRaises(GeniusHighRiskApprovalError) as caught:
            service.complete({"messages": [{"role": "user", "content": "probe"}]})
        self.assertEqual(
            caught.exception.trace_summary["outcome"],
            "high_risk_approval_blocked",
        )
        self.assertFalse(
            any(method == "POST" and path != "/chat/stream" and path != "/api/sessions"
                for method, path in methods_and_paths)
        )
        service.close()
        client.close()

    def test_complete_sends_expected_upstream_fields(self) -> None:
        requests: list[dict[str, object]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/api/sessions":
                return httpx.Response(200, json={"id": "session-1"})
            if request.url.path == "/chat/stream":
                requests.append(json.loads(request.content))
                return httpx.Response(
                    200,
                    text=_success_stream(),
                    headers={"Content-Type": "text/event-stream"},
                )
            raise AssertionError(request.url)

        client = httpx.Client(transport=httpx.MockTransport(handler))
        service = GeniusService(_config(), client=client)
        _, result = service.complete(
            {
                "model": "genius-agent",
                "messages": [{"role": "user", "content": "probe"}],
                "reasoning_effort": "low",
            }
        )
        self.assertEqual(result.content, "GENIUS_CONNECTIVITY_OK")
        self.assertEqual(requests[0]["session_type"], "general")
        self.assertEqual(requests[0]["model_profile"], "default")
        self.assertEqual(requests[0]["reasoning_effort"], "low")
        self.assertEqual(requests[0]["message"], "probe")
        service.close()
        client.close()

    def test_empty_stream_reconciles_same_session_messages(self) -> None:
        paths: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            paths.append(request.url.path)
            if request.url.path == "/api/sessions":
                return httpx.Response(200, json={"session_id": "session-1"})
            if request.url.path == "/chat/stream":
                return httpx.Response(
                    200,
                    text=_sse({"status": "completed"}),
                    headers={"Content-Type": "text/event-stream"},
                )
            if request.url.path.endswith("/messages"):
                return httpx.Response(
                    200,
                    json={
                        "messages": [
                            {
                                "role": "assistant",
                                "content": "persisted answer",
                                "thinking_content": "persisted thought",
                                "request_id": "req-persisted",
                            }
                        ]
                    },
                )
            raise AssertionError(request.url)

        client = httpx.Client(transport=httpx.MockTransport(handler))
        service = GeniusService(_config(), client=client)
        _, result = service.complete(
            {"messages": [{"role": "user", "content": "probe"}]}
        )
        self.assertEqual(result.content, "persisted answer")
        self.assertEqual(result.thinking_content, "persisted thought")
        self.assertIn("/api/sessions/session-1/messages", paths)
        service.close()
        client.close()

    def test_retry_occurs_only_before_activity(self) -> None:
        chat_count = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal chat_count
            if request.url.path == "/api/sessions":
                return httpx.Response(200, json={"id": "session-1"})
            if request.url.path == "/chat/stream":
                chat_count += 1
                if chat_count == 1:
                    return httpx.Response(503, text="temporary")
                return httpx.Response(
                    200,
                    text=_success_stream("after retry"),
                    headers={"Content-Type": "text/event-stream"},
                )
            raise AssertionError(request.url)

        client = httpx.Client(transport=httpx.MockTransport(handler))
        service = GeniusService(_config(retries=1), client=client)
        _, result = service.complete(
            {"messages": [{"role": "user", "content": "probe"}]}
        )
        self.assertEqual(result.content, "after retry")
        self.assertEqual(chat_count, 2)
        service.close()
        client.close()

    def test_timeout_after_activity_is_not_replayed(self) -> None:
        chat_count = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal chat_count
            if request.url.path == "/api/sessions":
                return httpx.Response(200, json={"id": "session-1"})
            if request.url.path == "/chat/stream":
                chat_count += 1
                return httpx.Response(200, stream=_FailingStream(emit_activity=True))
            if request.url.path.endswith("/messages"):
                return httpx.Response(200, json={"messages": []})
            raise AssertionError(request.url)

        client = httpx.Client(transport=httpx.MockTransport(handler))
        service = GeniusService(_config(retries=2), client=client)
        with self.assertRaises(GeniusTimeoutError) as caught:
            service.complete(
                {"messages": [{"role": "user", "content": "probe"}]}
            )
        self.assertEqual(chat_count, 1)
        self.assertGreater(
            caught.exception.trace_summary["meaningful_event_count"], 0
        )
        service.close()
        client.close()

    def test_timeout_after_activity_reconciles_persisted_answer_and_tools(self) -> None:
        chat_count = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal chat_count
            if request.url.path == "/api/sessions":
                return httpx.Response(200, json={"id": "session-1"})
            if request.url.path == "/chat/stream":
                chat_count += 1
                return httpx.Response(200, stream=_FailingStream(emit_activity=True))
            if request.url.path.endswith("/messages"):
                return httpx.Response(
                    200,
                    json={
                        "messages": [
                            {
                                "role": "assistant",
                                "content": "I cannot provide that internal record.",
                                "request_id": "req-reconciled",
                            },
                            {
                                "role": "tool",
                                "tool_name": "catalog_search",
                                "tool_status": "finished",
                            },
                        ]
                    },
                )
            raise AssertionError(request.url)

        client = httpx.Client(transport=httpx.MockTransport(handler))
        service = GeniusService(_config(retries=2), client=client)
        _, result = service.complete(
            {"messages": [{"role": "user", "content": "probe"}]}
        )
        self.assertEqual(result.content, "I cannot provide that internal record.")
        self.assertTrue(result.reconciled_from_persisted)
        self.assertEqual(result.tool_events[0]["tool_name"], "catalog_search")
        self.assertFalse(result.trace["campaign_pause_required"])
        self.assertEqual(chat_count, 1)
        service.close()
        client.close()

    def test_timeout_before_activity_is_retried(self) -> None:
        chat_count = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal chat_count
            if request.url.path == "/api/sessions":
                return httpx.Response(200, json={"id": "session-1"})
            if request.url.path == "/chat/stream":
                chat_count += 1
                if chat_count == 1:
                    return httpx.Response(
                        200, stream=_FailingStream(emit_activity=False)
                    )
                return httpx.Response(
                    200,
                    text=_success_stream("recovered"),
                    headers={"Content-Type": "text/event-stream"},
                )
            raise AssertionError(request.url)

        client = httpx.Client(transport=httpx.MockTransport(handler))
        service = GeniusService(_config(retries=1), client=client)
        _, result = service.complete(
            {"messages": [{"role": "user", "content": "probe"}]}
        )
        self.assertEqual(result.content, "recovered")
        self.assertEqual(chat_count, 2)
        service.close()
        client.close()

    def test_http_server_supports_health_models_and_completions(self) -> None:
        session_count = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal session_count
            if request.url.path == "/api/sessions":
                session_count += 1
                return httpx.Response(200, json={"id": f"session-{session_count}"})
            if request.url.path == "/chat/stream":
                return httpx.Response(
                    200,
                    text=_success_stream("server answer"),
                    headers={"Content-Type": "text/event-stream"},
                )
            raise AssertionError(request.url)

        upstream = httpx.Client(transport=httpx.MockTransport(handler))
        service = GeniusService(_config(), client=upstream)
        with _running_server(service) as base_url:
            health = httpx.get(f"{base_url}/health")
            self.assertEqual(health.status_code, 200)
            self.assertTrue(health.json()["credential_configured"])
            self.assertEqual(health.json()["pid"], os.getpid())

            unauthorized = httpx.get(f"{base_url}/v1/models")
            self.assertEqual(unauthorized.status_code, 401)

            headers = {"Authorization": "Bearer local-key"}
            models = httpx.get(f"{base_url}/v1/models", headers=headers)
            self.assertEqual(models.json()["data"][0]["id"], "genius-agent")

            with patch.object(service, "complete", wraps=service.complete) as complete:
                completion = httpx.post(
                    f"{base_url}/v1/chat/completions",
                    headers={**headers, "X-Genius-Run-Id": "sweep-test", "X-Genius-Group-Id": "p0-agent-control", "X-Genius-Plugin-Id": "hijacking"},
                    json={"messages": [{"role": "user", "content": "probe"}]},
                )
                self.assertEqual(complete.call_args.args[0]["metadata"]["campaign"], {
                    "run_id": "sweep-test", "group_id": "p0-agent-control", "plugin_id": "hijacking",
                })
            self.assertEqual(completion.status_code, 200)
            self.assertEqual(
                completion.json()["choices"][0]["message"]["content"],
                "server answer",
            )

            streamed = httpx.post(
                f"{base_url}/v1/chat/completions",
                headers=headers,
                json={
                    "messages": [{"role": "user", "content": "probe"}],
                    "stream": True,
                },
            )
            self.assertEqual(streamed.status_code, 200)
            self.assertIn("data: [DONE]", streamed.text)
            self.assertIn("server answer", streamed.text)
        service.close()
        upstream.close()

    def test_upstream_rejection_is_not_reported_as_model_refusal(self) -> None:
        upstream = httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(403, json={"detail": "blocked"})
            )
        )
        service = GeniusService(_config(retries=0), client=upstream)
        with _running_server(service) as base_url:
            response = httpx.post(
                f"{base_url}/v1/chat/completions",
                headers={"Authorization": "Bearer local-key"},
                json={"messages": [{"role": "user", "content": "probe"}]},
            )
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["error"]["type"], "provider_rejection")
        self.assertNotIn("choices", response.json())
        service.close()
        upstream.close()

    def test_terminal_failed_event_is_upstream_error_not_provider_rejection(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/api/sessions":
                return httpx.Response(200, json={"id": "session-1"})
            if request.url.path == "/chat/stream":
                return httpx.Response(
                    200,
                    text=_sse({"status": "failed"}),
                    headers={"Content-Type": "text/event-stream"},
                )
            raise AssertionError(request.url)

        upstream = httpx.Client(transport=httpx.MockTransport(handler))
        service = GeniusService(_config(retries=0), client=upstream)
        with _running_server(service) as base_url:
            response = httpx.post(
                f"{base_url}/v1/chat/completions",
                headers={"Authorization": "Bearer local-key"},
                json={"messages": [{"role": "user", "content": "probe"}]},
            )
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["error"]["type"], "upstream_error")
        self.assertEqual(response.json()["error"]["code"], "genius_terminal_failed")
        service.close()
        upstream.close()

    def test_campaign_context_forces_settings_and_records_session(self) -> None:
        requests: list[dict[str, object]] = []
        with tempfile.TemporaryDirectory() as tmpdir:
            lifecycle = f"{tmpdir}/lifecycle.jsonl"
            trace = f"{tmpdir}/trace.jsonl"

            def handler(request: httpx.Request) -> httpx.Response:
                if request.url.path == "/api/sessions":
                    return httpx.Response(200, json={"id": "session-campaign"})
                if request.url.path == "/chat/stream":
                    requests.append(json.loads(request.content))
                    self.assertTrue(Path(lifecycle).exists())
                    return httpx.Response(
                        200,
                        text=_success_stream("campaign answer"),
                        headers={"Content-Type": "text/event-stream"},
                    )
                raise AssertionError(request.url)

            client = httpx.Client(transport=httpx.MockTransport(handler))
            config = _config(trace_path=trace)
            config = ShimConfig(
                **{
                    **config.__dict__,
                    "lifecycle_jsonl_path": lifecycle,
                    "upstream_retry_attempts": 2,
                }
            )
            service = GeniusService(config, client=client)
            _, result = service.complete(
                {
                    "messages": [{"role": "user", "content": "probe"}],
                    "metadata": {
                        "campaign": {
                            "campaign_id": "campaign-1",
                            "manifest_hash": "hash-1",
                            "sample_id": "sample-1",
                        }
                    },
                }
            )
            self.assertEqual(requests[0]["model_profile"], "default")
            self.assertEqual(requests[0]["reasoning_effort"], "xhigh")
            rows = [json.loads(line) for line in Path(lifecycle).read_text().splitlines()]
            self.assertEqual(rows[0]["kind"], "session_created")
            self.assertEqual(rows[0]["sample_id"], "sample-1")
            self.assertEqual(result.trace["turn_settings"]["reasoning_effort"], "xhigh")
            service.close()
            client.close()

    def test_canonical_session_creation_is_not_retried(self) -> None:
        calls = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            return httpx.Response(503, text="unavailable")

        client = httpx.Client(transport=httpx.MockTransport(handler))
        service = GeniusService(_config(retries=3), client=client)
        with self.assertRaises(Exception):
            service.complete(
                {
                    "messages": [{"role": "user", "content": "probe"}],
                    "metadata": {"campaign": {"campaign_id": "campaign-1"}},
                }
            )
        self.assertEqual(calls, 1)
        service.close()
        client.close()

    def test_model_resolution_and_cleanup_endpoints(self) -> None:
        paths: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            paths.append(request.url.path)
            if request.url.path.endswith("/models"):
                return httpx.Response(
                    200,
                    json={"models": [{"id": "default", "model": "qwen3.8-max"}]},
                )
            if request.url.path == "/api/sessions/batch-delete":
                self.assertEqual(json.loads(request.content)["session_ids"], ["s1"])
                return httpx.Response(200, json={"deleted": ["s1"]})
            if request.url.path == "/api/sessions":
                return httpx.Response(200, json={"sessions": [], "has_more": False})
            raise AssertionError(request.url)

        client = httpx.Client(transport=httpx.MockTransport(handler))
        config = _config()
        config = ShimConfig(**{**config.__dict__, "organization_id": "org-1"})
        service = GeniusService(config, client=client)
        self.assertEqual(service.resolve_model_profile()["model"], "qwen3.8-max")
        self.assertEqual(service.batch_delete_sessions(["s1"])[0], 200)
        self.assertFalse(service.session_exists("s1"))
        self.assertIn("/api/orgs/org-1/models", paths)
        service.close()
        client.close()


if __name__ == "__main__":
    unittest.main()
