"""Langfuse에 질문 한 건과 LLM 호출의 시간, 토큰 수를 남긴다.

질문, 근거, 답변 원문은 보내지 않는다. `.env`에 `LANGFUSE_PUBLIC_KEY`와 `LANGFUSE_SECRET_KEY`가
없거나 `LANGFUSE_TRACING_ENABLED=false`이면 아무것도 하지 않는다. 기록에 실패해도 답변은 계속한다.

실행을 구분하려면 환경변수를 쓴다.
    HWP_RAG_TRACE_SESSION  Langfuse 세션 ID(실험 실행 이름 등)
    HWP_RAG_TRACE_LABEL    질문 식별자(`new20:n16` 등). 질문 문장을 넣지 않는다.
"""

from __future__ import annotations

import contextlib
import contextvars
import functools
import os
from typing import Any, Iterator

# 이 키만 가진 metadata는 통과시키고, 그 밖의 input, output, metadata는 가린다.
_ALLOWED_METADATA = frozenset({
    "label", "latencies", "llm_calls", "input_tokens", "output_tokens", "max_input_tokens",
    "reasoning_tokens", "prompt_chars", "finish_reason",
})

_client: Any = None
_totals: contextvars.ContextVar[dict[str, int] | None] = contextvars.ContextVar("langfuse_totals", default=None)


def _mask(*, data: Any, **_: Any) -> Any:
    if data is None or (isinstance(data, dict) and data.keys() <= _ALLOWED_METADATA):
        return data
    return "[excluded]"


def _get_client() -> Any:
    global _client
    if os.environ.get("LANGFUSE_TRACING_ENABLED", "").lower() == "false":
        return None
    if not (os.environ.get("LANGFUSE_PUBLIC_KEY") and os.environ.get("LANGFUSE_SECRET_KEY")):
        return None
    if _client is None:
        try:
            from langfuse import Langfuse

            _client = Langfuse(mask=_mask)  # 키와 LANGFUSE_BASE_URL은 SDK가 환경변수에서 읽는다
        except Exception as e:  # noqa: BLE001
            print(f"[langfuse] 기록을 켜지 못함: {type(e).__name__}")
    return _client


@contextlib.contextmanager
def _observe(client: Any, **kwargs: Any) -> Iterator[Any]:
    try:
        cm = client.start_as_current_observation(**kwargs)
        observation = cm.__enter__()
    except Exception:  # noqa: BLE001
        yield None
        return
    try:
        yield observation
    finally:
        # 예외를 __exit__에 넘기면 OTel이 예외 메시지(원문이 섞일 수 있음)를 span에 남긴다.
        with contextlib.suppress(Exception):
            cm.__exit__(None, None, None)


def _mark_error(observation: Any, error: BaseException) -> None:
    with contextlib.suppress(Exception):
        observation.update(level="ERROR", status_message=type(error).__name__)


def _record_generation(observation: Any, messages: Any, result: Any) -> None:
    with contextlib.suppress(Exception):
        generation = result.generations[0]
        message = generation.message
        usage = getattr(message, "usage_metadata", None) or {}
        response_meta = getattr(message, "response_metadata", None) or {}
        info = getattr(generation, "generation_info", None) or {}
        metadata: dict[str, Any] = {
            "prompt_chars": sum(len(str(getattr(m, "content", m))) for m in messages),
            "finish_reason": info.get("finish_reason") or response_meta.get("finish_reason"),
        }
        reasoning = (usage.get("output_token_details") or {}).get("reasoning")
        if reasoning is not None:
            metadata["reasoning_tokens"] = reasoning
        update: dict[str, Any] = {"metadata": metadata}
        if usage:
            update["usage_details"] = {"input": usage.get("input_tokens", 0), "output": usage.get("output_tokens", 0)}
        totals = _totals.get()
        if totals is not None:
            totals["llm_calls"] += 1
            totals["input_tokens"] += usage.get("input_tokens", 0)
            totals["output_tokens"] += usage.get("output_tokens", 0)
            totals["max_input_tokens"] = max(totals["max_input_tokens"], usage.get("input_tokens", 0))
        if observation is not None:
            observation.update(**update)


def _session() -> Any:
    session = os.environ.get("HWP_RAG_TRACE_SESSION")
    if not session:
        return contextlib.nullcontext()
    from langfuse import propagate_attributes

    return propagate_attributes(session_id=session)


def _wrap_generate(original: Any) -> Any:
    @functools.wraps(original)
    def generate(self: Any, messages: Any, *args: Any, **kwargs: Any) -> Any:
        client = _get_client()
        if client is None:
            return original(self, messages, *args, **kwargs)
        model = getattr(self, "model_name", None)
        with _observe(client, name="llm", as_type="generation", model=model) as observation:
            try:
                result = original(self, messages, *args, **kwargs)
            except Exception as e:
                _mark_error(observation, e)
                raise
            _record_generation(observation, messages, result)
            return result

    return generate


def _wrap_answer(original: Any) -> Any:
    @functools.wraps(original)
    def answer(self: Any, *args: Any, **kwargs: Any) -> Any:
        client = _get_client()
        if client is None:
            return original(self, *args, **kwargs)
        totals = {"llm_calls": 0, "input_tokens": 0, "output_tokens": 0, "max_input_tokens": 0}
        token = _totals.set(totals)
        try:
            with _session(), _observe(client, name="rag-question", as_type="span") as span:
                try:
                    result = original(self, *args, **kwargs)
                except Exception as e:
                    _mark_error(span, e)
                    raise
                with contextlib.suppress(Exception):
                    metadata: dict[str, Any] = dict(totals)
                    metadata["latencies"] = result.get("latencies", {})
                    if label := os.environ.get("HWP_RAG_TRACE_LABEL"):
                        metadata["label"] = label
                    span.update(metadata=metadata)
                return result
        finally:
            _totals.reset(token)

    return answer


def instrument(chat_cls: type, bot_cls: type) -> None:
    """`chat_cls._generate`(모든 LLM 호출이 지나는 곳)와 `bot_cls.answer`를 감싼다. 두 번 불러도 한 번만 감싼다."""
    for cls, name, wrap in ((chat_cls, "_generate", _wrap_generate), (bot_cls, "answer", _wrap_answer)):
        marker = f"_langfuse_wrapped_{name}"
        if marker in cls.__dict__:
            continue
        setattr(cls, name, wrap(getattr(cls, name)))
        setattr(cls, marker, True)
