"""채점 가드(`scripts/run_experiment.py`)의 테스트: 채점은 Claude 캐시가 있어야 하고, 없으면 gpt-oss로 대신 채점하지 않고 멈춘다."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from run_experiment import load_claude_judgment  # noqa: E402


def test_cached_judgment_is_returned(tmp_path):
    f = tmp_path / "new20__m1__1.json"
    f.write_text(json.dumps({"correctness": {"score": 5, "reason": "x"}}), encoding="utf-8")
    assert load_claude_judgment(f)["correctness"]["score"] == 5


def test_missing_cache_stops_instead_of_grading_with_the_local_model(tmp_path):
    with pytest.raises(SystemExit) as exc:
        load_claude_judgment(tmp_path / "new20__m1__1.json")
    assert "claude_judge.py" in str(exc.value)
