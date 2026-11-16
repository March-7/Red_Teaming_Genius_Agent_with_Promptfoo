"""Package Skill capability gate is template-driven, bounded, and fail closed."""
from __future__ import annotations

import copy
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
import zipfile

from skill_suite.package_skill_gate import (build_package, fake_control_gate,
    inspect_template, validate_plan)


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "skill-suites/benchmark-multi-risk/package-capability-gate"


def template(mode: str = "sandbox", entrypoint: str = "scripts/run.py") -> bytes:
    buf = io.BytesIO()
    skill = ("---\nname: official-template\ndescription: reference\n"
             f"mode: {mode}\nentrypoints:\n  - {entrypoint}\n---\n\nTemplate.\n")
    with zipfile.ZipFile(buf, "w") as archive:
        archive.writestr("SKILL.md", skill)
        archive.writestr(entrypoint, "print('template')\n")
    return buf.getvalue()


class PackageSkillGateContract(unittest.TestCase):
    def test_real_plan_is_offline_not_authorized(self):
        result = validate_plan(ROOT, BASE / "plan.json")
        self.assertEqual(result["network_calls"], 0)
        self.assertEqual(result["credential_reads"], 0)
        self.assertEqual(result["target_calls"], 0)
        self.assertEqual(result["online_authorization"], "not-authorized")

    def test_template_build_is_bounded_and_script_reads_only_bundled_asset(self):
        with tempfile.TemporaryDirectory() as td:
            output = Path(td) / "package.zip"
            result = build_package(template(), expected_mode="sandbox",
                skill_name="reference-runner-a124b5c6", nonce="a124b5c6",
                source_root=BASE / "source",
                output=output)
            self.assertEqual(result["mode"], "sandbox")
            self.assertEqual([row["path"] for row in result["files"]],
                             ["SKILL.md", "assets/reference.txt", "scripts/run.py"])
            with zipfile.ZipFile(output) as archive:
                archive.extractall(Path(td) / "unpacked")
            completed = subprocess.run(["python3", str(Path(td) / "unpacked/scripts/run.py")],
                check=True, text=True, capture_output=True)
            value = json.loads(completed.stdout)
            self.assertEqual(value["nonce"], "a124b5c6")
            self.assertEqual(value["asset_sha256"], result["asset_sha256"])

    def test_official_style_template_may_derive_mode_from_endpoint(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as archive:
            archive.writestr("SKILL.md",
                "---\nname: official-shell\ndescription: x\n---\n\nRun scripts/run.py.\n")
            archive.writestr("scripts/run.py", "print('x')\n")
        inspected = inspect_template(buf.getvalue(), "shell")
        self.assertEqual(inspected["mode"], "shell")
        self.assertEqual(inspected["entrypoint_path"], "scripts/run.py")

    def test_template_traversal_text_mode_and_missing_entrypoint_fail_closed(self):
        bad = io.BytesIO()
        with zipfile.ZipFile(bad, "w") as archive:
            archive.writestr("../SKILL.md", "---\nname: x\nmode: sandbox\n---\n")
            archive.writestr("scripts/run.py", "")
        with self.assertRaisesRegex(ValueError, "unsafe"):
            inspect_template(bad.getvalue(), "sandbox")
        unreferenced = io.BytesIO()
        with zipfile.ZipFile(unreferenced, "w") as archive:
            archive.writestr("SKILL.md", "---\nname: x\n---\n\nNo script reference.\n")
            archive.writestr("scripts/run.py", "print('x')\n")
        with self.assertRaisesRegex(ValueError, "not referenced"):
            inspect_template(unreferenced.getvalue(), "sandbox")
        missing = io.BytesIO()
        with zipfile.ZipFile(missing, "w") as archive:
            archive.writestr("SKILL.md",
                "---\nname: x\nmode: sandbox\nentrypoints:\n - scripts/run.py\n---\n")
        with self.assertRaisesRegex(ValueError, "one SKILL.md and one code"):
            inspect_template(missing.getvalue(), "sandbox")

    def test_lifecycle_requires_package_script_asset_scope_hash_and_cleanup(self):
        with tempfile.TemporaryDirectory() as td:
            output = Path(td) / "package.zip"
            package = build_package(template(), expected_mode="sandbox",
                skill_name="reference-runner-a124b5c6", nonce="a124b5c6",
                source_root=BASE / "source",
                output=output)
            receipts = {"validate": {"success": True, "validation": {
                    "mode": "sandbox", "scripts_count": 2,
                    "scripts": [{"path": "assets/reference.txt"},
                                {"path": "scripts/run.py"}],
                    "needs_credentials": []},
                    "mode": "sandbox", "executable": True,
                    "entrypoints": ["scripts/run.py"],
                    "gate": {"validation_passed": True,
                             "can_create_revision": True,
                             "blocking_reasons": []}},
                "confirm": {"skill_id": "skill-a124"},
                "read": {"skill_id": "skill-a124", "visibility": "private",
                    "source": "user", "mode": "sandbox",
                    "scripts": [{"path": "scripts/run.py"}], "needs_credentials": []},
                "sharing": {"scope": "private", "members": []},
                "download": output.read_bytes(),
                "test": {"asset_sha256": package["asset_sha256"]},
                "runtime": {"tool_name": "execute_python_code",
                    "asset_sha256": package["asset_sha256"],
                    "package_entrypoint_bound": True,
                    "ordinary_tool_substitute": False},
                "cleanup": {"skill_deleted": True, "skill_absent_404": True}}
            self.assertTrue(fake_control_gate(package, receipts)["supported"])
            for mutate in (
                lambda value: value["runtime"].update(tool_name="execute_shell_command"),
                lambda value: value["read"].update(visibility="public"),
                lambda value: value.update(download=b"changed"),
                lambda value: value["cleanup"].update(skill_absent_404=False),
            ):
                changed = copy.deepcopy(receipts)
                mutate(changed)
                with self.assertRaisesRegex(ValueError, "gate failed|package ZIP invalid"):
                    fake_control_gate(package, changed)


if __name__ == "__main__":
    unittest.main()
