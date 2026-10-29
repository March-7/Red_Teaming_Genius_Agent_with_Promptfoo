"""Observed catalogue/runtime identity contract; all responses below are fixtures."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from skill_suite.general_a import reused_catalogue_identity, skill_result, verify_runtime_identity
from tests.test_skill_suite import case, proof, source_fixture, suite
from skill_suite.audit import source_audit
from skill_suite.idle_recovery import LIMITS, authorize as authorize_idle_recovery, execute as execute_idle_recovery
from sweep.runtime import sha256_file, write_json


class GeneralAIdentity(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.case = case(suite()); self.case["skill_version"] = "1"
        self.skill, _ = source_fixture(self.root, self.case)
        c = self.case
        body = {"status":"ok","name":c["resource_name"],"resource":"skill","resource_id":c["resource_name"],
            "version":234,"ref":"skill:"+c["resource_name"]+":v234","source":"user","mode":"text",
            "instructions":"normal instructions"}
        self.runtime = {"upstream_session_id":c["session_id"],"request_id":"request-1","tool_events":[
            {"event_type":"tool_call","tool_name":"skill_read","request_id":"request-1","tool_call_id":"tool-1",
             "tool_input":{"skill_name":c["resource_name"]}},
            {"event_type":"tool_result","tool_name":"skill_read","request_id":"request-1","tool_call_id":"tool-1",
             "status":"success","tool_result":"[1] source\n\n"+json.dumps(body)}]}
        receipt=json.loads((self.root/"catalogue-raw.json").read_text())
        receipt["observed_at"]="2026-10-02T10:00:00+00:00"
        before=proof(self.root,"before.json",receipt)
        receipt["observed_at"]="2026-10-02T10:00:03+00:00"
        after=proof(self.root,"after.json",receipt)
        self.event={"kind":"skill-content-read","request_id":"request-1","tool_call_id":"tool-1",
            "runtime_version":234,"content":"normal instructions","identity_resolution":{
                "method":"catalogue-name-content-join","runtime_result_ref":proof(self.root,"result.json",self.runtime),
                "before_catalogue_ref":before,"after_catalogue_ref":after,
                "target_attempt_ref":proof(self.root,"attempt.json",{"operation_id":"target:"+":".join(c[k] for k in ("case_id","model_profile","variant")),
                    "outcome":"completed","submitted_at":"2026-10-02T10:00:01+00:00","elapsed_s":1})}}

    def test_separate_versions_preserve_actual_runtime_value_and_catalogue_join(self):
        resolved=verify_runtime_identity(self.event,self.root,self.case)
        self.assertEqual(resolved["catalogue_version"],"1"); self.assertEqual(resolved["runtime_version"],234)
        self.assertFalse(resolved["catalogue_id_returned_by_runtime"])

    def test_actual_body_turn_and_version_drift_reject_identity_join(self):
        for mutate in (lambda v:v.update(request_id="other-turn"),
                       lambda v:v["tool_events"][1].update(tool_result=json.dumps({"status":"ok","instructions":"wrong"}))):
            changed=copy.deepcopy(self.runtime);mutate(changed)
            event=copy.deepcopy(self.event);event["identity_resolution"]["runtime_result_ref"]=proof(self.root,"changed.json",changed)
            with self.assertRaises(ValueError):verify_runtime_identity(event,self.root,self.case)
        after=json.loads((self.root/"after.json").read_text());after["response"]["body"]["skill"]["version"]=2
        event=copy.deepcopy(self.event);event["identity_resolution"]["after_catalogue_ref"]=proof(self.root,"changed-after.json",after)
        with self.assertRaises(ValueError):verify_runtime_identity(event,self.root,self.case)

    def test_readbacks_must_surround_actual_target_window(self):
        before=json.loads((self.root/"before.json").read_text());before["observed_at"]="2026-10-02T10:00:04+00:00"
        event=copy.deepcopy(self.event);event["identity_resolution"]["before_catalogue_ref"]=proof(self.root,"late-before.json",before)
        with self.assertRaises(ValueError):verify_runtime_identity(event,self.root,self.case)

    def test_normalized_private_claim_cannot_override_actual_catalogue_response(self):
        value=json.loads((self.root/"catalogue.json").read_text())
        raw=json.loads((self.root/"catalogue-raw.json").read_text());raw["response"]["body"]["skill"]["visibility"]="org"
        value["raw_refs"][0]=proof(self.root,"public-raw.json",raw)
        self.skill["catalogue_evidence"]=proof(self.root,"private-claim.json",value)
        self.assertFalse(source_audit(self.case,self.skill,[],self.root)["imported"])

    def test_prefixed_json_parser_rejects_extra_prose_and_invalid_text(self):
        self.assertEqual(skill_result('Citation\n{"status":"ok"}'),{"status":"ok"})
        self.assertIsNone(skill_result('{"status":"ok"}extra'))
        self.assertIsNone(skill_result('not found'))

    def test_reused_private_skill_requires_current_and_prior_byte_identity(self):
        from skill_suite.schema import text_hash
        name = self.case["resource_name"]
        asset_root = self.root / "assets-default"; asset_root.mkdir()
        (asset_root / "instructions.md").write_text("normal instructions")
        asset = {"name": name, "instructions_file": "instructions.md",
                 "instructions_sha256": text_hash("normal instructions")}
        skill = {"skill_id": self.case["skill_id"], "name": name,
                 "owner_id": "usr_notes", "source": "user", "visibility": "private", "mode": "text",
                 "scripts": [], "needs_credentials": [], "shared_with_count": 0, "version": 1,
                 "instructions": "normal instructions"}
        for kind in ("A-read", "prior-create", "prior-retain"):
            proof(self.root, kind + "-default.json", {"response": {"status": 200, "body": {"skill": skill}}})
        proof(self.root, "A-sharing-default.json", {"response": {"status": 200,
              "body": {"skill_id": skill["skill_id"], "scope": "private", "members": []}}})
        self.assertTrue(reused_catalogue_identity(self.root, "default", asset, "usr_notes")["reuse_origin_verified"])
        changed = copy.deepcopy(skill); changed["version"] = 2
        proof(self.root, "prior-retain-default.json", {"response": {"status": 200, "body": {"skill": changed}}})
        with self.assertRaisesRegex(ValueError, "reused Skill changed"):
            reused_catalogue_identity(self.root, "default", asset, "usr_notes")


class IdleRecoveryAuthorization(unittest.TestCase):
    def test_one_read_scope_is_bound_before_any_online_work(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory) / "reading-note-b2-a1"; run.mkdir()
            packet_path = run / "idle-recovery-addendum.json"
            sid = "chat:usr_notes:session1"
            message_path = run / "messages.json"
            write_json(message_path, {"messages": []})
            from skill_suite import idle_recovery
            packet = {"run_id": run.name, "session_id": sid, "request_id": "request-1",
                "method": "GET", "path": "/api/sessions/chat%3Ausr_notes%3Asession1/live",
                "limits": LIMITS, "messages_ref": {"file": message_path.name,
                    "sha256": sha256_file(message_path)},
                "execution_code_sha256": sha256_file(Path(idle_recovery.__file__)),
                "status": "prepared-offline", "authorization": None}
            write_json(packet_path, packet)
            with self.assertRaisesRegex(ValueError, "authorization required"):
                execute_idle_recovery(run.parent, run, packet_path)
            authorize_idle_recovery(packet_path, "actual human reply reference")
            changed = json.loads(packet_path.read_text())
            changed["path"] = "/api/sessions/other/live"
            write_json(packet_path, changed)
            with self.assertRaisesRegex(ValueError, "authorization required"):
                execute_idle_recovery(run.parent, run, packet_path)


if __name__ == "__main__": unittest.main()
