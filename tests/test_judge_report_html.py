"""Claude 채점 한 회차를 팀의 HTML 보고서(`scripts/build_eval_report.py`)로 만드는 부분의 테스트."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from build_eval_report import build_html  # noqa: E402
from judge_report_html import AXES, build_results  # noqa: E402


def _fixture(tmp_path):
    rd = tmp_path / "round19"
    (rd / "batches").mkdir(parents=True)
    (rd / "results").mkdir()
    item = {"item_id": "j0001", "question": "질문", "expected_answer": "정답", "context": "근거 </script> <b>", "generated_answer": "답"}
    (rd / "batches" / "batch_01.json").write_text(json.dumps([item]), encoding="utf-8")
    (rd / "results" / "batch_01.json").write_text(
        json.dumps({"j0001": {a: {"score": 4, "reason": f"{a} 사유"} for a in AXES}}), encoding="utf-8")
    origin = {"run": "r1", "system": "s", "dataset": "new20", "id": "m1", "repeat": 1}
    (rd / "mapping.json").write_text(json.dumps({"j0001": origin}), encoding="utf-8")
    (rd / "rubric.md").write_text("채점 기준 전문", encoding="utf-8")
    (rd / "instruction.txt").write_text("지시문 전문", encoding="utf-8")
    run = tmp_path / "runs" / "r1"
    run.mkdir(parents=True)
    raw = {"dataset": "new20", "id": "m1", "retrieved_docs": [{"source": "문서"}], "latencies": {"analyze_query": 1.0},
           "csv_short_circuit": False, "source_type": "hwp"}
    (run / "s_raw.json").write_text(json.dumps([raw]), encoding="utf-8")
    metrics = {"n_queries": 1, "n_scored": 1, "correctness_all": 4.0, "answer_coverage_all": 4.0, "faithfulness_all": 4.0,
               "context_relevance_all": 4.0, "source_recall_at_k": 1.0, "source_mrr": 1.0, "chunk_recall_at_k": 0.5,
               "chunk_recall_labeled_n": 1}
    row = {"dataset": "new20", "id": "m1", "source_hit_position": 1, "source_recall": 1.0, "chunk_recall": 0.5}
    (run / "summary.json").write_text(json.dumps({"top_k": 5, "systems": {"s": {"metrics": metrics, "per_query": [row]}}}), encoding="utf-8")
    dataset = {("new20", "m1"): {"query_type": "single_doc", "ground_truth": {"sources": ["문서"]}}}
    return rd, tmp_path / "runs", dataset


def test_results_carry_the_grading_input_and_scores_in_the_team_format(tmp_path):
    rd, runs, dataset = _fixture(tmp_path)
    res = build_results(rd, "r1", "s", dataset, runs)
    [q] = res["per_query"]
    assert q["judge_context"] == "근거 </script> <b>" and q["generated_answer"] == "답" and q["expected_answer"] == "정답"
    assert q["correctness"] == {"score": 4, "reason": "correctness 사유"} and q["hit_position"] == 1
    assert q["memo"] == "batch_01 · j0001" and q["ground_truth_sources"] == ["문서"]
    assert res["summary"]["avg_correctness"] == 4.0 and res["summary"]["recall_at_k_source"] == 1.0
    assert res["meta"]["rubric"] == "채점 기준 전문" and res["meta"]["instruction"] == "지시문 전문"


def test_html_shows_chunk_recall_and_marks_answers_that_used_no_chunks(tmp_path):
    rd, runs, dataset = _fixture(tmp_path)
    results = build_results(rd, "r1", "s", dataset, runs)
    page = build_html(results)
    assert "Recall@5 (Chunk)" in page and "<strong>Recall@K (chunk):</strong> 50%" in page
    results["per_query"][0]["recall_at_k_chunk"] = None
    assert "<strong>Recall@K (chunk):</strong> 해당 없음" in build_html(results)


def test_html_shows_the_grading_input_escaped_and_no_claims_from_the_old_run(tmp_path):
    rd, runs, dataset = _fixture(tmp_path)
    page = build_html(build_results(rd, "r1", "s", dataset, runs))
    assert "근거 &lt;/script&gt; &lt;b&gt;" in page and "채점 기준 전문" in page and "지시문 전문" in page
    assert "근거 </script>" not in page
    assert "gpt-5-mini" not in page and "Claude(subagent, Opus)" in page
