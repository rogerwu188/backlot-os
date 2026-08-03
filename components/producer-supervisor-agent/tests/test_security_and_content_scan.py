import re
from pathlib import Path

PKG_ROOT = Path(__file__).resolve().parents[1]
SCAN_DIRS = [PKG_ROOT / "src", PKG_ROOT / "schemas", PKG_ROOT / "tests"]

SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9]{16,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"-----BEGIN(?: [A-Z]+)? PRIVATE KEY-----"),
    re.compile(r"ANTHROPIC_API_KEY\s*=\s*['\"]?sk-"),
]

QINGSHAN_TOKENS = ["陈迹", "皎兔", "云羊", "青山", "沈砚", "密谍司", "太平医馆"]


def _all_text_files():
    self_path = Path(__file__).resolve()
    for d in SCAN_DIRS:
        if not d.is_dir():
            continue
        for path in d.rglob("*"):
            if path.resolve() == self_path:
                continue  # this file legitimately lists the tokens it scans for
            if path.is_file() and path.suffix in {".py", ".json", ".md", ".txt", ""}:
                yield path


def test_no_secrets_in_package():
    hits = []
    for path in _all_text_files():
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for pattern in SECRET_PATTERNS:
            if pattern.search(text):
                hits.append((str(path), pattern.pattern))
    assert not hits, f"potential secret material found: {hits}"


def test_no_qingshan_specific_content():
    hits = []
    for path in _all_text_files():
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for token in QINGSHAN_TOKENS:
            if token in text:
                hits.append((str(path), token))
    assert not hits, f"project-specific content leaked into generic package: {hits}"
