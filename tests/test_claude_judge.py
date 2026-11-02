"""Claude 채점 파이프라인(`scripts/claude_judge.py`)의 배치 내보내기와 결과 검증 테스트."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from claude_judge import AXES, build_items, split_batches, validate_results  # noqa: E402


def _rec(i, answer="답", error=None):
    r = {"dataset": "new20", "id": f"m{i}", "repeat": 1, "answer": answer, "evidence": f"근거{i}",
         "retrieved_docs": [{"content": f"청크{i}-{j}"} for j in range(7)]}
    if error:
        r["error"] = error
    return r


ITEMS = {("new20", f"m{i}"): {"question": f"질문{i}", "expected_answer": f"정답{i}"} for i in range(1, 6)}


class TestBuildItems:
    def test_context_is_evidence_plus_top_k_chunks(self):
        items, mapping = build_items({("run", "sys"): [_rec(1)]}, ITEMS, k=5, seed=1)
        ctx = items[0]["context"]
        assert "근거1" in ctx and "청크1-4" in ctx and "청크1-5" not in ctx

    def test_item_ids_are_blind_and_mapping_keeps_the_origin(self):
        items, mapping = build_items({("dbcmp3", "A"): [_rec(1)], ("dbcmp4", "B"): [_rec(1)]}, ITEMS, k=5, seed=1)
        assert all(set(i) == {"item_id", "question", "expected_answer", "context", "generated_answer"} for i in items)
        assert {m["run"] for m in mapping.values()} == {"dbcmp3", "dbcmp4"}
        assert set(mapping) == {i["item_id"] for i in items}

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


# --- 루브릭 v2: 명시 규칙과 주된 값 힌트 -------------------------------------------------------------

def test_primary_hint_ignores_parenthetical_breakdown():
    from claude_judge import primary_hint

    hint = primary_hint("기초금액은 50,000,000원(추정가격 45,454,545원, 부가가치세 4,545,455원)입니다.",
                        "기초금액은 50,000,000원입니다.")
    assert hint["primary_values"] == ["50000000"]
    assert hint["missing"] == []


def test_primary_hint_reports_missing_values_and_tolerates_notation():
    from claude_judge import primary_hint

    expected = "설치대수는 240kW 파워뱅크 2기와 디스펜서 5기입니다."
    hint = primary_hint(expected, "240kW 파워뱅크 2기가 설치됩니다.")
    assert hint["missing"], "디스펜서 5기가 답변에 없다는 것을 알려야 한다"
    assert primary_hint("사업비는 50,000,000원입니다.", "사업비는 약 5,000만 원 (50,000,000 원)입니다.")["missing"] == []


def test_rubric_v2_states_the_rules_that_drifted_between_rounds():
    from claude_judge import INSTRUCTIONS_V2

    for needle in ("주된 값", "괄호", "Answer coverage", "라벨", "문서에서 확인되지 않습니다"):
        assert needle in INSTRUCTIONS_V2


def test_build_items_adds_hint_only_when_requested():
    from claude_judge import build_items

    records = {("r", "s"): [{"dataset": "new20", "id": "m1", "answer": "50,000,000원", "evidence": "", "retrieved_docs": []}]}
    dataset = {("new20", "m1"): {"question": "q", "expected_answer": "기초금액은 50,000,000원(부가세 포함)입니다."}}
    plain, _ = build_items(records, dataset, 5, 1)
    hinted, _ = build_items(records, dataset, 5, 1, with_hint=True)
    assert "hint" not in plain[0]
    assert hinted[0]["hint"]["primary_values"] == ["50000000"]


# --- 거부 답변: Faithfulness는 해당 없음(N/A)으로 집계에서 뺀다 ---------------------------------------

def test_is_refusal_detects_not_found_answers_only():
    from claude_judge import is_refusal

    assert is_refusal("문서에서 확인되지 않습니다.")
    assert is_refusal("비교 답변을 위해 문서 A/B를 모두 검색했지만 문서 B 근거 부족으로 단정 비교를 생략합니다.")
    assert not is_refusal("기초금액은 50,000,000원입니다.")
    assert not is_refusal("")


def test_rubric_v2_marks_refusal_faithfulness_as_not_applicable():
    from claude_judge import INSTRUCTIONS_V2

    assert "N/A" in INSTRUCTIONS_V2


def test_hint_flags_refusal_items():
    from claude_judge import build_items

    records = {("r", "s"): [{"dataset": "new20", "id": "m1", "answer": "문서에서 확인되지 않습니다.", "evidence": "", "retrieved_docs": []}]}
    dataset = {("new20", "m1"): {"question": "q", "expected_answer": "기초금액은 50,000,000원입니다."}}
    items, _ = build_items(records, dataset, 5, 1, with_hint=True)
    assert items[0]["hint"]["refusal"] is True


def test_import_keeps_the_previous_claude_cache_when_regrading_with_v2(tmp_path, monkeypatch):
    import json as _json

    import claude_judge as cj

    runs = tmp_path / "runs"
    cache = runs / "r1" / "judge_cache" / "sys"
    cache.mkdir(parents=True)
    (cache / "new20__m1__1.json").write_text('{"old": true}', encoding="utf-8")
    out = tmp_path / "round"
    (out / "results").mkdir(parents=True)
    (out / "rubric_version.txt").write_text("v2\n", encoding="utf-8")
    axes = {ax: {"score": 5, "reason": "ok"} for ax in cj.AXES}
    (out / "mapping.json").write_text(_json.dumps({"j0001": {"run": "r1", "system": "sys", "dataset": "new20", "id": "m1", "repeat": 1}}), encoding="utf-8")
    (out / "results" / "batch_01.json").write_text(_json.dumps({"j0001": axes}), encoding="utf-8")
    monkeypatch.setattr(cj, "RUNS_DIR", runs)
    import argparse

    cj.cmd_import(argparse.Namespace(out_dir=str(out)))
    assert (runs / "r1" / "judge_cache_v1_ref" / "sys" / "new20__m1__1.json").exists()
    assert _json.loads((cache / "new20__m1__1.json").read_text(encoding="utf-8"))["correctness"]["score"] == 5
    assert not (runs / "r1" / "judge_cache_gptoss_ref").exists()
