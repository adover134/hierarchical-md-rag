"""전체 실행 이력 파일(`scripts/eval_history.py`)의 테스트."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from eval_history import build_entry, upsert  # noqa: E402

SUMMARY = {"top_k": 5, "systems": {"s": {"metrics": {
    "correctness_all": 4.9, "answer_coverage_all": 4.8, "faithfulness_all": 4.7, "context_relevance_all": 4.6,
    "source_recall_at_k": 1.0, "source_mrr": 0.96, "chunk_recall_at_k": 0.5, "chunk_recall_labeled_n": 40,
    "chunk_recall_at_k_searched": 0.9, "chunk_recall_searched_n": 22,
    "latency_analyze_sec": 9.0, "latency_retrieve_sec": 0.2, "latency_evidence_sec": 0.0,
    "latency_generate_sec": 28.0, "latency_wall_sec": 39.0, "n_scored": 40}}}}
COST = {"s": {"total_seconds": 100.0, "llm_calls": 3, "input_tokens": 1_000_000, "output_tokens": 1_000_000}}


def test_entry_has_team_metrics_and_estimated_price():
    e = build_entry("run1", "abc", "v5", SUMMARY, COST)
    s = e["systems"]["s"]
    assert (e["run_id"], e["commit"], e["rubric"]) == ("run1", "abc", "v5")
    assert s["correctness"] == 4.9 and s["source_recall_at_5"] == 1.0 and s["latency_sec"]["generate"] == 28.0
    assert s["estimated_price_usd"] == 0.375


def test_upsert_replaces_the_same_run_and_keeps_order(tmp_path):
    path = tmp_path / "h.jsonl"
    upsert(path, {"run_id": "a", "v": 1})
    upsert(path, {"run_id": "b", "v": 2})
    upsert(path, {"run_id": "a", "v": 3})
    rows = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines()]
    assert rows == [{"run_id": "b", "v": 2}, {"run_id": "a", "v": 3}]
