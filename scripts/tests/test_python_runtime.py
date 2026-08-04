from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "scripts" / "lib" / "python-runtime.sh"


def fake_python(path: Path, version: str) -> None:
    path.write_text(
        "#!/usr/bin/env bash\n"
        f"printf '%s\\n' '{version}'\n",
        encoding="utf-8",
    )
    path.chmod(0o755)


def select_python(candidate: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["BACKLOT_PYTHON"] = str(candidate)
    command = f'source "{HELPER}"; backlot_select_python'
    return subprocess.run(
        ["bash", "-c", command],
        text=True,
        capture_output=True,
        env=env,
    )


class PythonRuntimeTests(unittest.TestCase):
    def test_accepts_supported_python_312(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            candidate = Path(tmp) / "python3.12"
            fake_python(candidate, "3.12")
            result = select_python(candidate)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), str(candidate))

    def test_rejects_python_314_before_dependency_install(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            candidate = Path(tmp) / "python3.14"
            fake_python(candidate, "3.14")
            result = select_python(candidate)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")

    def test_rejects_python_39(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            candidate = Path(tmp) / "python3.9"
            fake_python(candidate, "3.9")
            result = select_python(candidate)
        self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
