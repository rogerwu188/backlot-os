from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PROFILE = ROOT / "scripts" / "lib" / "runtime-profile.sh"
DOCTOR = ROOT / "scripts" / "doctor.sh"


def run_profile(env: dict[str, str]) -> str:
    command = (
        f'source "{PROFILE}"; '
        'profile="$(backlot_detect_runtime_profile)"; '
        'echo "PROFILE=$profile"; '
        'backlot_report_model_configuration "$profile"'
    )
    completed = subprocess.run(
        ["bash", "-c", command],
        check=True,
        text=True,
        capture_output=True,
        env=env,
    )
    return completed.stdout


class RuntimeProfileTests(unittest.TestCase):
    def base_env(self, home: Path) -> dict[str, str]:
        env = os.environ.copy()
        for name in (
            "BACKLOT_RUNTIME_PROFILE",
            "STORYCLAW_DEVICE_ID",
            "STORYCLAW_RUNTIME",
            "OPENCLAW_HOME",
            "OPENAI_API_KEY",
            "QINGSHAN_IMAGE_ANALYSIS_COMMAND",
            "QINGSHAN_OCR_PYTHON",
        ):
            env.pop(name, None)
        env["HOME"] = str(home)
        return env

    def test_explicit_storyclaw_makes_openai_key_not_applicable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env = self.base_env(Path(tmp))
            env["BACKLOT_RUNTIME_PROFILE"] = "storyclaw"
            output = run_profile(env)
        self.assertIn("PROFILE=storyclaw", output)
        self.assertIn("PASS host-model-runtime:storyclaw-managed", output)
        self.assertIn("NOT_APPLICABLE OPENAI_API_KEY", output)
        self.assertNotIn("OPTIONAL_NOT_CONFIGURED OPENAI_API_KEY", output)

    def test_openclaw_home_is_auto_detected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            (home / ".openclaw").mkdir()
            output = run_profile(self.base_env(home))
        self.assertIn("PROFILE=storyclaw", output)

    def test_standalone_keeps_direct_api_key_optional(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env = self.base_env(Path(tmp))
            env["BACKLOT_RUNTIME_PROFILE"] = "standalone"
            output = run_profile(env)
        self.assertIn("PROFILE=standalone", output)
        self.assertIn("OPTIONAL_NOT_CONFIGURED OPENAI_API_KEY", output)
        self.assertNotIn("NOT_APPLICABLE OPENAI_API_KEY", output)

    def test_storyclaw_command_bridge_is_reported_separately(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env = self.base_env(Path(tmp))
            env["BACKLOT_RUNTIME_PROFILE"] = "storyclaw"
            env["QINGSHAN_IMAGE_ANALYSIS_COMMAND"] = "/opt/backlotos/bin/vision-bridge"
            output = run_profile(env)
        self.assertIn("CONFIGURED QINGSHAN_IMAGE_ANALYSIS_COMMAND", output)
        self.assertNotIn("cli_bridge_not_configured", output)

    def test_bundled_storyclaw_adapter_replaces_command_variable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            adapter = home / ".local" / "share" / "backlotos" / "venv" / "bin" / "backlotos-storyclaw-image-analysis"
            adapter.parent.mkdir(parents=True)
            adapter.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
            adapter.chmod(0o755)
            env = self.base_env(home)
            env["BACKLOT_RUNTIME_PROFILE"] = "storyclaw"
            env["BACKLOT_STORYCLAW_API_KEY"] = "secret"
            output = run_profile(env)
        self.assertIn("PASS image-analysis-runtime:storyclaw-chat-completions", output)
        self.assertIn("NOT_APPLICABLE QINGSHAN_IMAGE_ANALYSIS_COMMAND", output)

    def test_missing_bundled_ocr_is_capability_not_configured(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env = self.base_env(Path(tmp))
            env["BACKLOT_RUNTIME_PROFILE"] = "storyclaw"
            output = run_profile(env)
        self.assertIn("CAPABILITY_NOT_CONFIGURED ocr-runtime", output)
        self.assertNotIn("OPTIONAL_NOT_CONFIGURED QINGSHAN_OCR_PYTHON", output)

    def test_doctor_uses_storyclaw_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            install_dir = root / "install"
            bin_dir = install_dir / "venv" / "bin"
            command_dir = root / "commands"
            bin_dir.mkdir(parents=True)
            command_dir.mkdir()
            installed_version = install_dir / "source" / "version"
            installed_version.parent.mkdir(parents=True)
            shutil.copyfile(ROOT / "VERSION", installed_version)
            installed_pipeline_tools = install_dir / "share" / "pipeline-tools"
            installed_pipeline_tools.mkdir(parents=True)
            for artifact in (
                "submit_giggle_image_manifest.py",
                "giggle_api_client.py",
                "seedance2_prompt_compiler.py",
                "shot_package_completion_gate.py",
                "submit_giggle_video_manifest_v2.py",
                "exact_first_frame_transport.py",
                "exact_first_frame_post_harvest_gate.py",
                "production_video_submission_gate.py",
                "provider_video_capability_gate.py",
                "provider_video_capabilities.json",
            ):
                shutil.copyfile(
                    ROOT / "components" / "pipeline-tools" / artifact,
                    installed_pipeline_tools / artifact,
                )
            for name in ("git", "ffmpeg", "ffprobe", "node"):
                target = command_dir / name
                target.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
                target.chmod(0o755)
            for name in (
                "qingshan-review",
                "agentcut",
                "claude-story-agent",
                "backlotos",
                "backlotos-producer-command",
                "backlotos-pipeline-command",
            ):
                target = bin_dir / name
                if name == "backlotos-pipeline-command":
                    target.write_text(
                        "#!/usr/bin/env bash\n"
                        "printf '%s\\n' '{\"media_provider\":{\"defaults\":{\"video_model\":\"seedance-2.0-fast\"}}}'\n",
                        encoding="utf-8",
                    )
                else:
                    target.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
                target.chmod(0o755)
            python_target = bin_dir / "python"
            python_target.write_text(
                "#!/usr/bin/env bash\n"
                "if [[ ${1:-} == -c ]]; then exit 0; fi\n"
                "exec python3 \"$@\"\n",
                encoding="utf-8",
            )
            python_target.chmod(0o755)
            env = self.base_env(root)
            env["BACKLOT_RUNTIME_PROFILE"] = "storyclaw"
            env["BACKLOT_INSTALL_DIR"] = str(install_dir)
            env["PATH"] = f"{command_dir}:{os.environ.get('PATH', '')}"
            completed = subprocess.run(
                ["bash", str(DOCTOR)],
                check=True,
                text=True,
                capture_output=True,
                env=env,
            )
        self.assertIn("PASS runtime-profile:storyclaw", completed.stdout)
        self.assertIn("NOT_APPLICABLE OPENAI_API_KEY", completed.stdout)
        self.assertIn("PASS ocr-runtime:rapidocr-onn", completed.stdout)
        self.assertIn("NOT_APPLICABLE QINGSHAN_OCR_PYTHON", completed.stdout)


if __name__ == "__main__":
    unittest.main()
