import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "plugins/skip-the-comment/skills/skip-the-comment/scripts"
sys.path.insert(0, str(SCRIPTS))
MODEL_CACHE = Path(__file__).resolve().parents[1] / ".venv-dev" / "models"  # persistent, git-ignored


@pytest.fixture(autouse=True)
def isolated_dirs(tmp_path, monkeypatch):
    """Isolate all tests from the real user home directories."""
    monkeypatch.setenv("SKIP_THE_COMMENT_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setenv("SKIP_THE_COMMENT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("SKIP_THE_COMMENT_MODEL_DIR", str(MODEL_CACHE))
    monkeypatch.delenv("SKIP_THE_COMMENT_CHILD", raising=False)
