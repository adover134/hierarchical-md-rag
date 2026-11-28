"""격리 채점(`scripts/judge_grade.py`)의 테스트."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import judge_grade  # noqa: E402
from judge_grade import BASE_INSTRUCTION, batch_schema, grade_round, system_prompt  # noqa: E402

AXES = ("correctness", "answer_coverage", "faithfulness", "context_relevance")


def _round(tmp_path, batches=(("j0001", "j0002"), ("j0003",))):
    (tmp_path / "batches").mkdir(parents=True)
    (tmp_path / "rubric.md").write_text("루브릭 전문", encoding="utf-8")
    (tmp_path / "instruction.txt").write_text(BASE_INSTRUCTION + "\n검증 지시\n", encoding="utf-8")
    for n, ids in enumerate(batches, 1):
        items = [{"item_id": i, "question": f"질문 {i}"} for i in ids]
        (tmp_path / "batches" / f"batch_{n:02d}.json").write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")
    return tmp_path


def _scores(items):
    return {i["item_id"]: {a: {"score": 5, "reason": "ok"} for a in AXES} for i in items}


def test_system_prompt_is_the_rubric_followed_by_the_grading_instruction(tmp_path):
    rd = _round(tmp_path)
    assert system_prompt(rd) == "루브릭 전문\n\n## 채점 지시\n" + BASE_INSTRUCTION + "\n검증 지시\n"


def test_schema_requires_every_item_and_every_axis():
    schema = batch_schema(["j0001", "j0002"])
    assert schema["required"] == ["j0001", "j0002"] and schema["additionalProperties"] is False
    item = schema["properties"]["j0001"]
    assert item["required"] == list(AXES)
    assert item["properties"]["correctness"]["properties"]["score"] == {"type": "integer", "minimum": 0, "maximum": 5}


def test_each_batch_is_sent_alone_and_its_results_are_written(tmp_path):
    rd, sent = _round(tmp_path), []

    def ask(system, message, schema):
        sent.append((system, message, schema["required"]))
        return _scores(json.loads(message))

    grade_round(rd, ask, workers=1)
    assert [s[2] for s in sent] == [["j0001", "j0002"], ["j0003"]]
    assert all(s[0] == system_prompt(rd) and "질문 j0003" not in sent[0][1] for s in sent)
    assert set(json.loads((rd / "results" / "batch_01.json").read_text(encoding="utf-8"))) == {"j0001", "j0002"}


def test_finished_batches_are_kept_and_invalid_replies_are_not_written(tmp_path):
    rd = _round(tmp_path)
    (rd / "results").mkdir()
    (rd / "results" / "batch_01.json").write_text('{"kept": 1}', encoding="utf-8")
    with pytest.raises(RuntimeError, match="batch_02"):
        grade_round(rd, lambda system, message, schema: {}, workers=1)
    assert (rd / "results" / "batch_01.json").read_text(encoding="utf-8") == '{"kept": 1}'
    assert not (rd / "results" / "batch_02.json").exists()


def test_the_grader_call_has_no_instruction_files_no_tools_and_an_empty_folder(monkeypatch):
    seen = {}

    class Done:
        stdout = json.dumps({"structured_output": {"ok": 1}, "total_cost_usd": 0.1, "modelUsage": {"m": {"inputTokens": 3, "outputTokens": 4, "costUSD": 0.1}}})

    def run(cmd, **kwargs):
        seen.update(cmd=cmd, cwd=kwargs["cwd"], input=kwargs["input"], files=list(Path(kwargs["cwd"]).iterdir()))
        return Done()

    monkeypatch.setattr(judge_grade.subprocess, "run", run)
    calls = []
    assert judge_grade.claude_ask(calls)("지시", "항목", {"type": "object"}) == {"ok": 1}
    cmd = seen["cmd"]
    assert cmd[:3] == ["claude", "-p", "--safe-mode"] and cmd[cmd.index("--tools") + 1] == ""
    assert cmd[cmd.index("--system-prompt") + 1] == "지시" and "--no-session-persistence" in cmd
    assert seen["input"] == "항목" and seen["files"] == [] and calls == [{"cost_usd": 0.1, "models": ["m"], "usage": {"m": {"inputTokens": 3, "outputTokens": 4}}}]
