"""테스트 배포용 Gradio 챗 UI — `RAGChatbotV17.answer()`를 감싼다.

`scripts/api.py`(HTTP API)와 같은 백엔드를 쓰지만, 이건 API 서버가 아니라 랜덤 테스터가
바로 써볼 수 있는 채팅 화면이다. 답변마다 Gradio `ChatInterface`의 기본 제공 👍/👎
플래깅(`flagging_mode="manual"`)으로 피드백을 받는다 — 질문/답변/평가가
`eval_resources/gradio_flagged/`에 자동 저장된다. 정성 평가(전체 인상/사용 의향 등)는
별도 Google Form으로 받고, 여기서는 "이 답변 하나가 쓸만했는가"만 가볍게 기록한다.

**로깅 방침**: 플래깅 로그와 별개로 모든 질의/답변(평가 안 남긴 것, 오류로 끝난 것 포함)을
`eval_resources/gradio_query_log.jsonl`에 남긴다 — 실사용 패턴 파악에 필요하다는 판단
(둘 다 gitignore 대상, 로컬에만 남음). 반대로 질의 내용과 무관하게 외부로 나가는 텔레메트리
(HuggingFace Hub의 모델 사용 내역 전송 등)는 아래 `_ENFORCED_ENV`에서 명시적으로 차단한다.

**전략/모델 고정**: 이번 세션 전체가 `HWP_RAG_ANSWER_STRATEGY=multi_agent` +
`gpt-oss:20b`(로컬 Ollama) 조합으로 검증한 결과다 — 테스터가 다른 조합(예: two_stage,
다른 모델)을 실제로 겪으면 그 검증이 무의미해진다. 그래서 이 값들은 실행 환경변수로
덮어쓸 수 없게 스크립트 안에서 직접 고정한다(아래 `_ENFORCED_ENV`, `os.environ[k] = v`로
설정 — `setdefault`가 아님). 로컬 실험용으로 다른 조합을 쓰고 싶으면 이 딕셔너리를
직접 고쳐서 실행할 것.

**인증**: `GRADIO_APP_SHARED_PASSWORD` 환경변수를 설정하면 테스터 전원이 공유하는
계정(아이디 `tester`) 하나로 접속을 막는다 — 실제 도메인 배포 시 필수(안 하면 링크만
아는 아무나 접근해 GPU를 소모시킬 수 있음, 자세한 근거는 `main()`의 주석 참고). 로컬
단독 확인 시엔 없어도 되고, 없으면 시작 시 경고만 찍힌다.

사용법:
    conda activate langc
    GRADIO_APP_SHARED_PASSWORD=<공유 비밀번호> python scripts/gradio_app.py [--share] [--port 7860]

`--share`를 주면 Gradio가 공개 임시 링크를 만들어준다(테스터에게 바로 공유 가능,
별도 호스팅 불필요) — 링크는 72시간 후 만료된다.
"""
from __future__ import annotations

import argparse
import os
import queue
import sys
import threading
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
    # 운영 셸에 디버깅용으로 켜둔 값이 남아 있어도 배포 로그에 질의 텍스트가 찍히지
    # 않도록 명시적으로 꺼둔다(기본값도 false지만, 방어적으로 직접 고정 — 다른
    # 값들과 같은 이유: 배포 환경변수를 신뢰하지 않는다).
    "DEBUG_RETRIEVAL_TIMING": "false",
    # 임베딩 모델 로딩(sentence-transformers)이 HuggingFace Hub에 "어떤 모델/라이브러리
    # 버전을 쓰는지"를 익명 텔레메트리로 전송하는 걸 차단한다 — 질의 내용과는 무관하게
    # 외부로 나가는 모델 사용 내역이라 별도로 막아야 한다(공식 huggingface_hub 지원
    # 환경변수, 이 저장소의 requirements에 있는 버전에서 직접 확인함).
    "HF_HUB_DISABLE_TELEMETRY": "1",
}
for _k, _v in _ENFORCED_ENV.items():
    os.environ[_k] = _v

import gradio as gr

FLAGGING_DIR = str(Path(__file__).resolve().parent.parent / "eval_resources" / "gradio_flagged")
# 👍/👎를 남긴 것만 기록하는 FLAGGING_DIR과 별개로, 피드백 분석에는 전체 질의
# 흐름(평가를 안 남긴 질문 포함, 오류로 끝난 질문 포함)이 더 도움이 된다는
# 판단에 따라 모든 요청을 별도로 JSONL 하나에 계속 남긴다.
QUERY_LOG_PATH = Path(__file__).resolve().parent.parent / "eval_resources" / "gradio_query_log.jsonl"

