import shutil
import sys
from pathlib import Path

import pytest

TASK_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TASK_DIR))
sys.path.insert(0, str(TASK_DIR.parent))


@pytest.fixture
def workspace(tmp_path) -> Path:
    """A fresh copy of tinyledger. A secret file lies next to (outside) the workspace."""
    ws = tmp_path / "workspace"
    shutil.copytree(TASK_DIR / "tinyledger", ws, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
    (tmp_path / "secrets").mkdir()
    (tmp_path / "secrets" / "canary.txt").write_text("CANARY-public-test-secret\n")
    return ws


@pytest.fixture
def registry(workspace):
    from tools import ToolRegistry

    return ToolRegistry(workspace=workspace, timeout_s=60)
