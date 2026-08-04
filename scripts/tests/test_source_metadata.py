from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "scripts" / "lib" / "source-metadata.sh"


def write_metadata(source: Path, install: Path, env: dict[str, str] | None = None) -> None:
    command = (
        f'source "{HELPER}"; '
        f'backlot_write_source_metadata "{source}" "{install}"'
    )
    subprocess.run(["bash", "-c", command], check=True, env=env)


class SourceMetadataTests(unittest.TestCase):
    def test_source_archive_without_git_metadata_is_installable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "backlotos-v0.2.13"
            install = root / "install"
            source.mkdir()
            (source / "VERSION").write_text("0.2.13\n", encoding="utf-8")

            write_metadata(source, install)

            metadata = install / "source"
            self.assertEqual((metadata / "version").read_text().strip(), "0.2.13")
            self.assertEqual(
                (metadata / "git-commit").read_text().strip(),
                "source-archive:v0.2.13",
            )
            self.assertEqual(
                (metadata / "git-origin").read_text().strip(),
                "https://github.com/rogerwu188/backlot-os.git",
            )

    def test_source_archive_origin_can_be_overridden(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            install = root / "install"
            source.mkdir()
            (source / "VERSION").write_text("9.9.9\n", encoding="utf-8")
            env = os.environ.copy()
            env["BACKLOT_SOURCE_ORIGIN"] = "https://example.test/fork.git"

            write_metadata(source, install, env)

            self.assertEqual(
                (install / "source" / "git-origin").read_text().strip(),
                "https://example.test/fork.git",
            )

    def test_git_checkout_preserves_exact_commit_and_origin(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            install = root / "install"
            source.mkdir()
            (source / "VERSION").write_text("0.2.13\n", encoding="utf-8")
            subprocess.run(["git", "init", "-q", str(source)], check=True)
            subprocess.run(["git", "-C", str(source), "config", "user.name", "Test"], check=True)
            subprocess.run(["git", "-C", str(source), "config", "user.email", "test@example.com"], check=True)
            subprocess.run(["git", "-C", str(source), "add", "VERSION"], check=True)
            subprocess.run(["git", "-C", str(source), "commit", "-qm", "test"], check=True)
            subprocess.run(
                ["git", "-C", str(source), "remote", "add", "origin", "https://example.test/repo.git"],
                check=True,
            )
            expected_commit = subprocess.check_output(
                ["git", "-C", str(source), "rev-parse", "HEAD"], text=True
            ).strip()

            write_metadata(source, install)

            metadata = install / "source"
            self.assertEqual((metadata / "git-commit").read_text().strip(), expected_commit)
            self.assertEqual(
                (metadata / "git-origin").read_text().strip(),
                "https://example.test/repo.git",
            )


if __name__ == "__main__":
    unittest.main()
