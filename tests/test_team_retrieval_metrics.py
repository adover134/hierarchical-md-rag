"""팀 검색 지표를 저장된 실행 결과에 계산하는 부분(`scripts/run_experiment.py`)의 테스트."""

import sys
from pathlib import Path

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


def test_chunk_recall_is_none_without_labels():
    row = team_retrieval_metrics([_doc("가 공사_가 기관", "h_1")], {"sources": ["가 공사_가 기관"]}, 5)
    assert row["chunk_recall"] is None
