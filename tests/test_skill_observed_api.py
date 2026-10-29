"""Contract tests for the control endpoints observed in general A/B receipts."""
from __future__ import annotations

import hashlib
import unittest
from pathlib import Path
import tempfile
from urllib.parse import quote

from skill_suite.budget import Ledger
from skill_suite.observed_api import ObservedGeneralControl
from skill_suite.orchestration import FIXTURE_LIMITS


PRINCIPAL = "usr_fixture123"
SESSION = "chat:usr_fixture123:abc123"
SKILL = "skill-fixture123"
NAME = "reading-notes-a124b5c6"
CONTENT = "# 资料整理\n只读汇总数量。"


class FakeObservedControl:
    def __init__(self):
        self.calls = []
        self.artifact = None
        self.skill = {"skill_id": SKILL, "name": NAME, "instructions": CONTENT,
                      "owner_id": PRINCIPAL, "source": "user", "visibility": "private",
                      "mode": "text", "scripts": [], "needs_credentials": [],
                      "version": 1, "shared_with_count": 0}
        self.sharing = {"skill_id": SKILL, "scope": "private", "members": []}

    def request(self, label, method, path, body):
        self.calls.append((label, method, path, body))
        if (method, path) == ("POST", "/api/skills"):
            return {"skill_id": SKILL, "skill": dict(self.skill), "revision_id": "revision-a124"}
        if (method, path) == ("GET", "/api/skills/" + SKILL):
            return {"skill": dict(self.skill)}
        if (method, path) == ("GET", "/api/skills/" + SKILL + "/sharing"):
            return dict(self.sharing)
        if (method, path) == ("POST", "/api/sessions"):
            return {"session_id": SESSION, "user_id": PRINCIPAL, "session_type": "general"}
        if (method, path) == ("GET", "/api/sessions/" + quote(SESSION, safe="") + "/artifacts"):
            return {"artifacts": [dict(self.artifact)] if self.artifact else []}
        if (method, path) == ("DELETE", "/api/sessions/" + quote(SESSION, safe="") + "/artifacts"):
            self.artifact = None
            return {"deleted": 1}
        raise AssertionError("unobserved operation: " + method + " " + path)


class ObservedGeneralControlContract(unittest.TestCase):
    def setUp(self):
        self.fake = FakeObservedControl()
        self.adapter = ObservedGeneralControl(self.fake.request, PRINCIPAL, "case-a124")

    def test_exact_observed_private_skill_and_general_session_chain(self):
        created = self.adapter.create_skill(NAME, CONTENT)
        self.assertEqual(created["skill_id"], SKILL)
        self.assertEqual(self.adapter.read_skill(SKILL)["instructions"], CONTENT)
        self.assertEqual(self.adapter.create_session()["session_id"], SESSION)
        self.fake.artifact = {"id": "asset-a124", "scope_id": SESSION,
                              "filename": "reading-note-a124.md", "file_token": "token-a124"}
        self.assertEqual(len(self.adapter.list_artifacts(SESSION)["artifacts"]), 1)
        self.assertEqual(self.adapter.delete_artifact(SESSION, "asset-a124"), {"deleted": 1})
        self.assertEqual([row[1] for row in self.fake.calls],
                         ["POST", "GET", "GET", "POST", "GET", "DELETE"])
        self.assertEqual(self.fake.calls[0][3], {"name": NAME, "instructions": CONTENT,
            "description": "用于整理资料数量的操作说明", "category": "other",
            "tags": [], "stage": "", "priority": "medium", "needs_credentials": []})
        self.assertEqual(self.fake.calls[3][3], {"session_type": "general"})
        self.assertEqual(self.fake.calls[-1][3], {"ids": ["asset-a124"]})
        self.assertEqual(len({row[0] for row in self.fake.calls}), 6)

    def test_private_sharing_and_content_are_verified(self):
        self.adapter.create_skill(NAME, CONTENT)
        self.fake.sharing["scope"] = "organization"
        with self.assertRaisesRegex(ValueError, "sharing/version drift"):
            self.adapter.read_skill(SKILL)
        self.fake.sharing["scope"] = "private"
        self.fake.skill["instructions"] = "changed"
        with self.assertRaisesRegex(ValueError, "identity/content drift"):
            self.adapter.read_skill(SKILL)

    def test_foreign_session_and_duplicate_are_rejected_before_http(self):
        with self.assertRaisesRegex(ValueError, "not owned"):
            self.adapter.list_artifacts("chat:usr_other:abc")
        self.assertEqual(self.fake.calls, [])
        self.adapter.create_session()
        count = len(self.fake.calls)
        with self.assertRaisesRegex(ValueError, "identity drift"):
            self.adapter.create_session()
        self.assertEqual(len(self.fake.calls), count + 1)

    def test_unregistered_skill_and_unneutral_name_are_rejected_before_http(self):
        with self.assertRaisesRegex(ValueError, "not owned"):
            self.adapter.read_skill(SKILL)
        with self.assertRaises(ValueError):
            self.adapter.create_skill("TEST-skill", CONTENT)
        self.assertEqual(self.fake.calls, [])

    def test_second_skill_read_http_is_budgeted_before_submission(self):
        with tempfile.TemporaryDirectory() as temporary:
            limits = {**FIXTURE_LIMITS, "management": 2}
            ledger = Ledger(Path(temporary) / "ledger.json", limits)
            self.adapter.bind_fixture_ledger(ledger)
            self.adapter.create_skill(NAME, CONTENT)
            with self.assertRaisesRegex(Exception, "management budget exceeded"):
                self.adapter.read_skill(SKILL)
            self.assertEqual([row[1] for row in self.fake.calls], ["POST", "GET"])
            self.assertEqual(ledger.state["counts"]["management"], 2)

    def test_live_byte_callback_must_match_listed_capability_and_receipt(self):
        body = b"fixture bytes"
        def downloader(session_id, artifact_id, filename, token):
            self.assertEqual((session_id, artifact_id, filename, token),
                (SESSION, "asset-a124", "reading-note-a124.md", "token-a124"))
            return body, {"kind": "session-artifact-download", "status": "completed",
                "session_id": session_id, "artifact_id": artifact_id,
                "filename": filename, "file_token_sha256": hashlib.sha256(token.encode()).hexdigest(),
                "content_sha256": hashlib.sha256(body).hexdigest()}
        adapter = ObservedGeneralControl(self.fake.request, PRINCIPAL, "case-a124",
                                         live_file_downloader=downloader)
        adapter.create_session()
        self.fake.artifact = {"id": "asset-a124", "scope_id": SESSION,
                              "filename": "reading-note-a124.md", "file_token": "token-a124"}
        adapter.list_artifacts(SESSION)
        self.assertEqual(adapter.download("token-a124"), body)
        adapter.delete_artifact(SESSION, "asset-a124")
        with self.assertRaisesRegex(ValueError, "not from an owned listed artifact"):
            adapter.download("token-a124")


if __name__ == "__main__":
    unittest.main()
