from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path

import httpx

from viewer.server import ViewerHTTPServer, ViewerIndex, discover_sources, Source, _dual_gate_payload, _source_faithful_cases_payload, _eval_user_events, _link_trace_turns, _normalize_event


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def _make_root() -> Path:
    root = Path(tempfile.mkdtemp(prefix="genius-viewer-test-"))
    logs = root / "logs"
    _write_jsonl(
        logs / "genius_trace.jsonl",
        [
            {
                "kind": "genius_event",
                "timestamp": 2.0,
                "summary": {
                    "event_type": "content_delta",
                    "request_id": "global-request",
                    "raw": {"text": "global assistant"},
                },
            }
        ],
    )
    _write_jsonl(
        logs / "genius_session_lifecycle.jsonl",
        [
            {
                "kind": "session_created",
                "timestamp": 1.0,
                "upstream_session_id": "global-session",
            },
            {
                "kind": "request_completed",
                "timestamp": 3.0,
                "upstream_session_id": "global-session",
                "request_id": "global-request",
                "outcome": "completed",
            },
        ],
    )

    run_dir = root / "sweeps" / "p0" / "hijacking" / "runs" / "2026-09-12T10-00-00"
    _write_jsonl(
        run_dir / "genius_trace.jsonl",
        [
            {
                "kind": "genius_event",
                "timestamp": 5.0,
                "summary": {
                    "event_type": "reasoning_delta",
                    "request_id": "sweep-request",
                    "raw": {"text": "sweep reasoning"},
                },
            },
            {
                "kind": "genius_event",
                "timestamp": 6.0,
                "summary": {
                    "event_type": "tool_call",
                    "request_id": "sweep-request",
                    "tool_name": "team_delete",
                    "tool_input": {"team_id": "team-1"},
                    "tool_result": {"status": "awaiting_user_confirmation"},
                },
            },
        ],
    )
    _write_jsonl(
        run_dir / "genius_session_lifecycle.jsonl",
        [
            {
                "kind": "session_created",
                "timestamp": 4.0,
                "upstream_session_id": "sweep-session",
                "run_id": "sweep-run",
            },
            {
                "kind": "approval_observed",
                "timestamp": 7.0,
                "upstream_session_id": "sweep-session",
                "request_id": "sweep-request",
                "approval": {
                    "confirmation_id": "confirm-1",
                    "tool": "team_delete",
                    "prompt": "Delete team?",
                },
            },
            {
                "kind": "request_completed",
                "timestamp": 8.0,
                "upstream_session_id": "sweep-session",
                "request_id": "sweep-request",
                "outcome": "completed_after_approval",
            },
        ],
    )
    _write_jsonl(
        run_dir / "oracle.jsonl",
        [
            {
                "kind": "oracle",
                "timestamp": 7.5,
                "request_id": "sweep-request",
                "outcome": "team_deleted",
            }
        ],
    )
    (run_dir / "eval.json").write_text(
        json.dumps(
            {
                "kind": "eval",
                "request_id": "sweep-request",
                "results": [{"pass": True}],
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "run-manifest.json").write_text(
        json.dumps(
            {
                "run_id": "sweep-run",
                "group_id": "p0",
                "plugin_id": "hijacking",
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "summary.md").write_text("# Sweep summary\n", encoding="utf-8")
    project = Path(__file__).resolve().parents[1]
    source = project / "skill-suites/benchmark-multi-risk"
    target = root / "skill-suites/benchmark-multi-risk"
    target.mkdir(parents=True)
    for name in ("dual-gate-screening.json", "dual-gate-trajectories.json",
                 "risk-family-map.json", "source-category-catalogue.json",
                 "source-registry.json", "formal-category-selection.json"):
        shutil.copy2(source / name, target / name)
    shutil.copytree(source / "source-faithful-cases-v1",
                    target / "source-faithful-cases-v1")
    return root


class ViewerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = _make_root()
        self.index = ViewerIndex(self.root)
        self.server = ViewerHTTPServer(("127.0.0.1", 0), self.index)
        self.thread = threading.Thread(
            target=self.server.serve_forever,
            daemon=True,
        )
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"
        self.client = httpx.Client()

    def tearDown(self) -> None:
        self.client.close()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def test_source_discovery_finds_global_and_sweep_runs(self) -> None:
        sources = discover_sources(self.root)
        self.assertEqual(
            [(source.kind, source.run_id) for source in sources],
            [("global", "global-logs"), ("sweep", "sweep-run")],
        )

    def test_index_parses_sessions_requests_and_events(self) -> None:
        self.assertEqual(len(self.index.runs), 2)
        self.assertEqual(len(self.index.sessions), 2)
        self.assertEqual(len(self.index.requests), 2)
        self.assertEqual(len(self.index.events), 10)
        self.assertIn("sweep-run", self.index.runs)
        self.assertIn("sweep-session", self.index.sessions)
        self.assertIn("sweep-request", self.index.requests)

    def test_timeline_order_is_timestamp_sorted(self) -> None:
        timestamps = [event["timestamp"] for event in self.index.events]
        self.assertEqual(timestamps, sorted(timestamps))

    def test_static_frontend_is_served(self) -> None:
        response = self.client.get(f"{self.base_url}/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Genius Trace Viewer", response.text)
        styles = self.client.get(f"{self.base_url}/styles.css")
        self.assertEqual(styles.status_code, 200)
        script = self.client.get(f"{self.base_url}/app.js")
        self.assertEqual(script.status_code, 200)
        risks = self.client.get(f"{self.base_url}/risks.html")
        self.assertEqual(risks.status_code, 200)
        self.assertIn("Genius Skill 风险轨迹", risks.text)
        self.assertEqual(self.client.get(f"{self.base_url}/risks.js").status_code, 200)
        self.assertEqual(self.client.get(f"{self.base_url}/risks.css").status_code, 200)
        cases = self.client.get(f"{self.base_url}/cases.html")
        self.assertEqual(cases.status_code, 200)
        self.assertIn("Genius Skill Case 审查", cases.text)
        self.assertEqual(self.client.get(f"{self.base_url}/cases.js").status_code, 200)
        self.assertEqual(self.client.get(f"{self.base_url}/cases.css").status_code, 200)

    def test_dual_gate_review_api_joins_frozen_artifacts(self) -> None:
        payload = self.client.get(f"{self.base_url}/api/dual-gate").json()
        self.assertEqual(payload["status"], "ready-for-user-dual-gate-review")
        self.assertEqual(payload["counts"]["observed_success"], 0)
        self.assertEqual(payload["counts"]["source_faithful_testable"], 23)
        b_only = [row for row in payload["families"]
                  if row["family_id"] in payload["quadrants"]["b_only"]]
        self.assertEqual(len(b_only), 23)
        self.assertTrue(all(row["trajectory"]["executable_payload"] is False
                            for row in b_only))
        self.assertEqual(payload["new_online_calls"],
                         {"target": 0, "generation": 0, "judge": 0})

    def test_source_faithful_case_api_exposes_23_offline_blueprints(self) -> None:
        payload = self.client.get(f"{self.base_url}/api/source-faithful-cases").json()
        self.assertEqual((payload["case_count"], payload["family_count"]), (23, 23))
        self.assertEqual(payload["carrier_counts"], {"catalogue-selection": 1,
            "package-asset": 4, "package-script": 9, "text-skill": 9})
        self.assertTrue(all(case["genius_case"]["payload_status"] ==
                            "blueprint-no-executable-payload" for case in payload["cases"]))
        self.assertEqual((payload["target_calls"], payload["generation_calls"],
                          payload["judge_calls"]), (0, 0, 0))

    def test_api_index_run_session_and_request_routes(self) -> None:
        index = self.client.get(f"{self.base_url}/api/index").json()
        self.assertEqual(index["event_count"], 10)
        self.assertEqual(len(index["runs"]), 2)

        run = self.client.get(
            f"{self.base_url}/api/run/sweep-run"
        ).json()
        self.assertEqual(run["group_id"], "p0")
        self.assertEqual(run["plugin_id"], "hijacking")

        session = self.client.get(
            f"{self.base_url}/api/session/sweep-session"
        ).json()
        self.assertEqual(len(session["events"]), 7)

        request = self.client.get(
            f"{self.base_url}/api/request/sweep-request"
        ).json()
        self.assertEqual(len(request["events"]), 6)
        self.assertEqual(request["outcome"], "completed_after_approval")

    def test_api_filters_and_search(self) -> None:
        filtered = self.client.get(
            f"{self.base_url}/api/index",
            params={"run_id": "sweep-run"},
        ).json()
        self.assertEqual(filtered["event_count"], 7)

        tool_filtered = self.client.get(
            f"{self.base_url}/api/index",
            params={"tool_name": "team_delete"},
        ).json()
        self.assertEqual(tool_filtered["event_count"], 1)

        search = self.client.get(
            f"{self.base_url}/api/index",
            params={"q": "sweep reasoning"},
        ).json()
        self.assertEqual(search["event_count"], 1)

    def test_api_event_route_returns_raw_json(self) -> None:
        event = next(
            event
            for event in self.index.events
            if event["category"] == "approval"
        )
        response = self.client.get(
            f"{self.base_url}/api/event/{event['event_id']}"
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["confirmation_id"], "confirm-1")

    def test_local_only_and_read_only_boundaries(self) -> None:
        with self.assertRaisesRegex(ValueError, "127.0.0.1"):
            ViewerHTTPServer(("0.0.0.0", 0), self.index)
        self.assertEqual(self.client.post(f"{self.base_url}/api/index").status_code, 501)
        self.assertEqual(self.client.get(f"{self.base_url}/.env").status_code, 404)
        self.assertIn("connect-src 'self'", self.client.get(self.base_url).headers["content-security-policy"])

    def test_real_wire_shapes_preserve_tool_input_reply_and_whitespace(self) -> None:
        from viewer.server import Source, _normalize_event
        source = Source(self.root / "logs", "global", "wire", "logs", "wire")
        tool = _normalize_event(source, "trace", 1, {
            "kind": "genius_event", "summary": {"event_type": "reasoning_delta",
            "raw": {"tool": "team_delete", "id": "call-1", "input": {"team_id": "[REDACTED]"}}}})
        self.assertEqual(tool["category"], "tool")
        self.assertEqual(tool["tool_input"], {"team_id": "[REDACTED]"})
        reply = _normalize_event(source, "trace", 2, {
            "kind": "genius_event", "summary": {"event_type": "completed",
            "raw": {"reply": "## Completed\n\n**Done**"}}})
        self.assertIn("**Done**", reply["text"])
        chunk = _normalize_event(source, "trace", 3, {
            "kind": "genius_event", "summary": {"event_type": "reasoning_delta", "raw": {"text": " next "}}})
        self.assertEqual(chunk["text"], " next ")
        end = _normalize_event(source, "trace", 4, {
            "kind": "request_completed", "trace": {"request_id": "r", "upstream_session_id": "s", "outcome": "completed"}})
        self.assertEqual((end["request_id"], end["session_id"], end["outcome"]), ("r", "s", "completed"))

    def test_browser_refinement_interactions(self) -> None:
        run = self.root / "sweeps/p0/hijacking/runs/2026-09-12T10-00-00"
        path = run / "genius_trace.jsonl"
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        rows += [
            {"kind": "user_message", "timestamp": 4.2, "request_id": "sweep-request", "text": "请展示本地回放"},
            {"kind": "genius_event", "timestamp": 9, "request_id": "sweep-request", "summary": {
                "event_type": "completed", "raw": {"reply": '## 回放标题\n\n**重点** 与 `code`\n\n<img src="https://invalid.example/x" onerror="alert(1)">\n\n[引用](https://invalid.example)'}}},
        ]
        rows += [{"kind": "status", "timestamp": 10 + i, "request_id": "sweep-request", "text": f"Recorded event {i}"} for i in range(135)]
        _write_jsonl(path, rows)
        lifecycle = run / "genius_session_lifecycle.jsonl"
        rows = [json.loads(line) for line in lifecycle.read_text().splitlines()]
        rows += [{"kind": kind, "timestamp": 7.1 + i / 10, "request_id": "sweep-request", "upstream_session_id": "sweep-session", "approval": {"confirmation_id": "confirm-1"}, "outcome": outcome} for i, (kind, outcome) in enumerate([
            ("approval_policy_decision", "approved"), ("approval_protocol_submit", "submitted"), ("approval_terminal_result", "completed_after_approval")])]
        _write_jsonl(lifecycle, rows)
        self.server.index = ViewerIndex(self.root)
        result = subprocess.run(["node", "tests/viewer_browser_qa.cjs", self.base_url], capture_output=True, text=True, timeout=60, cwd=Path(__file__).resolve().parents[1])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_risk_review_browser_interactions(self) -> None:
        result = subprocess.run(
            ["node", "tests/risk_viewer_browser_qa.cjs", self.base_url],
            capture_output=True, text=True, timeout=60,
            cwd=Path(__file__).resolve().parents[1],
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_case_review_browser_interactions(self) -> None:
        result = subprocess.run(
            ["node", "tests/case_viewer_browser_qa.cjs", self.base_url],
            capture_output=True, text=True, timeout=60,
            cwd=Path(__file__).resolve().parents[1],
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_deep_link_restores_selected_session(self) -> None:
        script = r"""
const { chromium } = require('playwright');
(async () => {
  const browser = await chromium.launch({
    headless: true,
    executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
  });
  const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
  await page.goto(process.argv[1], { waitUntil: 'networkidle' });
  const text = await page.locator('#timeline-title').textContent();
  console.log(text);
  await browser.close();
})();
"""
        result = subprocess.run(
            ["node", "-e", script, f"{self.base_url}/?session_id=sweep-session"],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=Path(__file__).resolve().parents[1],
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("sweep-session", result.stdout)


class UserTurnRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.run = self.root / "sweeps/p0/hijacking/runs/sample"
        self.run.mkdir(parents=True)
        (self.run / "run-manifest.json").write_text(json.dumps({"run_id": "user-turn-run", "group_id": "p0", "plugin_id": "hijacking"}))
        self.source = Source(self.run, "sweep", "user-turn-run", "p0", "hijacking")
        self.trace = [
            {"kind": "request_started", "timestamp": 10, "upstream_session_id": "failed-session"},
            {"kind": "genius_event", "timestamp": 11, "summary": {"event_type": "reasoning_delta", "request_id": "failed-request", "raw": {"text": "thinking"}}},
            {"kind": "request_failed", "timestamp": 12.2, "trace_summary": {"request_id": "failed-request", "outcome": "upstream_failed"}},
            {"kind": "request_started", "timestamp": 20, "upstream_session_id": "ok-session"},
            {"kind": "genius_event", "timestamp": 21, "summary": {"event_type": "completed", "raw": {"reply": "exact response"}}},
            {"kind": "request_completed", "timestamp": 22.2, "trace": {"request_id": "ok-request", "upstream_session_id": "ok-session", "outcome": "completed"}},
        ]
        self.rows = [
            {"prompt": {"raw": "first user turn"}, "response": {"error": 'API error: 502\n{"genius_trace_summary":{"request_id":"failed-request"}}'}},
            {"prompt": {"raw": "second user turn"}, "response": {"output": "exact response"}},
        ]

    def build(self) -> ViewerIndex:
        _write_jsonl(self.run / "genius_trace.jsonl", self.trace)
        _write_jsonl(self.run / "session_lifecycle.jsonl", [{"kind": "session_created", "timestamp": 9, "upstream_session_id": "failed-session"}])
        (self.run / "eval.json").write_text(json.dumps({"results": {"results": self.rows}}))
        return ViewerIndex(self.root)

    def test_restores_failed_and_successful_inputs_without_using_eval_order(self) -> None:
        self.rows.reverse()
        index = self.build()
        users = [e for e in index.events if e["category"] == "user"]
        self.assertEqual([(e["text"], e["session_id"], e["request_id"]) for e in users], [
            ("first user turn", "failed-session", "failed-request"),
            ("second user turn", "ok-session", "ok-request"),
        ])
        self.assertTrue(all(e["raw"]["origin"] == "promptfoo_eval" for e in users))
        self.assertTrue(any(e["source_file"] == "lifecycle" for e in index.events))
        for user in users:
            start = next(e for e in index.events if e["kind"] == "request_started" and e["request_id"] == user["request_id"])
            self.assertLess(index.events.index(user), index.events.index(start))
        failed_events = [e for e in index.events if e.get("request_id") == "failed-request"]
        self.assertTrue(all(e["session_id"] == "failed-session" for e in failed_events))

    def test_truncated_reply_uses_unique_response_http_date(self) -> None:
        self.rows[1]["response"] = {"output": "exact response plus a truncated tail", "metadata": {"http": {"headers": {"date": "Thu, 01 Jan 1970 00:00:22 GMT"}}}}
        users = [e for e in self.build().events if e["category"] == "user"]
        self.assertEqual(users[1]["request_id"], "ok-request")
        self.assertEqual(users[1]["raw"]["association"], "response_http_date")

    def test_native_user_event_prevents_duplicate_eval_recovery(self) -> None:
        self.trace.insert(0, {"kind": "user_message", "timestamp": 9.9, "text": "first user turn", "origin": "local_shim", "local_turn_id": "turn-1", "upstream_session_id": "failed-session"})
        for row in self.trace[1:4]:
            row["local_turn_id"] = "turn-1"
        users = [e for e in self.build().events if e["category"] == "user"]
        self.assertEqual(len(users), 2)
        self.assertEqual(users[0]["raw"]["origin"], "local_shim")
        self.assertEqual(users[0]["request_id"], "failed-request")

    def test_unmatched_input_is_visible_but_never_assigned_by_position(self) -> None:
        self.rows[1]["response"] = {"output": "unmatched response"}
        users = [e for e in self.build().events if e["category"] == "user"]
        unmatched = next(e for e in users if e["text"] == "second user turn")
        self.assertIsNone(unmatched["request_id"])
        self.assertIsNone(unmatched["session_id"])
        self.assertEqual(unmatched["raw"]["association"], "unmatched")

    def test_overlapping_requests_do_not_inherit_serial_session_association(self) -> None:
        raw = [self.trace[i] for i in (0, 3, 1, 2, 4, 5)]
        events = [_normalize_event(self.source, "trace", i, r) for i, r in enumerate(raw)]
        _link_trace_turns(events)
        self.assertIsNone(events[2]["session_id"])
        self.assertIsNone(events[3]["session_id"])


class MultiRiskPilotViewerTests(unittest.TestCase):
    def test_discovers_pilot_and_enriches_source_license_reuse_and_hash_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            base = root / "skill-suites/benchmark-multi-risk"
            case_id = "script-drop"
            (base / "risk-cards").mkdir(parents=True)
            (base / "pilot-cases" / case_id).mkdir(parents=True)
            registry = {"sources": [
                {"source_id": "malskillbench", "repository_url": "https://github.com/example/mal",
                 "license_disposition": "academic-research-only"},
                {"source_id": "skillsbench", "repository_url": "https://github.com/example/benign",
                 "license_disposition": "confirmed-open"}]}
            (base / "source-registry.json").write_text(json.dumps(registry))
            card = {"risk_family": "malicious-script-drop", "disposition": "eligible-for-pilot",
                    "sources": [{"source_id": "malskillbench", "reuse_tier": "pattern-only"},
                                {"source_id": "skillsbench", "reuse_tier": "minimal-adaptation"}]}
            (base / "risk-cards" / f"{case_id}.json").write_text(json.dumps(card))
            adaptation = {"source_assets": [{"path": "Core/taxonomy/behaviors.py",
                                              "content_hash": "a" * 40}],
                          "adapted_files": [{"sha256": "b" * 64}]}
            (base / "pilot-cases" / case_id / "adaptation.json").write_text(json.dumps(adaptation))
            case = {"source_adaptations": [{"file": "adaptation.json"}]}
            (base / "pilot-cases" / case_id / "case.json").write_text(json.dumps(case))
            run = base / "runs/pilot-a124"
            run.mkdir(parents=True)
            (run / "run-manifest.json").write_text(json.dumps({"kind": "skill-multi-risk-pilot-run",
                "run_id": "pilot-a124", "target_context": "global-general", "session_type": "general"}))
            _write_jsonl(run / "genius_trace.jsonl", [{"kind": "request_completed", "timestamp": 1,
                "case_id": case_id, "risk_family": "malicious-script-drop", "variant": "normal",
                "row_id": "default-normal", "upstream_session_id": "chat:usr:a124",
                "trace": {"request_id": "request-a124", "upstream_session_id": "chat:usr:a124"}}])
            result_dir = run / case_id
            result_dir.mkdir()
            (result_dir / "pilot-result.json").write_text(json.dumps({"case_id": case_id,
                "risk_family": "malicious-script-drop", "rows": [{"model_profile": "default",
                "variant": "normal", "status": "normal-valid", "source_verified": True,
                "task_valid": True, "independent_effect_observed": False}]}))
            index = ViewerIndex(root)
            self.assertEqual(next(source for source in index.sources if source.run_id == "pilot-a124").kind,
                             "skill-pilot")
            event = next(event for event in index.events if event["source_file"] == "pilot-result")
            self.assertEqual(event["source_id"], "malskillbench,skillsbench")
            self.assertEqual(event["risk_family"], "malicious-script-drop")
            self.assertEqual(event["reuse_tier"], "pattern-only,minimal-adaptation")
            self.assertEqual(event["license_disposition"],
                             "academic-research-only,confirmed-open")
            self.assertEqual(event["evaluation_stage"], "pilot")
            self.assertEqual(event["original_hash"], "a" * 40)
            self.assertEqual(event["adapted_hash"], "b" * 64)


if __name__ == "__main__":
    unittest.main()
