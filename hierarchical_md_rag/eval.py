"""Recall@K / MRR을 계산한다. "정답"은 정답 chunk_id가 아니라 **부분 문자열 포함 여부**로
판정한다 — 청킹 전략이 바뀌면 청크 경계 자체가 달라져서 "정답 청크 ID"라는 개념이 두 전략 사이에서
성립하지 않기 때문이다(계층 기반은 섹션 단위로, 평문은 고정 크기로 잘리므로 같은 정답 문장이 서로
다른 청크에 들어간다). 대신 "정답이 될 만한 문장/키워드가 상위 K개 안의 어느 청크에든 있는가"로
판정하면 두 전략을 공정하게 비교할 수 있다."""

from __future__ import annotations

from dataclasses import dataclass

from .chunk import Chunk
from .retrieve import embed_query, embed_texts, search


@dataclass
class QueryResult:
    query: str
    hit: bool
    rank: int | None  # 1-indexed, 못 찾으면 None
    top_chunks: list[str]  # 상위 결과의 section_path (디버깅용)


def _contains_expected(text: str, expected_contains: list[str]) -> bool:
    return any(e in text for e in expected_contains)


def evaluate_one(
    chunks: list[Chunk],
    chunk_vecs,
    query: str,
    expected_contains: list[str],
    model_name: str,
    top_k: int,
) -> QueryResult:
    qvec = embed_query(query, model_name)
    ranked = search(qvec, chunk_vecs, top_k)
    rank = None
    for i, (chunk_idx, _score) in enumerate(ranked, start=1):
        if _contains_expected(chunks[chunk_idx].text, expected_contains):
            rank = i
            break
    top_chunks = [chunks[idx].section_path or f"chunk#{idx}" for idx, _ in ranked]
    return QueryResult(query=query, hit=rank is not None, rank=rank, top_chunks=top_chunks)


def evaluate(
    chunks: list[Chunk],
    queries: list[dict],
    model_name: str,
    top_k: int,
) -> dict:
    """`queries`: [{"query": str, "expected_contains": [str, ...]}, ...]
    반환: {"recall_at_k": float, "mrr": float, "results": [QueryResult, ...]}"""
    if not chunks:
        return {"recall_at_k": 0.0, "mrr": 0.0, "results": []}

    chunk_vecs = embed_texts([c.text for c in chunks], model_name)
    results = [
        evaluate_one(chunks, chunk_vecs, q["query"], q["expected_contains"], model_name, top_k)
        for q in queries
    ]
    hits = [r for r in results if r.hit]
    recall_at_k = len(hits) / len(results) if results else 0.0
    mrr = sum(1.0 / r.rank for r in hits) / len(results) if results else 0.0
    return {"recall_at_k": recall_at_k, "mrr": mrr, "results": results}
