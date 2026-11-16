"""Exact observed Genius control-plane operations for a private general Skill case.

The injected request callable must persist and meter each HTTP attempt, as
ManagementSession.request does. This module never loads credentials or sends a
request on its own. Target routing remains a separate campaign gate.
"""
from __future__ import annotations

import hashlib
from typing import Any, Callable
from urllib.parse import quote

from sweep.resource_naming import validate_neutral_resource_name
from .schema import identifier, text_hash


Request = Callable[[str, str, str, dict[str, Any] | None], dict[str, Any]]


class ObservedGeneralControl:
    """Validate observed private Skill, general session and artifact responses."""

    def __init__(self, request: Request, principal_id: str, operation_prefix: str,
                 *, fixture_target_runner=None, fixture_file_downloader=None,
                 live_file_downloader=None):
        if fixture_file_downloader is not None and live_file_downloader is not None:
            raise ValueError("one artifact download transport required")
        self.request = request
        self.principal_id = identifier(principal_id, "principal_id")
        self.prefix = identifier(operation_prefix, "operation_prefix")
        self._sequence = 0
        self._skills: dict[str, tuple[str, str, str]] = {}
        self._sessions: set[str] = set()
        self._artifacts: dict[str, set[str]] = {}
        self._tokens: dict[str, tuple[str, str, str]] = {}
        self._fixture_ledger = None
        self.fixture_http_metered = False
        self._fixture_target_runner = fixture_target_runner
        self._fixture_file_downloader = fixture_file_downloader
        self._live_file_downloader = live_file_downloader
        self.operations: dict[str, str] = {}

    def bind_fixture_ledger(self, ledger) -> None:
        """Meter each injected fake HTTP attempt; never bind a live manager twice."""
        if self._fixture_ledger is not None:
            raise ValueError("fixture ledger already bound")
        self._fixture_ledger = ledger
        self.fixture_http_metered = True

    def _attempt(self, label: str, kind: str, callback):
        self._sequence += 1
        operation = f"{self.prefix}-{self._sequence:03d}-{label}"
        if self._fixture_ledger is not None:
            self._fixture_ledger.reserve(kind, operation)
        try:
            value = callback(operation)
            if self._fixture_ledger is not None:
                self._fixture_ledger.finish(operation, "completed")
            return value
        except Exception:
            if self._fixture_ledger is not None:
                self._fixture_ledger.finish(operation, "adapter-error")
            raise

    def _call(self, label: str, method: str, path: str,
              body: dict[str, Any] | None = None) -> dict[str, Any]:
        result = self._attempt(label, "cleanup" if label == "delete-artifact" else "management",
                               lambda operation: self._submit(operation, label, method, path, body))
        if not isinstance(result, dict):
            raise ValueError("observed control-plane response must be an object")
        return result

    def _submit(self, operation: str, label: str, method: str, path: str,
                body: dict[str, Any] | None) -> dict[str, Any]:
        self.operations[label] = operation
        return self.request(operation, method, path, body)

    def adopt_session(self, response: dict[str, Any]) -> str:
        """Adopt a freshly metered POST /api/sessions response for this principal."""
        session_id = response.get("session_id") if isinstance(response, dict) else None
        if (not isinstance(session_id, str)
                or not session_id.startswith("chat:" + self.principal_id + ":")
                or response.get("user_id") != self.principal_id
                or response.get("session_type") != "general"
                or session_id in self._sessions):
            raise ValueError("native general session identity drift")
        self._sessions.add(session_id)
        return session_id

    def create_skill(self, name: str, content: str) -> dict[str, Any]:
        validate_neutral_resource_name(name)
        if not isinstance(content, str) or not content.strip() or len(content) > 50000:
            raise ValueError("Skill content must be bounded text")
        body = {"name": name, "instructions": content,
                "description": "用于整理资料数量的操作说明", "category": "other",
                "tags": [], "stage": "", "priority": "medium", "needs_credentials": []}
        response = self._call("create-skill", "POST", "/api/skills", body)
        skill_id, skill = response.get("skill_id"), response.get("skill")
        identifier(skill_id, "skill_id")
        if not isinstance(skill, dict) or skill.get("skill_id") != skill_id:
            raise ValueError("Skill creation did not return its identity")
        self._validate_skill(skill, skill_id, name, content, require_count=False)
        self._skills[skill_id] = (name, content, str(skill["version"]))
        return {"skill_id": skill_id, "name": name, "instructions": content,
                "visibility": "private", "owner_id": self.principal_id,
                "version": skill["version"]}

    def _validate_skill(self, skill: dict[str, Any], skill_id: str, name: str,
                        content: str, *, require_count: bool) -> None:
        if (skill.get("skill_id") != skill_id or skill.get("name") != name
                or skill.get("instructions") != content
                or skill.get("owner_id") != self.principal_id
                or skill.get("source") != "user" or skill.get("visibility") != "private"
                or skill.get("mode") != "text" or skill.get("scripts")
                or skill.get("needs_credentials")
                or type(skill.get("version")) is not int or skill["version"] < 1
                or (require_count and skill.get("shared_with_count") != 0)):
            raise ValueError("private Skill identity/content drift")

    def read_skill(self, skill_id: str) -> dict[str, Any]:
        if skill_id not in self._skills:
            raise ValueError("Skill is not owned by this provisioner")
        name, content, version = self._skills[skill_id]
        path = "/api/skills/" + quote(skill_id, safe="")
        response = self._call("read-skill", "GET", path)
        skill = response.get("skill")
        if not isinstance(skill, dict):
            raise ValueError("Skill readback missing")
        self._validate_skill(skill, skill_id, name, content, require_count=True)
        sharing = self._call("read-sharing", "GET", path + "/sharing")
        if (sharing.get("skill_id") != skill_id or sharing.get("scope") != "private"
                or sharing.get("members") != [] or str(skill["version"]) != version):
            raise ValueError("Skill sharing/version drift")
        return {"skill_id": skill_id, "name": name, "instructions": content,
                "visibility": "private", "owner_id": self.principal_id,
                "version": skill["version"]}

    def create_session(self) -> dict[str, Any]:
        response = self._call("create-session", "POST", "/api/sessions",
                              {"session_type": "general"})
        self.adopt_session(response)
        return response

    def list_artifacts(self, session_id: str) -> dict[str, Any]:
        self._owned_session(session_id)
        response = self._call("list-artifacts", "GET",
                              "/api/sessions/" + quote(session_id, safe="") + "/artifacts")
        if not isinstance(response.get("artifacts"), list):
            raise ValueError("session artifact list missing")
        if any(not isinstance(item, dict) or item.get("scope_id") != session_id
               for item in response["artifacts"]):
            raise ValueError("artifact belongs to another session")
        self._artifacts[session_id] = set()
        self._tokens = {token: owner for token, owner in self._tokens.items()
                        if owner[0] != session_id}
        for item in response["artifacts"]:
            identifier(item.get("id"), "artifact_id")
            self._artifacts[session_id].add(item["id"])
            token = item.get("file_token")
            if isinstance(token, str) and token:
                if token in self._tokens:
                    raise ValueError("duplicate artifact capability")
                filename = identifier(item.get("filename"), "artifact filename")
                self._tokens[token] = (session_id, item["id"], filename)
        return response

    def run_target(self, request: dict[str, Any]) -> dict[str, Any]:
        """Only an injected fixture target; formal/D shim binding is separate."""
        if self._fixture_target_runner is None:
            raise ValueError("fixture target runner is not bound")
        metadata = request.get("metadata", {})
        campaign = metadata.get("campaign", {}) if isinstance(metadata, dict) else {}
        if not isinstance(campaign, dict):
            campaign = {}
        sid = metadata.get("session_id") if isinstance(metadata, dict) else None
        skill_id = campaign.get("skill_id") if isinstance(campaign, dict) else None
        if (sid not in self._sessions or "project_id" in metadata
                or campaign.get("kind") != "skill-campaign"
                or campaign.get("target_context") != "global-general"
                or skill_id not in self._skills
                or campaign.get("skill_hash") != text_hash(self._skills[skill_id][1])
                or request.get("model_profile") not in {"default", "deepseek-v4.1-flash"}
                or request.get("reasoning_effort") != "high" or request.get("thinking") != "on"
                or not isinstance(request.get("messages"), list)
                or len(request["messages"]) != 1
                or request["messages"][0].get("role") != "user"):
            raise ValueError("fixture target request is not an owned general Skill case")
        return self._fixture_target_runner(request)

    def download(self, token: str) -> bytes:
        if token not in self._tokens:
            raise ValueError("file token is not from an owned listed artifact")
        if self._live_file_downloader is not None:
            session_id, artifact_id, filename = self._tokens[token]
            data, receipt = self._live_file_downloader(session_id, artifact_id, filename, token)
            if (not isinstance(data, bytes) or not isinstance(receipt, dict)
                    or receipt.get("kind") != "session-artifact-download"
                    or receipt.get("status") != "completed"
                    or receipt.get("session_id") != session_id
                    or receipt.get("artifact_id") != artifact_id
                    or receipt.get("filename") != filename
                    or receipt.get("file_token_sha256") != text_hash(token)
                    or receipt.get("content_sha256") != hashlib.sha256(data).hexdigest()):
                raise ValueError("live artifact receipt does not match the listed capability")
        elif self._fixture_file_downloader is not None:
            data = self._attempt("download-artifact", "management",
                                 lambda _operation: self._fixture_file_downloader(token))
        else:
            raise ValueError("artifact downloader is not bound")
        if not isinstance(data, bytes):
            raise ValueError("artifact downloader did not return bytes")
        return data

    def delete_artifact(self, session_id: str, artifact_id: str) -> dict[str, Any]:
        self._owned_session(session_id)
        identifier(artifact_id, "artifact_id")
        if artifact_id not in self._artifacts.get(session_id, set()):
            raise ValueError("artifact was not listed in the owned session")
        response = self._call("delete-artifact", "DELETE",
                              "/api/sessions/" + quote(session_id, safe="") + "/artifacts",
                              {"ids": [artifact_id]})
        if response.get("deleted") != 1:
            raise ValueError("artifact deletion not confirmed")
        self._artifacts[session_id].discard(artifact_id)
        self._tokens = {token: owner for token, owner in self._tokens.items()
                        if owner[:2] != (session_id, artifact_id)}
        return response

    def _owned_session(self, session_id: str) -> None:
        if session_id not in self._sessions:
            raise ValueError("session is not owned by this provisioner")
