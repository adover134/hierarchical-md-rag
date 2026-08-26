"""검색 API — `RAGChatbotV17.answer()`를 HTTP로 노출한다.

이 저장소에서 서비스 사용자용 UI가 실제로 붙는 지점은 여기뿐이다. DB 구축/upsert(원본
HWP/HWPX 파싱 + 청킹 + Chroma 적재)는 서비스 제공자가 CLI(`build_index_new_parser.py`)를
직접 쓰거나 자체 자동화로 돌리는 별개 작업이고, 여기서는 그렇게 이미 만들어진 DB에 대해
"검색"(LLM을 통한 질의응답)만 한다 — API에 문서 업로드/인덱싱 엔드포인트는 없다.

이 API가 곧 UI의 백엔드 역할이라(별도로 감싸는 계층이 없음), hwp-hierarchical-md-service의
`auth.py`와 같은 방식(`Authorization: Bearer <key>`, 키 목록 환경변수)으로 인증한다 —
rate limit은 범위 밖(그쪽은 Langfuse 트레이스를 근거로 셌는데, 이 저장소는 Langfuse를 아직
안 쓴다).

사용법:
    python scripts/api.py [--host 0.0.0.0] [--port 8001]
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel

ANONYMOUS = "anonymous"

app = FastAPI(
    title="hierarchical-md-rag search API",
    description="RAGChatbotV17.answer()를 감싸는 검색(질의응답) 전용 API — 문서 인덱싱은 CLI 몫",
    version="0.1.0",
)

_chatbot: Any = None


def _get_chatbot() -> Any:
    """RAGChatbotV17 인스턴스를 지연 생성해 프로세스 전체에서 재사용한다(임베딩 모델/DB
    커넥션 등 초기화 비용이 요청마다 드는 걸 피하기 위함 — Streamlit 쪽의
    `@st.cache_resource`와 같은 의도)."""
    global _chatbot
    if _chatbot is None:
        from src.graph.workflow import RAGChatbotV17

        _chatbot = RAGChatbotV17()
    return _chatbot


def _configured_keys() -> set[str] | None:
    raw = os.environ.get("RAG_API_KEYS", "").strip()
    if not raw:
        return None
    return {k.strip() for k in raw.split(",") if k.strip()}


def require_api_key(authorization: str | None = Header(default=None)) -> str:
    """`Authorization: Bearer <key>` 검증. `RAG_API_KEYS` 미설정이면 통과(`ANONYMOUS`) —
    로컬 개발/사내망처럼 인증이 필요 없는 배포를 막지 않기 위함(hwp-hierarchical-md-service의
    `auth.py`와 동일한 철학). 실제 서비스 배포에서는 반드시 설정할 것."""
    keys = _configured_keys()
    if keys is None:
        return ANONYMOUS

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "인증 필요: Authorization: Bearer <API_KEY> 헤더가 없습니다")
    key = authorization.removeprefix("Bearer ").strip()
    if key not in keys:
        raise HTTPException(401, "유효하지 않은 API 키")
    return key


class QueryRequest(BaseModel):
    query: str
    top_k: int = 24


@app.get("/v1/health")
def health() -> dict:
    """DB/챗봇 초기화가 유효한지 점검(인증 불필요)."""
    try:
        chatbot = _get_chatbot()
        chunk_count = getattr(chatbot.vector_store, "count", None)
        return {"ok": True, "chunk_count": chunk_count}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


@app.post("/v1/query")
def query(req: QueryRequest, api_key: str = Depends(require_api_key)) -> dict:
    """질의에 대해 RAG 답변을 생성한다 — `RAGChatbotV17.answer()`의 반환 dict를 그대로 전달."""
    if not req.query.strip():
        raise HTTPException(400, "query가 비어 있습니다")

    chatbot = _get_chatbot()
    t0 = time.perf_counter()
    try:
        result = chatbot.answer(req.query.strip(), top_k=req.top_k)
    except Exception as e:
        raise HTTPException(500, f"질의 처리 실패: {type(e).__name__}: {e}") from e
    result["_latency_sec"] = round(time.perf_counter() - t0, 2)
    return result


def main() -> None:
    import uvicorn

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8001)
    args = ap.parse_args()
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
