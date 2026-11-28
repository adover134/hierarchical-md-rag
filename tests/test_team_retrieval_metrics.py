"""팀 검색 지표를 저장된 실행 결과에 계산하는 부분(`scripts/run_experiment.py`)의 테스트."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

from run_experiment import team_retrieval_metrics  # noqa: E402

GT = {"sources": ["가 공사_가 기관"], "chunk_uids": ["h_1", "h_2"], "chunk_orders": []}


def _doc(source, chunk_id=None):
    return {"source": source, "chunk_id": chunk_id, "chunk_index": None, "score": 1.0}


def test_the_step2_audited_prefix_is_ignored_when_matching_the_document():
    row = team_retrieval_metrics([_doc("step2_audited_가 공사_가 기관.md")], GT, 5)
    assert row["source_recall"] == 1.0 and row["source_hit_position"] == 1


def test_chunk_recall_is_the_share_of_labelled_chunks_in_the_top_k():
    docs = [_doc("가 공사_가 기관", "h_1"), _doc("가 공사_가 기관", "x_9")]
    assert team_retrieval_metrics(docs, GT, 5)["chunk_recall"] == 0.5


def test_chunk_recall_is_null_for_an_answer_that_uses_no_chunks():
    row = team_retrieval_metrics([_doc("step2_audited_가 공사_가 기관.md")], GT, 5, uses_chunks=False)
    assert row["chunk_recall"] is None
    assert row["source_recall"] == 1.0 and row["source_hit_position"] == 1


def test_chunk_recall_is_zero_when_a_chunk_search_finds_nothing():
    assert team_retrieval_metrics([], GT, 5)["chunk_recall"] == 0.0


def test_chunk_recall_is_none_without_labels():
    row = team_retrieval_metrics([_doc("가 공사_가 기관", "h_1")], {"sources": ["가 공사_가 기관"]}, 5)
    assert row["chunk_recall"] is None


TWO = {"sources": ["가 공사_가 기관", "나 공사_나 기관"]}
A, B, X = "가 공사_가 기관", "나 공사_나 기관", "다 공사_다 기관"


def _ndcg(sources, gt=TWO):
    return team_retrieval_metrics([_doc(s) for s in sources], gt, 5)["source_ndcg"]


def test_ndcg_is_full_when_every_labelled_document_is_within_the_top_n_documents():
    assert _ndcg([A, B]) == 1.0 and _ndcg([B, A]) == 1.0


def test_ndcg_counts_the_chunks_of_one_document_once():
    assert _ndcg([A, A, B]) == 1.0


def test_ndcg_weights_the_ranks_within_the_top_n():
    assert _ndcg([A, X, B]) == pytest.approx(0.6131, abs=1e-4)
    assert _ndcg([X, A, B]) == pytest.approx(0.3869, abs=1e-4)
    assert _ndcg([A]) == pytest.approx(0.6131, abs=1e-4)


def test_ndcg_of_a_single_document_question_is_zero_below_the_first_rank():
    one = {"sources": [A]}
    assert _ndcg([A, X], one) == 1.0 and _ndcg([X, A], one) == 0.0


def test_ndcg_looks_only_at_the_top_k_results():
    one = {"sources": [A, B]}
    assert _ndcg([A, A, A, A, A, B], one) == pytest.approx(0.6131, abs=1e-4)


def test_ndcg_is_none_without_labelled_documents():
    assert _ndcg([A], {}) is None


def test_chunk_recall_does_not_accept_the_same_chunk_number_of_another_document():
    gt = {"sources": [A], "chunk_uids": ["aaa_9"], "chunk_orders": [9]}
    docs = [{"source": X, "chunk_id": "bbb_9", "chunk_index": "9", "score": 1.0}]
    assert team_retrieval_metrics(docs, gt, 5)["chunk_recall"] == 0.0


def test_chunk_recall_is_none_when_the_labels_have_only_chunk_numbers():
    gt = {"sources": [A], "chunk_orders": [9]}
    assert team_retrieval_metrics([_doc(A, "aaa_9")], gt, 5)["chunk_recall"] is None
