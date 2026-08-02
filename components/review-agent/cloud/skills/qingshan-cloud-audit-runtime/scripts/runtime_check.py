#!/usr/bin/env python3
import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys


def version(command):
    path = shutil.which(command)
    if not path:
        return {"status": "MISSING", "path": None, "version": None}
    proc = subprocess.run([path, "-version"], capture_output=True, text=True, timeout=10)
    line = (proc.stdout or proc.stderr).splitlines()
    return {"status": "PASS" if proc.returncode == 0 else "ERROR", "path": path, "version": line[0] if line else None}


def module(name):
    return {"status": "PASS" if importlib.util.find_spec(name) else "MISSING"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--require-all", action="store_true")
    args = parser.parse_args()
    checks = {
        "python": {"status": "PASS", "version": sys.version.split()[0]},
        "ffmpeg": version("ffmpeg"),
        "ffprobe": version("ffprobe"),
        "rapidocr": module("rapidocr"),
        "onnxruntime": module("onnxruntime"),
        "opencv": module("cv2"),
        "faster_whisper": module("faster_whisper"),
        "openai_sdk": module("openai"),
        "mediapipe": module("mediapipe"),
        "vlm_command": {"status": "PASS" if os.environ.get("QINGSHAN_IMAGE_ANALYSIS_COMMAND") else "MISSING"},
        "asr_command": {"status": "PASS" if os.environ.get("QINGSHAN_ASR_COMMAND") else "MISSING"},
        "lipsync_command": {"status": "PASS" if os.environ.get("QINGSHAN_LIPSYNC_COMMAND") else "MISSING"},
    }
    missing = sorted(key for key, value in checks.items() if value["status"] != "PASS")
    report = {"schema": "qingshan.cloud_audit_runtime_check.v1", "status": "PASS" if not missing else "CAPABILITY_FAIL", "checks": checks, "missing": missing}
    print(json.dumps(report, ensure_ascii=False, indent=2 if args.json else None, sort_keys=True))
    return 1 if args.require_all and missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