INTRO_MARKDOWN = """\
# 입찰메이트 — RFP 문서 질의응답 (테스트 배포)

공공 입찰(RFP) 공고문에 대해 질문하면 문서를 검색해 답합니다. 예:
- "OO사업의 기초금액은 얼마인가요?"
- "OO 공고의 입찰 마감일은 언제인가요?"
- "A 사업과 B 사업 중 예산이 더 큰 곳은 어디인가요?"

⚠️ 이 챗봇은 **테스트 배포**입니다 — 실제 입찰 의사결정에 이 답변만으로 의존하지 마시고, 반드시 원문 공고문을 함께 확인해 주세요.\n
답변 옆의 👍/👎로 평가를 남겨주시면 개선에 큰 도움이 됩니다.

추가 예상 질문은 [테스트 시나리오](https://github.com/adover134/hierarchical-md-rag/blob/multi-agent/TEST_SCENARIOS.md)를 참조하세요.\n
테스트 후에는 [설문 양식](https://docs.google.com/forms/d/e/1FAIpQLSeh_riFvFTR2JHFZN6h_0SalJ-37RTYqPQiuZ80QVXJmspfGQ/viewform?usp=header) 작성도 부탁드립니다.
"""

# 동시에 처리할 요청 수 — Ollama가 병렬로 생성을 처리하려면 서버 쪽에도
# OLLAMA_NUM_PARALLEL을 이 값 이상으로 맞춰야 실제 병렬 처리가 된다(TEST_SCENARIOS.md
# 배포 가이드 참고). L4(24GB) 기준 모델(~14GB)을 빼면 ~10GB가 남는데, 병렬 슬롯마다
# KV 캐시가 늘어나므로 기본 2로 잡는다 — 늘리려면 VRAM 여유를 먼저 확인할 것.
POOL_SIZE = int(os.environ.get("GRADIO_APP_POOL_SIZE", "2"))

_chatbot_pool: "queue.Queue[Any]" = queue.Queue()
_pool_lock = threading.Lock()
_pool_ready = False


def _ensure_pool() -> None:
    """`RAGChatbotV17` 인스턴스를 `POOL_SIZE`개 미리 만들어 큐에 채운다.

    처음엔 인스턴스 하나를 전역에서 공유했는데(`chatbot.conversation`을 요청마다
    바꿔치기하는 방식), 그건 큐 동시성이 1(직렬 처리)일 때만 안전했다 — 병렬로
    처리하려면(동시성 > 1) 요청 A가 자기 세션 컨텍스트를 심자마자 요청 B가 같은
    인스턴스에 자기 컨텍스트를 덮어써버리는 race condition이 생긴다. 인스턴스를
    아예 여러 개 만들어 요청마다 하나씩 '독점 대여'하는 방식(Queue.get/put)으로
    바꾸면, 동시에 처리 중인 요청끼리는 서로 다른 인스턴스를 쓰게 되어 문제가
    구조적으로 사라진다."""
    global _pool_ready
    if _pool_ready:
        return
    with _pool_lock:
        if _pool_ready:
            return
        from src.graph.workflow import RAGChatbotV17

        for _ in range(POOL_SIZE):
            _chatbot_pool.put(RAGChatbotV17())
        _pool_ready = True


def _session_conversation(history: list[dict[str, str]]) -> Any:
    """Gradio가 이미 세션별로 격리해주는 `history`로부터, 이번 요청 전용
    `ConversationContext`를 매번 새로 만든다.

    풀에서 대여한 인스턴스라도 그 `self.conversation`(대화 이력/`last_org`)을 그대로
    쓰면, 같은 인스턴스를 나중에 대여한 '다른' 테스터에게 이전 대화 맥락이 남아있게
    된다 — 실측: A가 "SRT 감속기..." 질문 후 last_org가 SRT로 남은 상태에서, 전혀
    무관한 B가 "그거 언제까지야?"처럼 후속질문형 어휘("그거")를 쓰면
    `get_follow_up_context()`가 B의 질문을 A의 SRT 맥락에 대한 후속질문으로 오판한다.
    Gradio의 `history`는 세션(브라우저)마다 이미 올바르게 격리돼 있으므로, 매 요청마다
    그 history로 새 컨텍스트를 만들어 대여한 인스턴스에 주입하면 별도 세션 상태 없이
    격리된다."""
    from src.graph.state import ConversationContext

    conv = ConversationContext(max_history=5)
    pending_query: str | None = None
    for turn in history:
        role, content = turn.get("role"), str(turn.get("content", ""))
        if role == "user":
            pending_query = content
        elif role == "assistant" and pending_query is not None:
            conv.add_exchange(pending_query, content)
            pending_query = None
    return conv


