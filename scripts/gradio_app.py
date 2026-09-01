"""테스트 배포용 Gradio 챗 UI — `RAGChatbotV17.answer()`를 감싼다.

`scripts/api.py`(HTTP API)와 같은 백엔드를 쓰지만, 이건 API 서버가 아니라 랜덤 테스터가
바로 써볼 수 있는 채팅 화면이다. 답변마다 Gradio `ChatInterface`의 기본 제공 👍/👎
플래깅(`flagging_mode="manual"`)으로 피드백을 받는다 — 질문/답변/평가가
`eval_resources/gradio_flagged/`에 자동 저장된다. 정성 평가(전체 인상/사용 의향 등)는
별도 Google Form으로 받고, 여기서는 "이 답변 하나가 쓸만했는가"만 가볍게 기록한다.

**전략/모델 고정**: 이번 세션 전체가 `HWP_RAG_ANSWER_STRATEGY=multi_agent` +
`gpt-oss:20b`(로컬 Ollama) 조합으로 검증한 결과다 — 테스터가 다른 조합(예: two_stage,
다른 모델)을 실제로 겪으면 그 검증이 무의미해진다. 그래서 이 값들은 실행 환경변수로
덮어쓸 수 없게 스크립트 안에서 직접 고정한다(아래 `_ENFORCED_ENV`, `os.environ[k] = v`로
설정 — `setdefault`가 아님). 로컬 실험용으로 다른 조합을 쓰고 싶으면 이 딕셔너리를
직접 고쳐서 실행할 것.

사용법:
    conda activate langc
    python scripts/gradio_app.py [--share] [--port 7860]

`--share`를 주면 Gradio가 공개 임시 링크를 만들어준다(테스터에게 바로 공유 가능,
별도 호스팅 불필요) — 링크는 72시간 후 만료된다.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# 이번 세션 내내 검증한 정확한 조합 — 환경변수로 덮어쓸 수 없도록 직접 대입한다
# (setdefault가 아니다: 실행 셸에 이미 다른 값이 있어도 무조건 이걸로 강제한다).
# import 이전에 설정해야 확실히 반영된다(GRADIO_ANALYTICS_ENABLED은 gradio import
# 시점에 읽히고, 나머지는 RAGChatbotV17 지연 임포트 시점에 읽힌다 — 어느 쪽이든
# main()이 서버를 실제로 띄우기 전에 끝나므로 순서상 안전하다).
_ENFORCED_ENV = {
    "GRADIO_ANALYTICS_ENABLED": "False",  # launch() 텔레메트리 핑이 샌드박스에서 무응답으로 멈춤(아래 launch() 주석 참고)
    "HWP_RAG_ANSWER_STRATEGY": "multi_agent",
    "HWP_RAG_LLM_BASE_URL": "http://localhost:11434/v1",
    "OPENAI_API_KEY": "ollama-local",
    "REASONING_MODEL": "gpt-oss:20b",
    "QUERY_INTENT_MODEL": "gpt-oss:20b",
    "OPENAI_TIMEOUT_SEC": "1200",
}
for _k, _v in _ENFORCED_ENV.items():
    os.environ[_k] = _v

import gradio as gr

FLAGGING_DIR = str(Path(__file__).resolve().parent.parent / "eval_resources" / "gradio_flagged")

INTRO_MARKDOWN = """\
# 입찰메이트 — RFP 문서 질의응답 (테스트 배포)

공공 입찰(RFP) 공고문에 대해 질문하면 문서를 검색해 답합니다. 예:
- "OO사업의 기초금액은 얼마인가요?"
- "OO 공고의 입찰 마감일은 언제인가요?"
- "A 사업과 B 사업 중 예산이 더 큰 곳은 어디인가요?"

