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


def test_trace_records_llm_calls_and_postprocess_without_changing_results():
    from types import SimpleNamespace

    from run_experiment import install_trace

    class Chat:
        model_name = "m"

        def _generate(self, messages, *a, **k):
            gen = SimpleNamespace(text="초안", message=SimpleNamespace(response_metadata={"finish_reason": "stop"}))
            return SimpleNamespace(generations=[gen])

    class Bot:
        @staticmethod
        def _compact_answer_sections(answer, style="concise"):
            return answer.split("\n")[0]

        def _polish_answer_with_llm(self, answer):
            return answer + "!"

    trace: list = []
    install_trace(Chat, Bot, trace)
    msgs = [SimpleNamespace(type="human", content="질문")]
    assert Chat()._generate(msgs).generations[0].text == "초안"
    assert Bot._compact_answer_sections("a\nb") == "a"
    assert Bot()._polish_answer_with_llm("x") == "x!"
    assert [t["stage"] for t in trace] == ["llm", "_compact_answer_sections", "_polish_answer_with_llm"]
    assert trace[0]["input"] == [{"role": "human", "content": "질문"}] and trace[0]["finish_reason"] == "stop"
