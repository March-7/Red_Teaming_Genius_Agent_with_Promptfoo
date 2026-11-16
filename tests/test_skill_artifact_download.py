"""Observed artifact byte endpoint, bounded readback and attempt accounting."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

import httpx

from skill_suite.artifact_download import download_artifact
from skill_suite.budget import Ledger
from skill_suite.orchestration import FIXTURE_LIMITS


SESSION = "chat:usr_fixture123:a124b5c6"
ARTIFACT = "asset-a124"
NAME = "reading-note-a124.md"
TOKEN = "opaque-capability-a124"
AUTH = "fixture-auth-a124"


class ArtifactDownloadContract(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.calls = 0
        self.response_status = 200
        self.response_content = "资料摘要归档".encode()
        def respond(request):
            self.calls += 1
            self.assertEqual(request.method, "GET")
            self.assertEqual(request.url.scheme, "https")
            self.assertEqual(request.url.host, "genius.example.invalid")
            self.assertEqual(request.url.path, "/api/files/download")
            self.assertEqual(set(request.url.params), {"token", "auth_token"})
            self.assertEqual(request.url.params["token"], TOKEN)
            self.assertEqual(request.url.params["auth_token"], AUTH)
            self.assertEqual(request.headers["Authorization"], "Bearer " + AUTH)
            return httpx.Response(self.response_status, content=self.response_content)
        client = httpx.Client(transport=httpx.MockTransport(respond))
        self.addCleanup(client.close)
        self.service = SimpleNamespace(_client=client,
            config=SimpleNamespace(upstream_base_url="https://genius.example.invalid"),
            credentials=SimpleNamespace(raw_token=AUTH),
            _headers=lambda: {"Authorization": "Bearer " + AUTH})
        self.ledger = Ledger(self.root / "ledger.json",
                             {**FIXTURE_LIMITS, "management": 1, "recovery": 0})

    def invoke(self):
        return download_artifact(self.service, self.ledger, self.root, "artifact-read-a124",
            session_id=SESSION, artifact_id=ARTIFACT, filename=NAME, file_token=TOKEN)

    def test_exact_endpoint_bytes_hash_and_zero_retry(self):
        body, receipt = self.invoke()
        self.assertEqual(body, self.response_content)
        self.assertEqual(receipt["content_sha256"], hashlib.sha256(body).hexdigest())
        self.assertEqual(receipt["body_ref"]["sha256"], receipt["content_sha256"])
        self.assertEqual((self.root / receipt["body_ref"]["file"]).read_bytes(), body)
        saved = (self.root / "artifact-read-a124.json").read_text()
        self.assertNotIn(TOKEN, saved)
        self.assertNotIn(AUTH, saved)
        self.assertEqual(self.ledger.state["counts"]["management"], 1)
        with self.assertRaisesRegex(ValueError, "no retry"):
            self.invoke()
        self.assertEqual(self.calls, 1)

    def test_http_error_and_large_body_stop_without_replay(self):
        self.response_status = 302
        with self.assertRaisesRegex(ValueError, "status mismatch"):
            self.invoke()
        saved = json.loads((self.root / "artifact-read-a124.json").read_text())
        self.assertEqual(saved["status"], "error")
        self.assertEqual(saved["http_status"], 302)
        self.assertFalse((self.root / "artifact-read-a124.bin").exists())
        self.assertEqual(self.ledger.state["counts"]["management"], 1)
        self.assertTrue(self.ledger.state["stopped"])
        with self.assertRaisesRegex(ValueError, "no retry"):
            self.invoke()
        self.assertEqual(self.calls, 1)

    def test_oversized_body_is_rejected_after_one_counted_http_attempt(self):
        self.response_content = b"x" * 4097
        with self.assertRaisesRegex(ValueError, "exceeds"):
            self.invoke()
        self.assertEqual(self.ledger.state["counts"]["management"], 1)
        self.assertTrue(self.ledger.state["stopped"])
        self.assertFalse((self.root / "artifact-read-a124.bin").exists())


if __name__ == "__main__":
    unittest.main()
