from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable

from .errors import AgentCutError


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _check_soundfile() -> tuple[bool, str | None]:
    try:
        import numpy as np
        import soundfile as sf
        with tempfile.TemporaryDirectory(prefix="agentcut-save-") as tmp:
            target = Path(tmp) / "probe.wav"
            sf.write(target, np.zeros((48, 1), dtype="float32"), 48000, subtype="PCM_16")
            if not target.is_file() or target.stat().st_size < 44:
                raise RuntimeError("probe WAV was not written")
        return True, None
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


def _check_ffmpeg(ffmpeg: str) -> tuple[bool, str | None]:
    try:
        with tempfile.TemporaryDirectory(prefix="agentcut-save-") as tmp:
            target = Path(tmp) / "probe.wav"
            process = subprocess.run([ffmpeg, "-v", "error", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono", "-t", "0.001", "-y", str(target)], capture_output=True, text=True)
            if process.returncode or not target.is_file() or target.stat().st_size < 44:
                raise RuntimeError(process.stderr.strip() or "probe WAV was not written")
        return True, None
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


def _check_torchaudio() -> tuple[bool, str | None]:
    try:
        import torch
        import torchaudio
        with tempfile.TemporaryDirectory(prefix="agentcut-save-") as tmp:
            target = Path(tmp) / "probe.wav"
            torchaudio.save(str(target), torch.zeros(1, 48), 48000)
            if not target.is_file() or target.stat().st_size < 44:
                raise RuntimeError("probe WAV was not written")
        return True, None
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


def audio_save_health(ffmpeg: str) -> dict[str, Any]:
    checks = {}
    for name, checker in (("soundfile", _check_soundfile), ("ffmpeg", lambda: _check_ffmpeg(ffmpeg)), ("torchaudio", _check_torchaudio)):
        ok, error = checker()
        checks[name] = {"available": ok, **({"error": error} if error else {})}
    selected = next((name for name in ("soundfile", "ffmpeg", "torchaudio") if checks[name]["available"]), None)
    return {"ready": selected is not None, "selectedBackend": selected, "backends": checks,
            "probe": "actual WAV write", "failFastBeforeModelLoad": True}


def require_audio_save_backend(ffmpeg: str) -> dict[str, Any]:
    health = audio_save_health(ffmpeg)
    if not health["ready"]:
        detail = "; ".join(f"{name}: {value.get('error', 'unavailable')}" for name, value in health["backends"].items())
        raise AgentCutError(f"no usable audio-save backend; refusing model download/inference: {detail}")
    return health


def _install_torchaudio_fallback(backend: str, ffmpeg: str) -> None:
    if backend == "torchaudio":
        return
    try:
        import torchaudio
    except Exception as exc:
        raise AgentCutError(f"Demucs requires torchaudio import even when save uses fallback: {exc}")

    def save(uri: Any, src: Any, sample_rate: int, **kwargs: Any) -> None:
        target = str(uri)
        tensor = src.detach().cpu().float()
        if backend == "soundfile":
            import soundfile as sf
            subtype = {16: "PCM_16", 24: "PCM_24", 32: "PCM_32"}.get(kwargs.get("bits_per_sample"), "PCM_24")
            sf.write(target, tensor.transpose(0, 1).numpy(), sample_rate, subtype=subtype)
            return
        channels = int(tensor.shape[0])
        process = subprocess.run([ffmpeg, "-v", "error", "-f", "f32le", "-ar", str(sample_rate), "-ac", str(channels),
                                  "-i", "pipe:0", "-y", "-c:a", "pcm_s24le", target],
                                 input=tensor.transpose(0, 1).contiguous().numpy().tobytes(), capture_output=True)
        if process.returncode:
            raise RuntimeError(process.stderr.decode(errors="replace"))
    torchaudio.save = save


def run_demucs_with_safe_save(ffmpeg: str, source: str, output_dir: str, report_path: str, *,
                              model: str = "htdemucs", expected_model_sha256: str | None = None,
                              overwrite: bool = False) -> dict[str, Any]:
    # This must remain the first expensive-operation boundary: the actual-write
    # probe completes before Demucs import, model resolution/download or inference.
    health = require_audio_save_backend(ffmpeg)
    src, root, report = Path(source).resolve(), Path(output_dir).resolve(), Path(report_path).resolve()
    if not src.is_file():
        raise AgentCutError(f"input audio not found: {src}")
    existing = {str(path): sha256_file(path) for path in root.rglob("*") if path.is_file()} if root.exists() else {}
    if existing and not overwrite:
        raise AgentCutError("Demucs output directory is not empty; pass --overwrite to create rollback backups")
    backup_root = report.with_suffix(report.suffix + ".rollback")
    backups: list[dict[str, str]] = []
    if existing:
        backup_root.mkdir(parents=True, exist_ok=True)
        for name, digest in existing.items():
            source_path = Path(name)
            backup = backup_root / source_path.relative_to(root)
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, backup)
            backups.append({"original": name, "backup": str(backup), "sha256": digest})
    report.parent.mkdir(parents=True, exist_ok=True)
    prepared = {"version": "agentcut.demucs-safe-save.v1", "status": "PREPARED_BEFORE_MODEL_LOAD",
                "input": {"path": str(src), "sha256": sha256_file(src)}, "model": {"name": model},
                "audioSave": health, "rollback": {"createdFiles": [], "backups": backups,
                                                    "restoreBackupsThenDeleteCreated": True}}
    report.write_text(json.dumps(prepared, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _install_torchaudio_fallback(str(health["selectedBackend"]), ffmpeg)
    try:
        from demucs.separate import main as demucs_main
    except Exception as exc:
        raise AgentCutError(f"Demucs is not installed in this Python environment: {exc}")
    demucs_main(["-n", model, "--two-stems", "vocals", "-o", str(root), str(src)])
    candidates = sorted(root.rglob("vocals.wav"), key=lambda path: path.stat().st_mtime, reverse=True)
    if not candidates:
        raise AgentCutError("Demucs completed without producing vocals.wav")
    vocal = candidates[0]
    try:
        import torch
        checkpoint_roots = [Path(torch.hub.get_dir()) / "checkpoints"]
    except Exception:
        checkpoint_roots = [Path(os.environ.get("TORCH_HOME", Path.home() / ".cache" / "torch")) / "hub" / "checkpoints"]
    checkpoints = sorted((p for base in checkpoint_roots if base.exists() for p in base.glob("*") if p.is_file()), key=lambda p: p.stat().st_mtime, reverse=True)
    model_file = checkpoints[0] if checkpoints else None
    model_sha = sha256_file(model_file) if model_file else None
    created = [{"path": str(path), "sha256": sha256_file(path)} for path in root.rglob("*") if path.is_file() and str(path) not in existing]
    result = {"version": "agentcut.demucs-safe-save.v1", "status": "OUTPUT_CREATED", "input": {"path": str(src), "sha256": sha256_file(src)},
              "model": {"name": model, "path": str(model_file) if model_file else None, "sha256": model_sha},
              "output": {"path": str(vocal), "sha256": sha256_file(vocal)}, "audioSave": health,
              "rollback": {"createdFiles": created, "backups": backups, "restoreBackupsThenDeleteCreated": True}}
    report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if expected_model_sha256 and model_sha != expected_model_sha256:
        raise AgentCutError(f"model SHA mismatch: expected {expected_model_sha256}, got {model_sha}; provenance/rollback report preserved at {report}")
    result["status"] = "COMPLETE"
    report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result
