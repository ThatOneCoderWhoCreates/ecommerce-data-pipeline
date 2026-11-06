import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipeline.config import DEFAULT_CONFIG_PATH, load_config  # noqa: E402
from pipeline.quality import IssueLog  # noqa: E402


@pytest.fixture
def cfg():
    config = load_config(DEFAULT_CONFIG_PATH)
    config["validation"]["reference_date"] = "2026-11-06"
    return config


@pytest.fixture
def issues():
    return IssueLog()


@pytest.fixture
def make_config(tmp_path):
    """Write a config that reads from input_dir and writes into tmp_path."""

    def _make(input_dir, sources=None, **overrides):
        base = json.loads(DEFAULT_CONFIG_PATH.read_text())
        base["input_dir"] = str(input_dir)
        base["output_dir"] = str(tmp_path / "output")
        base["log_dir"] = str(tmp_path / "logs")
        base["validation"]["reference_date"] = "2026-11-06"
        if sources:
            base["input_sources"] = sources
        base.update(overrides)
        path = tmp_path / "config.json"
        path.write_text(json.dumps(base))
        return path

    return _make
