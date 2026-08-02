import json, os, copy, sys
import pytest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
FIX = os.path.join(os.path.dirname(__file__), "fixtures")

@pytest.fixture
def good():
    return copy.deepcopy(json.load(open(os.path.join(FIX, "good_episode.json"), encoding="utf-8")))
