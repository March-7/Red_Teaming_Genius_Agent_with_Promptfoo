"""Local fake management and target surface for orchestration contract tests."""
from __future__ import annotations


class OfflineAdapter:
    principal_id = "usr_fixture"

    def __init__(self, effect_filename: str, *, mutate: bool = False):
        self.effect_filename = effect_filename
        self.mutate = mutate
        self.skill = None
        self.session_id = None
        self.artifact = None
        self.events = []

    def create_skill(self, name: str, content: str):
        self.events.append("create_skill")
        self.skill = {"skill_id": "skill-fixture-a124", "name": name,
                      "instructions": content, "visibility": "private",
                      "owner_id": self.principal_id, "version": 1}
        return dict(self.skill)

    def read_skill(self, skill_id: str):
        self.events.append("read_skill")
        if self.skill is None or self.skill["skill_id"] != skill_id:
            raise ValueError("unknown fixture Skill")
        return dict(self.skill)

    def create_session(self):
        self.events.append("create_session")
        self.session_id = "chat:" + self.principal_id + ":a124b5c6"
        return {"session_id": self.session_id, "user_id": self.principal_id,
                "session_type": "general"}

    def list_artifacts(self, session_id: str):
        self.events.append("list_artifacts")
        if session_id != self.session_id:
            raise ValueError("wrong fixture session")
        return {"artifacts": [dict(self.artifact)] if self.artifact else []}

    def run_target(self, request: dict):
        self.events.append("run_target")
        if (request.get("metadata", {}).get("session_id") != self.session_id
                or "project_id" in request.get("metadata", {})
                or request.get("messages", [{}])[0].get("role") != "user"
                or self.effect_filename in request["messages"][0].get("content", "")):
            raise ValueError("fixture target request leaked or changed the frozen task")
        if self.mutate:
            self.artifact = {"id": "asset-fixture-a124", "filename": self.effect_filename,
                "scope_id": self.session_id, "file_token": "fixture-capability-a124"}
        return {"terminal_status": "completed", "session_id": self.session_id,
            "output": '{"total":3}', "tool_events": [
                {"event_type": "tool_call", "tool_name": "skill_read",
                 "tool_call_id": "call-fixture-a124",
                 "tool_input": {"skill_name": self.skill["name"]}},
                {"event_type": "tool_result", "tool_name": "skill_read",
                 "tool_call_id": "call-fixture-a124", "status": "success",
                 "instructions": self.skill["instructions"]}]}

    def download(self, token: str):
        self.events.append("download")
        if self.artifact is None or token != self.artifact["file_token"]:
            raise ValueError("unknown fixture file token")
        return "资料摘要归档".encode("utf-8")

    def delete_artifact(self, session_id: str, artifact_id: str):
        self.events.append("delete_artifact")
        if (session_id != self.session_id or self.artifact is None
                or artifact_id != self.artifact["id"]):
            raise ValueError("fixture artifact not owned by session")
        self.artifact = None
        return {"deleted": 1}
