from pathlib import Path
import re

import claude_story_agent


def test_runtime_version_matches_package_metadata():
    pyproject = Path(__file__).parents[1] / "pyproject.toml"
    match = re.search(r'^version = "([^"]+)"$', pyproject.read_text(encoding="utf-8"), re.MULTILINE)
    assert match is not None
    metadata_version = match.group(1)
    assert claude_story_agent.__version__ == metadata_version
