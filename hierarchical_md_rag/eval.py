"""Recall@K / MRR / Hit Position을 계산한다. "정답"은 정답 chunk_id가 아니라 **부분 문자열
포함 여부**로 판정한다 — 청킹 전략이 바뀌면 청크 경계 자체가 달라져서 "정답 청크 ID"라는 개념이
두 전략 사이에서 성립하지 않기 때문이다(계층 기반은 섹션 단위로, 평문은 고정 크기로 잘리므로 같은
정답 문장이 서로 다른 청크에 들어간다). 대신 "정답이 될 만한 문장/키워드가 상위 K개 안의 어느
청크에든 있는가"로 판정하면 두 전략을 공정하게 비교할 수 있다.

`query_type`으로 결과를 나눠서 본다 — 질의 하나를 여러 개 섞어서 평균만 보면, 어떤 유형에서 왜
차이가 나는지 진단이 안 된다. 세 가지 유형을 구분한다(질의셋 작성 시 이 셋을 고루 섞을 것을 권장):

- `fact_lookup`: 문서 안의 구체적인 값 하나(날짜/금액/수량 등)를 정확히 찾는 질의. 검색 정밀도를
  가장 직접적으로 테스트한다.
- `single_doc`: 한 문서 안의 여러 문장을 종합해야 답이 되는 질의. 가장 흔한 케이스.
- `multi_doc`: 여러 문서에 걸친 내용을 종합해야 하는 질의(예: "어느 문서의 예산이 가장 큰가"). 이
  도구는 폴더 안 모든 문서의 청크를 한 인덱스에 모아 검색하므로 이런 질의도 그대로 평가할 수 있다."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from .chunk import Chunk
from .retrieve import embed_query, embed_texts, search

QUERY_TYPES = ("fact_lookup", "single_doc", "multi_doc")


@dataclass
class QueryResult:
    query: str
    query_type: str
    hit: bool
    rank: int | None  # 1-indexed, 못 찾으면 None
    top_chunks: list[str]  # 상위 결과의 section_path (디버깅용)


@dataclass
class Metrics:
    count: int
    recall_at_k: float
    mrr: float
    avg_hit_position: float | None  # 맞춘 것들만의 평균 순위 (낮을수록 좋음). hit 0개면 None


def _contains_expected(text: str, expected_contains: list[str]) -> bool:
    return any(e in text for e in expected_contains)


def _summarize(results: list[QueryResult]) -> Metrics:
    if not results:
        return Metrics(count=0, recall_at_k=0.0, mrr=0.0, avg_hit_position=None)
    hits = [r for r in results if r.hit]
    recall_at_k = len(hits) / len(results)
    mrr = sum(1.0 / r.rank for r in hits) / len(results)
    avg_hit_position = (sum(r.rank for r in hits) / len(hits)) if hits else None
    return Metrics(count=len(results), recall_at_k=recall_at_k, mrr=mrr, avg_hit_position=avg_hit_position)


def evaluate_one(
    chunks: list[Chunk],
    chunk_vecs,
    query: str,
    query_type: str,
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
    return QueryResult(query=query, query_type=query_type, hit=rank is not None, rank=rank, top_chunks=top_chunks)


def evaluate(
    chunks: list[Chunk],
    queries: list[dict],
    model_name: str,
    top_k: int,
) -> dict:
    """`queries`: [{"query": str, "query_type": str, "expected_contains": [str, ...]}, ...]
    반환: {"overall": Metrics, "by_type": {query_type: Metrics}, "results": [QueryResult, ...]}"""
    if not chunks or not queries:
        return {"overall": _summarize([]), "by_type": {}, "results": []}

    chunk_vecs = embed_texts([c.text for c in chunks], model_name)
    results = [
        evaluate_one(
            chunks, chunk_vecs, q["query"], q.get("query_type", "unspecified"),
            q["expected_contains"], model_name, top_k,
        )
        for q in queries
    ]

    grouped: dict[str, list[QueryResult]] = defaultdict(list)
    for r in results:
        grouped[r.query_type].append(r)

    return {
        "overall": _summarize(results),
        "by_type": {qtype: _summarize(rs) for qtype, rs in grouped.items()},
        "results": results,
    }
