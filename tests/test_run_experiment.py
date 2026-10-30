"""실험 실행기의 채점·집계·리포트 배선 테스트 — Judge는 캐시로 대체해 LLM/DB 없이 실행한다."""

import argparse
import json

import yaml

import run_experiment as R


def _setup(tmp_path):
    ds = tmp_path / "ds.yaml"
    ds.write_text(yaml.safe_dump([
        {"id": "a1", "question": "기초금액은?", "expected_answer": "기초금액은 285,125,000원입니다.",
         "ground_truth": {"sources": ["문서A_기관"]}},
        {"id": "a2", "question": "공사기간은?", "expected_answer": "공사기간은 60일입니다.",
         "ground_truth": {"sources": ["문서B_기관"]}},
    ], allow_unicode=True), encoding="utf-8")
    ts = tmp_path / "tables.yaml"
    ts.write_text(yaml.safe_dump([
        {"source": "문서B_기관", "pairs": [{"label": "공사기간", "value": "착공일로부터 60일"}, {"label": "납품기한", "value": "30일"}]},
    ], allow_unicode=True), encoding="utf-8")
    cfg = {
        "runs_dir": str(tmp_path / "runs"), "top_k": 5,
        "llm": {"base_url": "http://localhost:11434/v1", "api_key": "x", "model": "m", "judge_model": "m"},
        "datasets": [{"name": "d1", "path": str(ds), "role": "existing", "enabled": True}],
        "tags": {"regression_pass_score": 4, "regression": {"d1": ["a2"]}, "numeric_compare": {}},
        "table_samples": str(ts),
        "systems": [{"name": "sysA", "title": "시스템 A", "kind": "current", "project_root": str(tmp_path), "env": {}}],
    }
    rd = tmp_path / "runs" / "r1"
    (rd / "judge_cache" / "sysA").mkdir(parents=True)
    raw = [
        {"dataset": "d1", "id": "a1", "repeat": 1, "answer": "285,125,000원", "evidence": "",
         "retrieved_docs": [{"source": "문서A_기관.hwpx", "content": "기초금액 285,125,000원", "chunk_id": "c1", "score": 0.9}],
         "latencies": {"retrieve": 1.0, "generate": 3.0}, "wall_seconds": 5.0},
        {"dataset": "d1", "id": "a2", "repeat": 1, "answer": "모릅니다", "evidence": "",
         "retrieved_docs": [{"source": "문서C_기관.pdf", "content": "무관", "chunk_id": "c2", "score": 0.1}],
         "latencies": {"retrieve": 2.0, "generate": 4.0}, "wall_seconds": 7.0},
    ]
    (rd / "sysA_raw.json").write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    chunks = [
        {"id": "c1", "text": "기초금액 285,125,000원", "source": "문서A_기관.hwpx", "section_level1": "1. 개요", "section_level2": "N/A"},
        {"id": "c2", "text": "무관", "source": "문서C_기관.pdf", "section_level1": "N/A", "section_level2": "N/A"},
        {"id": "c3", "text": "공사기간: 착공일로부터 60일", "source": "문서B_기관.pdf", "section_level1": "N/A", "section_level2": "N/A"},
    ]
    (rd / "sysA_chunks.json").write_text(json.dumps(chunks, ensure_ascii=False), encoding="utf-8")
    for key, score in (("a1", 5), ("a2", 1)):
        judge = {k: {"score": score, "reason": ""} for k in ("correctness", "answer_coverage", "faithfulness", "context_relevance")}
        (rd / "judge_cache" / "sysA" / f"d1__{key}__1.json").write_text(json.dumps(judge), encoding="utf-8")
    return cfg, rd


def test_evaluate_and_report(tmp_path):
    cfg, rd = _setup(tmp_path)
    args = argparse.Namespace(run_id="r1", systems=None, write=False)
    R.cmd_evaluate(cfg, args)
    m = json.loads((rd / "summary.json").read_text(encoding="utf-8"))["systems"]["sysA"]["metrics"]

    assert m["n_scored"] == 2 and m["n_errors"] == 0
    assert m["correctness_all"] == 3.0 and m["correctness_existing"] == 3.0
    # 핵심값: a1은 1위에서 확보, a2("60일")는 검색 텍스트에 없음 → 적격 2건 중 1건
    assert m["kv_eligible_n"] == 2
    assert m["context_hit_at_5"] == 0.5 and m["kv_mrr"] == 0.5
    # 헤더 포함률: c1은 섹션 있음, c2는 없음
    assert m["header_inclusion"] == 0.5
    # 회귀 묶음(a2)은 correctness 1 → 불통과
    assert m["regression_pass_rate"] == 0.0 and m["regression_n"] == 1
    # 표 정합률: 공사기간 쌍은 있고 납품기한 쌍은 없음
    assert m["table_pair_accuracy"] == 0.5 and m["table_pairs_n"] == 2
    # 청킹 통계
    assert m["chunk_count"] == 3 and m["chunk_docs_indexed"] == 3 and m["chunk_section_coverage"] == round(1 / 3, 4)
    assert m["api_cost_usd"] == 0.0
    assert m["latency_retrieve_sec"] == 1.5 and m["latency_wall_sec"] == 6.0

    text = R.render_report(json.loads((rd / "summary.json").read_text(encoding="utf-8")), cfg)
    assert "시스템 A" in text and "Context Hit Rate@3" in text and "청크 길이 평균" in text


def test_remote_endpoint_is_not_reported_as_free(tmp_path):
    cfg, rd = _setup(tmp_path)
    cfg["llm"]["base_url"] = "https://api.openai.com/v1"
    R.cmd_evaluate(cfg, argparse.Namespace(run_id="r1", systems=None, write=False))
    m = json.loads((rd / "summary.json").read_text(encoding="utf-8"))["systems"]["sysA"]["metrics"]
    assert m["api_cost_usd"] is None
