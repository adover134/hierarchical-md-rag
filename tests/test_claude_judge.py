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
        assert {o["run"] for m in mapping.values() for o in m["origins"]} == {"dbcmp3", "dbcmp4"}
        assert set(mapping) == {i["item_id"] for i in items}

    def test_shuffle_is_deterministic_for_a_seed(self):
        recs = {("r", "s"): [_rec(i) for i in range(1, 6)]}
        a, _ = build_items(recs, ITEMS, k=5, seed=7)
        b, _ = build_items(recs, ITEMS, k=5, seed=7)
        assert [i["question"] for i in a] == [i["question"] for i in b]

    def test_identical_items_are_graded_once_and_keep_every_origin(self):
        items, mapping = build_items({("r", "A"): [_rec(1), _rec(2)], ("r", "B"): [_rec(1), _rec(2, answer="다른 답")]}, ITEMS, k=5, seed=1)
        assert len(items) == 3
        assert sorted(len(m["origins"]) for m in mapping.values()) == [1, 1, 2]

    def test_errored_records_are_skipped(self):
        items, _ = build_items({("r", "s"): [_rec(1), _rec(2, error="x")]}, ITEMS, k=5, seed=1)
        assert len(items) == 1


class TestContext:
    def _ctx(self, evidence, docs, k=5):
        rec = {"dataset": "new20", "id": "m1", "answer": "답", "evidence": evidence,
               "retrieved_docs": [{"source": s, "content": c} for s, c in docs]}
        items, _ = build_items({("r", "s"): [rec]}, ITEMS, k=k, seed=1)
        return items[0]["context"]

    def test_every_block_names_its_document(self):
        ctx = self._ctx("", [("가 사업_가 기관", "사업비: 1원"), ("나 사업_나 기관", "사업비: 2원")])
        assert "[문서: 가 사업_가 기관]\n사업비: 1원" in ctx
        assert "[문서: 나 사업_나 기관]\n사업비: 2원" in ctx

    def test_evidence_already_inside_a_chunk_is_not_repeated(self):
        ctx = self._ctx("사업비: 1원", [("가", "사업비: 1원")])
        assert ctx.count("사업비: 1원") == 1

    def test_evidence_from_a_chunk_below_top_k_keeps_that_document_name(self):
        ctx = self._ctx("기간: 60일", [("가", "본문"), ("나", "기간: 60일 이내")], k=1)
        assert "[문서: 나]\n기간: 60일" in ctx and "이내" not in ctx

    def test_evidence_differing_only_in_spacing_and_marks_is_not_repeated(self):
        ctx = self._ctx("입찰 보증금은 「유의서」에 따라 귀속됩니다.", [("가", "**입찰보증금**은\n「유의서」에 따라 귀속됩니다")])
        assert ctx.count("귀속") == 1

    def test_reworked_evidence_takes_the_document_that_has_its_opening(self):
        opening = "입찰건명: 납품기한및장소, 2027학년도 교복 구매 2단계 입찰 재공고: 동복 2027. 2. 19.(금) 학교 사정에 따라 변동"
        ctx = self._ctx(opening + ", 하복 5. 7.", [("가", "다른 본문"), ("나", opening + ", Col3: 중복 칸")], k=1)
        assert "[문서: 나]\n" + opening in ctx

    def test_evidence_found_in_no_chunk_is_kept_and_marked(self):
        assert "[문서: 표시 없음]\n요약한 근거" in self._ctx("요약한 근거", [("가", "본문")])


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


# --- 루브릭: 명시 규칙과 주된 값 힌트 -------------------------------------------------------------

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


def test_rubric_v3_states_the_rules_that_drifted_between_rounds():
    from claude_judge import INSTRUCTIONS_V3

    for needle in ("주된 값", "괄호", "Answer coverage", "라벨", "문서에서 확인되지 않습니다", "[문서: "):
        assert needle in INSTRUCTIONS_V3


def test_rubric_v3_makes_the_chosen_target_the_only_primary_fact_of_a_comparison():
    from claude_judge import INSTRUCTIONS_V3

    assert "선택한 대상 하나" in INSTRUCTIONS_V3
    assert "과 있으면 그 값" not in INSTRUCTIONS_V3


def test_comparison_question_hint_does_not_list_compared_values():
    from claude_judge import primary_hint

    expected = "(건축)(368,467,000원)가 (통신)(24,867,000원)보다 기초금액이 더 큽니다."
    hint = primary_hint(expected, "(건축)이 더 큽니다.", question="(건축)와 (통신) 중 기초금액이 더 큰 공사는 무엇인가요?")
    assert hint["comparison"] is True and hint["primary_values"] == [] and hint["missing"] == []


def test_comparison_question_that_also_asks_the_value_keeps_the_values():
    from claude_judge import primary_hint

    hint = primary_hint("가가 2,000,000원 더 큽니다.", "가가 더 큽니다.", question="가와 나 중 어느 쪽이 더 큰 금액이며 차이는 얼마인가요?")
    assert hint["comparison"] is False and hint["primary_values"]


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


def test_rubric_v3_marks_refusal_faithfulness_as_not_applicable():
    from claude_judge import INSTRUCTIONS_V3

    assert "N/A" in INSTRUCTIONS_V3


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


def test_import_v3_writes_every_origin_and_keeps_the_v2_cache(tmp_path, monkeypatch):
    import argparse
    import json as _json

    import claude_judge as cj

    runs = tmp_path / "runs"
    for system in ("a", "b"):
        cache = runs / "r1" / "judge_cache" / system
        cache.mkdir(parents=True)
        (cache / "new20__m1__1.json").write_text('{"old": true}', encoding="utf-8")
    out = tmp_path / "round"
    (out / "results").mkdir(parents=True)
    (out / "rubric_version.txt").write_text("v3\n", encoding="utf-8")
    origins = [{"run": "r1", "system": s, "dataset": "new20", "id": "m1", "repeat": 1} for s in ("a", "b")]
    (out / "mapping.json").write_text(_json.dumps({"j0001": {"origins": origins}}), encoding="utf-8")
    axes = {ax: {"score": 5, "reason": "ok"} for ax in cj.AXES}
    (out / "results" / "batch_01.json").write_text(_json.dumps({"j0001": axes}), encoding="utf-8")
    monkeypatch.setattr(cj, "RUNS_DIR", runs)

    cj.cmd_import(argparse.Namespace(out_dir=str(out)))
    for system in ("a", "b"):
        assert (runs / "r1" / "judge_cache_v2_ref" / system / "new20__m1__1.json").exists()
        new = runs / "r1" / "judge_cache" / system / "new20__m1__1.json"
        assert _json.loads(new.read_text(encoding="utf-8"))["correctness"]["score"] == 5


def test_is_refusal_ignores_a_stray_not_found_line_after_a_real_answer():
    from claude_judge import is_refusal

    long_answer = ("공사기간은 90일입니다. - 등록개시: 2026.8.10. 10:00, 마감 및 개찰: 2026.8.14. 10:00/11:00. "
                   "- 사업명: 지역농업개발센터 시설개선 공사(안남·청산분소)(건축). - 담당: 농업기술센터 기술지원과 지도기획팀입니다. - 문서에서 확인되지 않습니다.")
    assert not is_refusal(long_answer)
    assert is_refusal("요청하신 값은 `문서에서 확인되지 않습니다.`입니다.")
