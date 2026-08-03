import json
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


@pytest.fixture
def tmp_project(tmp_path: Path) -> Path:
    """A generic, fully-fictional standalone project directory (no source-drama-specific content)."""
    project = tmp_path / "GEN-PROJECT"
    (project / "episodes").mkdir(parents=True)
    for n in (1, 2):
        eid = f"E{n:03d}"
        (project / "episodes" / f"{eid}.json").write_text(json.dumps({
            "schema": "backlotos.episode-state/1.0",
            "episode_id": eid,
            "updated_at": "2026-01-01T00:00:00Z",
            "stages": [
                {"id": "source_plan", "status": "COMPLETE"},
                {"id": "story_generation", "status": "QUEUED"},
                {"id": "story_review", "status": "WAITING"},
            ],
        }), encoding="utf-8")
    return project


@pytest.fixture
def good_intake() -> dict:
    return {
        "source": {"url": "https://example.invalid/generic-novel.txt"},
        "production_type": "short_drama",
        "visual_format": "live_action",
        "episode_count": 4,
        "episode_duration_seconds": 120,
        "aspect_ratio": "9:16",
    }
