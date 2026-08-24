#!/usr/bin/env python3
"""제목 반복 청크 리랭킹 버그 재현/회귀 테스트 하네스.

docs/NEXT_SESSION_HANDOFF.md에서 다루는 버그(질문이 사업명을 그대로 반복하면
서두 소개 청크가 실제 정답 청크를 리랭킹에서 압도)의 재현 사례와, 관련 수정
과정에서 함께 검증한 회귀 방지 사례를 한 번에 돌려서 기록으로 남긴다.

매번 새로 python -c로 임시 검색을 돌리면 이전에 뭘 확인했는지 흔적이 안 남고
검증이 재현 가능하지 않으므로, 이 스크립트가 실행마다 사용한 쿼리/받은 결과를
전부 JSON으로 저장한다.

사용법:
    conda activate langc
    HWP_RAG_LLM_BASE_URL=http://localhost:11434/v1 OPENAI_API_KEY=ollama-local \
    REASONING_MODEL=gpt-oss:20b QUERY_INTENT_MODEL=gpt-oss:20b OPENAI_TIMEOUT_SEC=1200 \
    python scripts/repro_title_repetition_bug.py [--out eval_resources/debug_logs/xxx.json]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.graph.workflow import RAGChatbotV17  # noqa: E402
from src.retrievers.vectorstore import VectorStore  # noqa: E402

CASES = [
    {
        "id": "m1",
        "question": "SRT 감속기 모터피니언기어 구매 입찰의 낙찰자 결정 기준은 무엇인가요?",
        "targets": ["4148b8ca50e7b083_8"],
        "retrieval_top_k": 22,
    },
    {
        "id": "m3",
        "question": "한국마사회제주경마장 스마트워크 무선망 환경조성 도입 통신공사의 추정금액은 얼마인가요?",
        "targets": ["8d112e98e864a788_2"],
        "retrieval_top_k": 22,
    },
    {
        "id": "m9",
        "question": "소상공인 상세페이지 제작지원을 위한 생성형 AI 콘텐츠 제작 서비스 공급 및 운영 용역의 전자입찰서 접수 마감일시는 언제인가요?",
        "targets": ["beaba6445d09a569_2"],
        "retrieval_top_k": 22,
    },
    {
        "id": "m11",
        "question": "전주사랑의집 남자생활실 타일공사의 기초금액은 얼마인가요?",
        "targets": ["c1ee714a792489a3_2"],
        "retrieval_top_k": 22,
    },
    {
        "id": "m14",
        "question": "G램프사업단 연구시설장비 구입(컴퓨터외 1종) 사업의 기초금액은 얼마인가요?",
        "targets": ["0dd703316cf145af_1"],
        "retrieval_top_k": 22,
    },
    {
        "id": "m15",
        "question": "㈜헤르스 가스감지기(내압방폭형) 44SET 및 엣지컴퓨팅장비(THOR) 구매설치의 기초금액은 얼마인가요?",
        "targets": ["b4adac0d5097e089_1"],
        "retrieval_top_k": 22,
    },
    {
        "id": "m18",
        "question": "G램프 3차년도 연구시설장비 구입(GPU그래픽카드) 사업의 기초금액은 얼마인가요?",
        "targets": ["81a3686192ce1679_1"],
        "retrieval_top_k": 22,
    },
    {
        "id": "m19",
        "question": "장성경찰서 장애인승강기 설치공사(건축)와 (통신) 중 기초금액이 더 큰 공사는 무엇인가요?",
        "targets": ["55e0137bca42b879_5", "48a806ec55c477a9_4"],
        "retrieval_top_k": 30,
    },
    {
        "id": "m20",
        "question": (
            "2026년 한서대학교 산업디자인 개발 프로젝트 설계 컨설팅 및 목업 개발 용역과 "
            "2026 글로벌소상공인육성사업 자카르타국제프리미엄소비재전 용역 중 사업예산이 더 큰 사업은 무엇인가요?"
        ),
        "targets": ["d2d30dea14bb3078_1", "44d53fa91300a2f6_2"],
        "retrieval_top_k": 30,
    },
]


def run_case(bot: RAGChatbotV17, vs: VectorStore, case: dict) -> dict:
    query = case["question"]
    targets = case["targets"]
    top_k = case["retrieval_top_k"]

    expanded_queries = bot._expand_query_terms(query)
    strategy = bot._build_retrieval_strategy(query, org_name=None, top_k=top_k, doc_types=None, target_orgs=None)
    resolved_targets = list(strategy.get("resolved_targets") or [])

    # 리랭킹 직전(merged) 후보 풀을 가로채서 "후보군에 아예 없었는지" vs
    # "후보군엔 있었는데 점수에서 밀렸는지"를 구분한다.
    captured: dict = {}
    orig_rerank = bot._rerank_results

    def _patched(q, results, org_name, prefer_original):
        captured["merged_ids"] = [
            (r.get("chunk_id") or (r.get("metadata") or {}).get("chunk_id")) for r in results
        ]
        return orig_rerank(q, results, org_name, prefer_original)

    bot._rerank_results = _patched
    try:
        final_results = bot._retrieve_results(query, org_name=None, top_k=top_k, prefer_original=True)
    finally:
        bot._rerank_results = orig_rerank

    final_ids = [(r.get("chunk_id") or (r.get("metadata") or {}).get("chunk_id")) for r in final_results]
    merged_ids = captured.get("merged_ids", [])

    # 원시 dense 순위(전체 코퍼스 기준)도 같이 남겨서, 나중에 후보군 크기를
    # 다시 조정할 때 "어느 순위까지 커버해야 하는지" 바로 알 수 있게 한다.
    raw_dense_rank: dict[str, int | None] = {}
    for t in targets:
        raw_dense_rank[t] = None
    try:
        raw_rows = vs._query_candidates(query, n_results=vs.count)
        rank_map = {r["chunk_id"]: i for i, r in enumerate(raw_rows)}
        for t in targets:
            raw_dense_rank[t] = rank_map.get(t)
    except Exception:
        pass

    target_status = {}
    for t in targets:
        target_status[t] = {
            "final_rank": (final_ids.index(t) + 1) if t in final_ids else None,
            "in_pre_rerank_pool": t in merged_ids,
            "raw_dense_rank_over_full_corpus": raw_dense_rank.get(t),
        }

    all_ok = all(v["final_rank"] is not None for v in target_status.values())

    return {
        "id": case["id"],
        "question": query,
        "retrieval_top_k": top_k,
        "expanded_queries_sent_to_db": expanded_queries,
        "comparison_like": bool(strategy.get("comparison_like")),
        "resolved_targets": resolved_targets,
        "status": "OK" if all_ok else "MISS",
        "targets": target_status,
        "final_top_results": [
            {"rank": i + 1, "chunk_id": cid}
            for i, cid in enumerate(final_ids[: max(10, len(targets) + 5)])
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--out",
        default="eval_resources/debug_logs/retrieval_bias_repro.json",
        help="결과 JSON 저장 경로",
    )
    args = parser.parse_args()

    bot = RAGChatbotV17()
    vs = bot.vector_store

    results = [run_case(bot, vs, case) for case in CASES]

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"결과 저장: {out_path}")
    for r in results:
        marker = "OK  " if r["status"] == "OK" else "MISS"
        ranks = {t: v["final_rank"] for t, v in r["targets"].items()}
        print(f"[{marker}] {r['id']}: {ranks}")


if __name__ == "__main__":
    main()