⚠️ 이 챗봇은 **테스트 배포**입니다 — 실제 입찰 의사결정에 이 답변만으로 의존하지 마시고,
반드시 원문 공고문을 함께 확인해 주세요. 답변 옆의 👍/👎로 평가를 남겨주시면
개선에 큰 도움이 됩니다.
"""

_chatbot: Any = None


def _get_chatbot() -> Any:
    """RAGChatbotV17 인스턴스를 지연 생성해 프로세스 전체에서 재사용한다
    (scripts/api.py의 `_get_chatbot()`과 동일한 패턴 — 임베딩 모델/DB 커넥션
    초기화 비용을 요청마다 물지 않기 위함)."""
    global _chatbot
    if _chatbot is None:
        from src.graph.workflow import RAGChatbotV17

        _chatbot = RAGChatbotV17()
    return _chatbot


def respond(message: str, history: list[dict[str, str]]) -> str:
    message = (message or "").strip()
    if not message:
        return "질문을 입력해 주세요."

    chatbot = _get_chatbot()
    try:
        result = chatbot.answer(message, top_k=24)
    except Exception as e:  # noqa: BLE001 — 테스트 배포라 예외를 그대로 노출하지 않고 안내문으로 감싼다
        return f"죄송합니다, 답변 생성 중 오류가 발생했습니다({type(e).__name__}). 다른 방식으로 질문해 주시겠어요?"
    return str(result.get("answer") or "답변을 찾지 못했습니다.")


def _check_ollama_ready() -> str | None:
    """`_ENFORCED_ENV`가 고정한 gpt-oss:20b/Ollama 조합이 실제로 떠 있는지 확인한다.
    안 띄우고 그냥 서버를 열면, 테스터가 첫 질문에서야 모호한 예외 메시지를 받게
    된다 — 그 대신 실행 시점에 바로 실패 사유를 알려준다. 문제없으면 None을
    돌려준다."""
    import urllib.error
    import urllib.request

    base_url = os.environ["HWP_RAG_LLM_BASE_URL"]
    tags_url = base_url.rsplit("/v1", 1)[0] + "/api/tags"
    try:
        with urllib.request.urlopen(tags_url, timeout=5) as resp:
            import json as _json

            names = [m.get("name", "") for m in _json.load(resp).get("models", [])]
    except (urllib.error.URLError, OSError) as e:
        return f"Ollama({base_url})에 연결할 수 없습니다({e}). `ollama serve`가 떠 있는지 확인하세요."

    target = os.environ["REASONING_MODEL"]
    if not any(n == target or n.startswith(target + ":") for n in names):
        return f"Ollama에 '{target}' 모델이 없습니다(설치된 모델: {names or '없음'}). `ollama pull {target}`로 받으세요."
    return None


def build_app() -> gr.ChatInterface:
    return gr.ChatInterface(
        fn=respond,
        title=None,
        description=INTRO_MARKDOWN,
        examples=[
            "SRT 감속기 모터피니언기어 구매 입찰의 낙찰자 결정 기준은 무엇인가요?",
            "2026년 대전광역시립요양원 식자재 구매의 납품기한은 언제까지인가요?",
        ],
        flagging_mode="manual",
        flagging_options=("Like", "Dislike"),
        flagging_dir=FLAGGING_DIR,
    )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=7860)
    ap.add_argument("--share", action="store_true", help="Gradio 공개 임시 링크 생성(72시간 만료)")
    args = ap.parse_args()

    error = _check_ollama_ready()
    if error:
        print(f"[gradio_app] 실행 중단: {error}", file=sys.stderr)
        raise SystemExit(1)

    demo = build_app()
    # 이 환경에서는 launch()를 기본(블로킹) 모드로 부르면 "Running on local URL" 배너도
    # 못 찍고 응답 없이 멈춘다(실측: 60초+ 무응답, GRADIO_ANALYTICS_ENABLED 여부와 무관).
    # prevent_thread_lock=True로 즉시 반환시킨 뒤 block_thread()로 직접 블로킹하면
    # 정상 동작한다.
    demo.queue().launch(
        server_name=args.host, server_port=args.port, share=args.share, prevent_thread_lock=True
    )
    demo.block_thread()


if __name__ == "__main__":
    main()
