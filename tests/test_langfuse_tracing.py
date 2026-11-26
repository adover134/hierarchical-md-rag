"""Langfuse 계측: 시간과 토큰 수는 남기고 원문은 내보내지 않는다(네트워크 없이 메모리 exporter로 확인)."""

from types import SimpleNamespace
from uuid import uuid4

import pytest

from src.utils import langfuse_tracing as tracing

SECRETS = ("비밀질문", "비밀근거", "비밀답변", "비밀오류")


def _classes(fail: bool = False):
    class Chat:
        model_name = "gpt-oss:20b"

        def _generate(self, messages):
            if fail:
                raise RuntimeError("비밀오류")
            message = SimpleNamespace(
                usage_metadata={"input_tokens": 120, "output_tokens": 30},
                response_metadata={"finish_reason": "stop"},
                content="비밀답변",
            )
            return SimpleNamespace(generations=[SimpleNamespace(message=message, generation_info=None)])

    class Bot:
        def answer(self, query, top_k=24):
            Chat()._generate([SimpleNamespace(content="비밀근거")])
            return {"answer": "비밀답변", "latencies": {"retrieve": 0.5}}

    return Chat, Bot


@pytest.fixture
def exported(monkeypatch):
    from langfuse import Langfuse
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    exporter = InMemorySpanExporter()
    monkeypatch.setenv("LANGFUSE_TRACING_ENABLED", "true")
    public_key = f"pk-lf-{uuid4().hex}"  # SDK가 public key별로 전송기를 재사용하므로 테스트마다 다르게
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", public_key)
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-test")
    monkeypatch.setenv("HWP_RAG_TRACE_SESSION", "run1:multi_agent")
    monkeypatch.setenv("HWP_RAG_TRACE_LABEL", "new20:n16")
    client = Langfuse(base_url="http://127.0.0.1:9", mask=tracing._mask, span_exporter=exporter)
    monkeypatch.setattr(tracing, "_client", client)

    def spans():
        client.flush()
        return {s.name: dict(s.attributes) for s in exporter.get_finished_spans()}, exporter.get_finished_spans()

    yield spans
    client.shutdown()


def _dump(spans) -> str:
    return " ".join(f"{s.attributes} {[(e.name, dict(e.attributes)) for e in s.events]} {s.status.description}" for s in spans)


def test_records_usage_and_latency_without_any_original_text(exported):
    chat, bot = _classes()
    tracing.instrument(chat, bot)
    tracing.instrument(chat, bot)  # 두 번 감싸지 않는다

    result = bot().answer("비밀질문")

    assert result["answer"] == "비밀답변"
    by_name, spans = exported()
    assert sorted(s.name for s in spans) == ["llm", "rag-question"]
    llm, question = by_name["llm"], by_name["rag-question"]
    assert '"input": 120' in llm["langfuse.observation.usage_details"]
    assert llm["langfuse.observation.model.name"] == "gpt-oss:20b"
    text = _dump(spans)
    assert "run1:multi_agent" in text and "new20:n16" in text and "retrieve" in text
    assert "langfuse.observation.metadata.llm_calls" in question
    assert not [secret for secret in SECRETS if secret in text]


def test_errors_propagate_and_their_messages_are_not_recorded(exported):
    chat, bot = _classes(fail=True)
    tracing.instrument(chat, bot)

    with pytest.raises(RuntimeError, match="비밀오류"):
        bot().answer("비밀질문")

    _, spans = exported()
    text = _dump(spans)
    assert "RuntimeError" in text
    assert not [secret for secret in SECRETS if secret in text]


def test_mask_hides_everything_except_numeric_metadata():
    assert tracing._mask(data="비밀질문") == "[excluded]"
    assert tracing._mask(data={"question": "비밀질문"}) == "[excluded]"
    assert tracing._mask(data={"prompt_chars": 4}) == {"prompt_chars": 4}


def test_without_keys_nothing_is_created(monkeypatch):
    monkeypatch.setenv("LANGFUSE_TRACING_ENABLED", "true")
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    monkeypatch.setattr(tracing, "_client", None)
    chat, bot = _classes()
    tracing.instrument(chat, bot)

    assert bot().answer("q")["answer"] == "비밀답변"
    assert tracing._client is None
