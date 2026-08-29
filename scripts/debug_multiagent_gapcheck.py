#!/usr/bin/env python3
"""`HWP_RAG_ANSWER_STRATEGY=multi_agent` 경로 계측 하네스.

multi-agent 브랜치 디버깅 중 매번 python -c로 임시 스크립트를 만들어 검증하면
이전에 뭘 확인했는지 흔적이 안 남고 검증이 재현 가능하지 않았다(제목 반복 청크
버그 재현 때 쓴 `repro_title_repetition_bug.py`와 같은 이유). 이 스크립트는
질문을 하나 돌릴 때마다 gap-check 로그(step별 covered 여부·매칭 청크 수)·검색
호출(org_name/top_k/결과 수)·최종 생성 프롬프트에 들어간 전체 컨텍스트·최종
답변을 전부 `eval_resources/debug_logs/multiagent_runs/`에 JSON으로 저장한다.

사용법:
    conda activate langc
    HWP_RAG_LLM_BASE_URL=http://localhost:11434/v1 OPENAI_API_KEY=ollama-local \
    REASONING_MODEL=gpt-oss:20b QUERY_INTENT_MODEL=gpt-oss:20b OPENAI_TIMEOUT_SEC=1200 \
    python scripts/debug_multiagent_gapcheck.py --label m19 \
        --question "장성경찰서 장애인승강기 설치공사(건축)와 (통신) 중 기초금액이 더 큰 공사는 무엇인가요?"

여러 문항을 반복 실행할 때는 run_case()를 임포트해서 쓴다 — 문항 사이에
_reset_chatbot_context()로 대화 이력을 비워야 이전 문항의 무관한 Q/A가 다음
문항의 "# 이전 대화" 컨텍스트로 새어 들어가지 않는다(실측: 재현·수정됨).
"""
from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

os.environ.setdefault("HWP_RAG_LLM_BASE_URL", "http://localhost:11434/v1")
os.environ.setdefault("OPENAI_API_KEY", "ollama-local")
os.environ.setdefault("REASONING_MODEL", "gpt-oss:20b")
os.environ.setdefault("QUERY_INTENT_MODEL", "gpt-oss:20b")
os.environ.setdefault("OPENAI_TIMEOUT_SEC", "1200")
os.environ["HWP_RAG_ANSWER_STRATEGY"] = "multi_agent"

import sys  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.graph.workflow import RAGChatbotV17  # noqa: E402

LOG_DIR = PROJECT_ROOT / "eval_resources" / "debug_logs" / "multiagent_runs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

_chatbot: RAGChatbotV17 | None = None


def get_chatbot() -> RAGChatbotV17:
    global _chatbot
    if _chatbot is None:
        _chatbot = RAGChatbotV17()
    else:
        _reset_chatbot_context(_chatbot)
    return _chatbot


def _reset_chatbot_context(chatbot: RAGChatbotV17) -> None:
    """평가 문항 간 대화 컨텍스트 누적을 방지한다(scripts/eval_retrieval.py와 동일 패턴)."""
    conv = getattr(chatbot, "conversation", None)
    if conv is None:
        return
    if hasattr(conv, "history"):
        conv.history = []
    if hasattr(conv, "last_org"):
        conv.last_org = None
    if hasattr(conv, "last_query_type"):
        conv.last_query_type = None


def run_case(label: str, question: str, run_tag: str = "") -> dict:
    """질문 하나를 multi_agent 경로로 실행하고, gap-check/검색 호출/컨텍스트/답변을
    전부 기록해 JSON 파일로 저장한 뒤 그 dict를 반환한다."""
    chatbot = get_chatbot()

    orig_find_matches = chatbot._find_step_matches
    orig_build_ctx = chatbot._build_step_structured_context
    orig_retrieve_results = chatbot._retrieve_results

    record: dict = {
        "label": label, "question": question,
        "gap_checks": [], "retrieve_calls": [], "context": None, "step_evidence": None,
    }

    def spy_find_matches(step, accumulated):
        matches = orig_find_matches(step, accumulated)
        record["gap_checks"].append({"step": step, "covered": bool(matches), "n_matches": len(matches)})
        return matches

    def spy_build_ctx(query, step_evidence, accumulated):
        out = orig_build_ctx(query, step_evidence, accumulated)
        record["context"] = out
        record["step_evidence"] = [
            {"step": s, "extracted_value": v, "block_chars": len(b)} for s, v, b in step_evidence
        ]
        return out

    def spy_retrieve(q, org_name, top_k, prefer_original=False, doc_types=None, target_orgs=None, perf_stats=None):
        result = orig_retrieve_results(
            q, org_name, top_k,
            prefer_original=prefer_original, doc_types=doc_types,
            target_orgs=target_orgs, perf_stats=perf_stats,
        )
        record["retrieve_calls"].append({"org_name": org_name, "top_k": top_k, "n_results": len(result)})
        return result

    chatbot._find_step_matches = spy_find_matches
    chatbot._build_step_structured_context = spy_build_ctx
    chatbot._retrieve_results = spy_retrieve

    started = time.perf_counter()
    try:
        result = chatbot.answer(question, top_k=5)
        record["answer"] = result.get("answer")
        record["answer_mode"] = result.get("answer_mode")
        retrieved_docs = result.get("retrieved_docs", []) or []
        record["final_chunk_ids"] = [d.get("chunk_id") for d in retrieved_docs if isinstance(d, dict)]
    finally:
        chatbot._find_step_matches = orig_find_matches
        chatbot._build_step_structured_context = orig_build_ctx
        chatbot._retrieve_results = orig_retrieve_results
        record["elapsed_sec"] = round(time.perf_counter() - started, 1)

    out_path = LOG_DIR / f"{label}{('_' + run_tag) if run_tag else ''}_{int(time.time())}.json"
    out_path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    record["_saved_to"] = str(out_path)
    return record


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", required=True)
    parser.add_argument("--question", required=True)
    parser.add_argument("--tag", default="")
    args = parser.parse_args()

    rec = run_case(args.label, args.question, args.tag)
    print(f"saved: {rec['_saved_to']}")
    print("answer:", rec["answer"])
    print("gap_checks:", rec["gap_checks"])
    print("retrieve_calls:", rec["retrieve_calls"])


if __name__ == "__main__":
    main()