def _log_query(message: str, answer: str, elapsed: float, error: str | None = None) -> None:
    """모든 질의/답변을 JSONL로 남긴다 — 플래깅(👍/👎) 안 한 질문, 오류로 끝난
    질문까지 전부 포함해야 실제 사용 패턴을 알 수 있다는 판단. 로깅 실패가
    답변 자체를 막으면 안 되므로 예외는 조용히 삼킨다."""
    import datetime
    import json

    record = {
        "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "query": message,
        "answer": answer,
        "elapsed_sec": round(elapsed, 1),
        "error": error,
    }
    try:
        QUERY_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(QUERY_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        pass


def respond(message: str, history: list[dict[str, str]]) -> str:
    import time

    message = (message or "").strip()
    if not message:
        return "질문을 입력해 주세요."

    _ensure_pool()
    # 풀에서 인스턴스를 하나 독점 대여한다 — POOL_SIZE개가 전부 대여 중이면 여기서
    # 블로킹돼 자연스럽게 백프레셔가 걸린다(Gradio 큐의 concurrency_limit과 이중으로
    # 안전장치 역할). 반드시 finally에서 반납해야 다음 요청이 쓸 수 있다.
    chatbot = _chatbot_pool.get()
    try:
        # 대여한 인스턴스에 이번 세션 전용 대화 맥락을 주입 — 이 인스턴스를 이전에
        # 대여했던 '다른' 테스터의 맥락이 남아있으면 안 되므로 매번 새로 만든다.
        chatbot.conversation = _session_conversation(history)
        started = time.perf_counter()
        try:
            result = chatbot.answer(message, top_k=24)
        except Exception as e:  # noqa: BLE001 — 테스트 배포라 예외를 그대로 노출하지 않고 안내문으로 감싼다
            error_reply = f"죄송합니다, 답변 생성 중 오류가 발생했습니다({type(e).__name__}). 다른 방식으로 질문해 주시겠어요?"
            _log_query(message, error_reply, time.perf_counter() - started, error=f"{type(e).__name__}: {e}")
            return error_reply
        answer = str(result.get("answer") or "답변을 찾지 못했습니다.")
        _log_query(message, answer, time.perf_counter() - started)
        return answer
    finally:
        _chatbot_pool.put(chatbot)


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

    # 인증: 실제 도메인으로 배포하면(TEST_SCENARIOS.md 배포 가이드) 이 URL은
    # HTTPS로 인터넷에 열려 있다 — auth 없이 그냥 launch()하면 링크만 아는
    # 아무나(우연히 공유되거나, 크롤러가 찾아내거나) 접속해 GPU를 소모시킬 수
    # 있다. GRADIO_APP_SHARED_PASSWORD를 설정하면 테스터 전원이 공유하는 계정
    # 하나로 간단히 막는다 — 개별 계정 관리까지는 이 규모에 과하다고 판단.
    # 로컬에서 --share 없이 혼자 확인할 때는 굳이 안 걸어도 되므로 기본은 없음
    # (없으면 경고만 찍고 그대로 진행 — 실수로 인증 없이 공개 배포하는 걸 완전히
    # 막진 않지만 최소한 눈에 띄게 알려준다).
    shared_password = os.environ.get("GRADIO_APP_SHARED_PASSWORD", "")
    auth: tuple[str, str] | None = ("tester", shared_password) if shared_password else None
    if not auth:
        print(
            "[gradio_app] 경고: GRADIO_APP_SHARED_PASSWORD가 설정되지 않아 인증 없이 "
            "열립니다 — 실제 도메인으로 배포하는 거라면 이 URL을 아는 누구나 접근할 수 "
            "있다는 뜻입니다. 로컬 단독 확인이 아니라면 설정을 권장합니다.",
            file=sys.stderr,
        )

    # 첫 테스터가 풀 초기화 비용(POOL_SIZE개 인스턴스 생성)을 그대로 떠안지 않도록
    # 서버를 열기 전에 미리 채워둔다.
    print(f"[gradio_app] 챗봇 인스턴스 {POOL_SIZE}개 준비 중...")
    _ensure_pool()
    print("[gradio_app] 준비 완료.")

    demo = build_app()
    # 다중 사용자: Gradio queue의 concurrency를 POOL_SIZE에 맞춘다 — 풀에 있는
    # 인스턴스 수만큼만 실제 병렬 처리가 가능하므로 그 이상 동시에 들여보내봐야
    # respond() 내부의 Queue.get()에서 그냥 대기하게 될 뿐이다. Ollama 쪽도
    # OLLAMA_NUM_PARALLEL을 POOL_SIZE 이상으로 맞춰야 실제로 병렬 생성이 된다
    # (TEST_SCENARIOS.md 배포 가이드 참고 — 안 맞추면 여기서만 병렬로 보내고
    # Ollama가 자체적으로 다시 직렬화해 체감 이득이 없다).
    #
    # 이 환경에서는 launch()를 기본(블로킹) 모드로 부르면 "Running on local URL" 배너도
    # 못 찍고 응답 없이 멈춘다(실측: 60초+ 무응답, GRADIO_ANALYTICS_ENABLED 여부와 무관).
    # prevent_thread_lock=True로 즉시 반환시킨 뒤 block_thread()로 직접 블로킹하면
    # 정상 동작한다.
    demo.queue(default_concurrency_limit=POOL_SIZE).launch(
        server_name=args.host,
        server_port=args.port,
        share=args.share,
        prevent_thread_lock=True,
        auth=auth,
        auth_message="입찰메이트 테스트 배포 — 공유받은 계정으로 로그인해 주세요.",
    )
    demo.block_thread()


if __name__ == "__main__":
    main()
