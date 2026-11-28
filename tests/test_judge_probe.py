"""채점기 시험 묶음(`scripts/judge_probe.py`)의 테스트."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from judge_probe import build_probe, check_probe  # noqa: E402

AXES = ("correctness", "answer_coverage", "faithfulness", "context_relevance")


def _scores(**low):
    return {a: {"score": low.get(a, 5), "reason": "r"} for a in AXES}


def _source(tmp_path):
    rd = tmp_path / "source"
    (rd / "batches").mkdir(parents=True)
    (rd / "results").mkdir()
    items = [{"item_id": f"j{n}", "question": f"질문 {n}", "expected_answer": f"{n}원", "context": f"근거 {n}원",
              "generated_answer": f"답 {n}원", "검증 결과": {"old": True}} for n in (1, 2, 3)]
    (rd / "batches" / "batch_01.json").write_text(json.dumps(items), encoding="utf-8")
    (rd / "mapping.json").write_text(json.dumps(
        {f"j{n}": {"run": "r", "system": "s", "dataset": "new20", "id": f"m{n}", "repeat": 1} for n in (1, 2, 3)}), encoding="utf-8")
    (rd / "results" / "batch_01.json").write_text(json.dumps(
        {"j1": _scores(), "j2": _scores(context_relevance=4), "j3": _scores()}), encoding="utf-8")
    return rd


VERIFICATION = {f"new20/m{n}": {"result": {"notices": [], "answer": f"{n}", "unverified": ""}} for n in (1, 2, 3)}
CASES = {
    "context_swaps": [{"id": "m1", "system": "s", "context_from": {"id": "m3", "system": "s"}, "kind": "다른 공고"}],
    "altered_answers": [{"id": "m3", "system": "s", "replace": [["답 3원", "답 9원"]]}],
    "keep_deducted": [{"id": "m1", "system": "s", "axes": ["correctness"]}],
}


def _built(tmp_path):
    out = tmp_path / "probe"
    build_probe(_source(tmp_path), VERIFICATION, CASES, out)
    items = {i["item_id"]: i for f in sorted((out / "batches").glob("*.json")) for i in json.loads(f.read_text(encoding="utf-8"))}
    mapping = json.loads((out / "mapping.json").read_text(encoding="utf-8"))
    return out, items, mapping


def test_build_collects_deducted_kept_swapped_and_altered_items_with_the_new_verification(tmp_path):
    out, items, mapping = _built(tmp_path)
    by_kind = {o["kind"]: (items[i], o) for i, o in mapping.items()}
    assert set(by_kind) == {"context 바꿈", "값 바꿈", "감점 유지", "감점 항목"}
    assert by_kind["감점 항목"][1]["id"] == "m2" and by_kind["감점 유지"][1]["keep"] == ["correctness"]
    assert by_kind["context 바꿈"][0]["context"] == "근거 3원" and by_kind["context 바꿈"][0]["question"] == "질문 1"
    assert by_kind["값 바꿈"][0]["generated_answer"] == "답 9원" and by_kind["값 바꿈"][0]["context"] == "근거 3원"
    assert all(i["검증 결과"]["answer"] == mapping[k]["id"][1] for k, i in items.items())
    assert (out / "rubric.md").exists() and (out / "instruction.txt").exists() and (out / "rubric_version.txt").exists()


def test_build_refuses_a_replacement_that_changes_nothing_or_appears_in_the_context(tmp_path):
    source = _source(tmp_path)
    for old, new in (("없는 말", "x"), ("답 3원", "근거 3원")):
        cases = {"altered_answers": [{"id": "m3", "system": "s", "replace": [[old, new]]}]}
        with pytest.raises(ValueError):
            build_probe(source, VERIFICATION, cases, tmp_path / f"p{new}")


def test_a_swap_case_may_carry_the_other_context_itself(tmp_path):
    cases = {"context_swaps": [{"id": "m1", "system": "s", "context": "문항에 없는 공고의 근거", "kind": "다른 지역"}]}
    build_probe(_source(tmp_path), VERIFICATION, cases, tmp_path / "probe")
    items = [i for f in sorted((tmp_path / "probe" / "batches").glob("*.json")) for i in json.loads(f.read_text(encoding="utf-8"))]
    assert "문항에 없는 공고의 근거" in [i["context"] for i in items]


def test_check_passes_only_when_every_planted_error_is_deducted_and_kept_items_stay_deducted(tmp_path):
    out, _, mapping = _built(tmp_path)
    kinds = {o["kind"]: i for i, o in mapping.items()}
    good = {i: _scores() for i in mapping}
    good[kinds["context 바꿈"]] = _scores(context_relevance=3)
    good[kinds["값 바꿈"]] = _scores(correctness=1, faithfulness=1)
    good[kinds["감점 유지"]] = _scores(correctness=4)
    (out / "results").mkdir(exist_ok=True)
    (out / "results" / "batch_01.json").write_text(json.dumps(good), encoding="utf-8")
    report = check_probe(out)
    assert [(r["name"], r["passed"], r["total"]) for r in report] == [("context 바꿈", 1, 1), ("값 바꿈", 1, 1), ("감점 유지", 1, 1)]

    bad = {**good, kinds["값 바꿈"]: _scores(correctness=1), kinds["감점 유지"]: _scores()}
    (out / "results" / "batch_01.json").write_text(json.dumps(bad), encoding="utf-8")
    report = check_probe(out)
    assert [r["passed"] for r in report] == [1, 0, 0] and report[1]["failures"] == ["s m3"]


def test_check_stops_when_results_are_missing(tmp_path):
    out, _, _ = _built(tmp_path)
    with pytest.raises(ValueError, match="빠진 결과"):
        check_probe(out)
