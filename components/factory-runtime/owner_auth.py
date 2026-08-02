#!/usr/bin/env python3
"""Validate one-time activation authorization from an approved physical directory."""

import hashlib
import json
import os
from pathlib import Path

ACTION = "activate_file_native_workers_live"
BASE_SHA = "a961d8412d69f98e70b9522c406406d4ebc68e738f51360b5b53c66f3cf4c300"
REQUIRED = {
    "owner_scoped",
    "one_time",
    "atomic_live_switch",
    "rollback_point",
    "five_worker_health",
    "writer_ch482_preserved",
}
TEST_AUTH_ROOT = Path(__file__).resolve().parent / "fixtures"
LIVE_AUTH_ROOT = Path(
    "/home/storyclaw/.openclaw/shared/ai-drama-factory/factory/owner_authorizations"
)


def sha_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _approved_file(path, root):
    if root is None:
        raise ValueError("approved authorization root required")

    root = Path(root).expanduser().resolve(strict=True)
    if not root.is_dir():
        raise ValueError("approved authorization root missing")

    raw = Path(os.path.abspath(os.path.expanduser(str(path))))
    if ".." in Path(path).parts:
        raise ValueError("authorization path traversal rejected")

    try:
        relative = raw.relative_to(root)
    except ValueError as exc:
        raise ValueError("authorization outside approved shared root") from exc

    cursor = root
    for part in relative.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise ValueError("authorization symlink rejected")

    resolved = raw.resolve(strict=True)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError("authorization outside approved shared root") from exc
    if not resolved.is_file():
        raise ValueError("authorization file missing")
    return resolved


def validate(path, expected_package_sha=BASE_SHA, allow_test=False):
    if allow_test:
        approved_root = TEST_AUTH_ROOT
    else:
        approved_root = LIVE_AUTH_ROOT
    p = _approved_file(path, approved_root)

    o = json.loads(p.read_text())
    req = {
        "schema",
        "authorization_id",
        "owner",
        "approved",
        "action",
        "package_sha256",
        "target_version",
        "requirements",
        "test_only",
    }
    if not req <= set(o):
        raise ValueError("authorization missing required fields")
    if (
        o["schema"] != "qingshan.owner_live_activation_authorization.v1"
        or o["owner"] != "Roger"
        or o["approved"] is not True
    ):
        raise ValueError("owner authorization invalid")
    if o["action"] != ACTION or o["package_sha256"] != expected_package_sha:
        raise ValueError("authorization action/package mismatch")
    if not REQUIRED <= set(o["requirements"]):
        raise ValueError("authorization requirements incomplete")
    if Path(o["authorization_id"]).name != p.name:
        raise ValueError("authorization_id must equal filename")
    if o["test_only"] and not allow_test:
        raise ValueError("test_only authorization can never be consumed live")
    if not o["test_only"] and allow_test:
        raise ValueError("real authorization forbidden in dry-run tests")
    return {
        "authorization": o,
        "authorization_path": str(p),
        "authorization_root": str(Path(approved_root).resolve()),
        "authorization_sha256": sha_file(p),
    }
