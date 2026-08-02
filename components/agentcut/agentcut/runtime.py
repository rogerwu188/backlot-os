from __future__ import annotations

import os
import platform
import shutil
import hashlib
import sys
from pathlib import Path
from typing import Any


def bundled_binary(name: str = "ffmpeg") -> Path | None:
    system = {"Darwin": "darwin", "Linux": "linux", "Windows": "windows"}.get(platform.system())
    machine = {"arm64": "arm64", "aarch64": "arm64", "x86_64": "amd64", "AMD64": "amd64"}.get(platform.machine())
    if not system or not machine:
        return None
    executable = name + (".exe" if system == "windows" else "")
    candidate = Path(__file__).resolve().parent / "vendor" / f"{system}-{machine}" / executable
    return candidate if candidate.is_file() and os.access(candidate, os.X_OK) else None


def resolve_binary(configured: str | None, name: str = "ffmpeg") -> str:
    """Explicit path, environment, bundled binary, then PATH—in that order."""
    if configured and configured != "auto":
        return configured
    env_name = f"AGENTCUT_{name.upper()}"
    if os.environ.get(env_name):
        return os.environ[env_name]
    bundled = bundled_binary(name)
    if bundled:
        return str(bundled)
    return shutil.which(name) or name


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def runtime_fingerprint() -> str:
    package = Path(__file__).resolve().parent
    digest = hashlib.sha256()
    for source in sorted(package.glob("*.py")):
        digest.update(source.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(source.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def binary_info(path: str) -> dict[str, Any]:
    resolved = shutil.which(path)
    if resolved is None and Path(path).is_file():
        resolved = str(Path(path).resolve())
    return {"path": resolved or path, "available": resolved is not None,
            "sha256": sha256_file(resolved) if resolved else None}


def runtime_identity(version: str, ffmpeg: str, ffprobe: str) -> dict[str, Any]:
    ffmpeg_info = binary_info(ffmpeg)
    ffprobe_info = binary_info(ffprobe)
    ready = bool(ffmpeg_info["available"] and ffprobe_info["available"])
    return {
        "status": "ready" if ready else "unavailable", "ready": ready,
        "version": version, "runtimeHash": runtime_fingerprint(),
        "python": {"executable": sys.executable, "version": platform.python_version()},
        "ffmpegInfo": ffmpeg_info, "ffprobeInfo": ffprobe_info,
    }
