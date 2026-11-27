"""Claude 채점 파이프라인(`scripts/claude_judge.py`)의 배치 내보내기와 결과 검증 테스트."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from claude_judge import AXES, build_items, split_batches, validate_results  # noqa: E402


def _rec(i, answer="답", error=None):
    r = {"dataset": "new20", "id": f"m{i}", "repeat": 1, "answer": answer, "evidence": f"근거{i}",
         "retrieved_docs": [{"content": f"청크{i}-{j}"} for j in range(7)]}
    if error:
        r["error"] = error
    return r


ITEMS = {("new20", f"m{i}"): {"question": f"질문{i}", "expected_answer": f"정답{i}"} for i in range(1, 6)}


class TestBuildItems:
    def test_context_is_evidence_plus_top_k_chunk_text_without_document_names(self):
        rec = _rec(1)
        rec["retrieved_docs"][0]["source"] = "문서 이름"
        items, _ = build_items({("run", "sys"): [rec]}, ITEMS, k=5, seed=1)
        assert items[0]["context"] == "근거1\n\n" + "\n\n".join(f"청크1-{j}" for j in range(5))

    def test_item_ids_are_blind_and_mapping_keeps_the_origin(self):
        items, mapping = build_items({("dbcmp3", "A"): [_rec(1)], ("dbcmp4", "B"): [_rec(1)]}, ITEMS, k=5, seed=1)
        assert all(set(i) == {"item_id", "question", "expected_answer", "context", "generated_answer"} for i in items)
        assert {m["run"] for m in mapping.values()} == {"dbcmp3", "dbcmp4"}
        assert set(mapping) == {i["item_id"] for i in items}

    def test_identical_answers_stay_separate_items(self):
        items, _ = build_items({("r", "A"): [_rec(1)], ("r", "B"): [_rec(1)]}, ITEMS, k=5, seed=1)
        assert len(items) == 2

    def test_shuffle_is_deterministic_for_a_seed(self):
        recs = {("r", "s"): [_rec(i) for i in range(1, 6)]}
        a, _ = build_items(recs, ITEMS, k=5, seed=7)
        b, _ = build_items(recs, ITEMS, k=5, seed=7)
        assert [i["question"] for i in a] == [i["question"] for i in b]

    def test_errored_records_are_skipped(self):
        items, _ = build_items({("r", "s"): [_rec(1), _rec(2, error="x")]}, ITEMS, k=5, seed=1)
        assert len(items) == 1


def test_split_batches_sizes():
    assert [len(b) for b in split_batches(list(range(25)), 10)] == [10, 10, 5]


def _ok():
    return {a: {"score": 4, "reason": "근거"} for a in AXES}


class TestValidateResults:
    def test_complete_valid_results_pass(self):
        assert validate_results({"j1": _ok()}, ["j1"]) == []

    def test_missing_items_are_reported(self):
        assert any("j2" in p for p in validate_results({"j1": _ok()}, ["j1", "j2"]))

    def test_score_must_be_an_integer_between_0_and_5(self):
        bad = _ok(); bad["correctness"]["score"] = 7
        assert any("correctness" in p for p in validate_results({"j1": bad}, ["j1"]))
        bad2 = _ok(); bad2["faithfulness"]["score"] = 3.5
        assert any("faithfulness" in p for p in validate_results({"j1": bad2}, ["j1"]))

    def test_missing_axis_is_reported(self):
        bad = _ok(); del bad["context_relevance"]
        assert any("context_relevance" in p for p in validate_results({"j1": bad}, ["j1"]))

    def test_unknown_items_are_reported(self):
        assert any("j9" in p for p in validate_results({"j1": _ok(), "j9": _ok()}, ["j1"]))


# --- 채점 기준: 팀 rubric + 추가 기준 3개 -------------------------------------------------------------

def test_rubric_is_the_team_prompt_followed_only_by_the_three_approved_criteria():
    from claude_judge import rubric_text
    from src.evaluation.llm_judge import JUDGE_SYSTEM_PROMPT

    assert rubric_text() == JUDGE_SYSTEM_PROMPT + """

## 추가 기준
1. Correctness는 기대 답변의 주된 값(괄호 밖의 값과 사실)으로 판단한다.
   괄호 안의 값이 빠지거나 달라도 Correctness를 깎지 않는다.
   괄호 밖의 값과 사실은 모두 있어야 한다.
2. 비교 질문의 답은 비교 결과다. 비교의 근거가 된 값이 답변에 없어도
   Correctness와 Answer coverage를 깎지 않는다.
3. 질문이 묻는 금액의 이름과 답변이 쓴 이름이 달라도(예: 기초금액을 사업비로)
   값이 같으면 Correctness와 Answer coverage를 깎지 않는다.
"""


def test_import_writes_the_scores_and_keeps_the_v4_cache(tmp_path, monkeypatch):
    import argparse
    import json as _json

    import claude_judge as cj

    cache = tmp_path / "runs" / "r1" / "judge_cache" / "sys"
    cache.mkdir(parents=True)
    (cache / "new20__m1__1.json").write_text('{"old": true}', encoding="utf-8")
    out = tmp_path / "round"
    (out / "results").mkdir(parents=True)
    (out / "rubric_version.txt").write_text("v5\n", encoding="utf-8")
    origin = {"run": "r1", "system": "sys", "dataset": "new20", "id": "m1", "repeat": 1}
    (out / "mapping.json").write_text(_json.dumps({"j0001": origin}), encoding="utf-8")
    axes = {ax: {"score": 5, "reason": "ok"} for ax in cj.AXES}
    (out / "results" / "batch_01.json").write_text(_json.dumps({"j0001": axes}), encoding="utf-8")
    monkeypatch.setattr(cj, "RUNS_DIR", tmp_path / "runs")

    cj.cmd_import(argparse.Namespace(out_dir=str(out)))
    assert (tmp_path / "runs" / "r1" / "judge_cache_v4_ref" / "sys" / "new20__m1__1.json").exists()
    assert _json.loads((cache / "new20__m1__1.json").read_text(encoding="utf-8"))["correctness"]["score"] == 5
