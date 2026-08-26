"""`scripts/api.py`의 인증/요청 검증 배선 테스트.

`RAGChatbotV17`(임베딩 모델·벡터DB·LLM 호출)은 실제로 띄우지 않고 목(mock)으로 대체한다 —
여기서 검증하는 건 답변 품질이 아니라 "인증이 요구될 때 막는지", "빈 질의를 거부하는지",
"query/top_k가 chatbot.answer()에 제대로 전달되는지" 같은 API 계층 자체의 배선이다.
서비스 제공자가 배포 전에 `pytest tests/test_api.py`로 바로 돌려볼 수 있다."""

from __future__ import annotations

from unittest import mock

import api as api_mod
from fastapi.testclient import TestClient

client = TestClient(api_mod.app)


def _fake_chatbot():
    chatbot = mock.Mock()
    chatbot.answer.return_value = {"answer": "테스트 답변", "evidence": [], "found": True}
    chatbot.vector_store.count = 42
    return chatbot


def test_health_reports_chunk_count():
    with mock.patch.object(api_mod, "_get_chatbot", return_value=_fake_chatbot()):
        r = client.get("/v1/health")
    assert r.status_code == 200
    assert r.json() == {"ok": True, "chunk_count": 42}


def test_health_no_auth_required(monkeypatch):
    monkeypatch.setenv("RAG_API_KEYS", "secret1")
    with mock.patch.object(api_mod, "_get_chatbot", return_value=_fake_chatbot()):
        r = client.get("/v1/health")
    assert r.status_code == 200


def test_query_passes_through_when_auth_unconfigured(monkeypatch):
    monkeypatch.delenv("RAG_API_KEYS", raising=False)
    chatbot = _fake_chatbot()
    with mock.patch.object(api_mod, "_get_chatbot", return_value=chatbot):
        r = client.post("/v1/query", json={"query": "테스트 질문", "top_k": 5})
    assert r.status_code == 200
    assert r.json()["answer"] == "테스트 답변"
    chatbot.answer.assert_called_once_with("테스트 질문", top_k=5)


def test_query_rejects_empty_query(monkeypatch):
    monkeypatch.delenv("RAG_API_KEYS", raising=False)
    with mock.patch.object(api_mod, "_get_chatbot", return_value=_fake_chatbot()):
        r = client.post("/v1/query", json={"query": "   "})
    assert r.status_code == 400


def test_query_uses_default_top_k(monkeypatch):
    monkeypatch.delenv("RAG_API_KEYS", raising=False)
    chatbot = _fake_chatbot()
    with mock.patch.object(api_mod, "_get_chatbot", return_value=chatbot):
        client.post("/v1/query", json={"query": "질문"})
    chatbot.answer.assert_called_once_with("질문", top_k=24)


def test_query_without_authorization_header_rejected(monkeypatch):
    monkeypatch.setenv("RAG_API_KEYS", "secret1")
    with mock.patch.object(api_mod, "_get_chatbot", return_value=_fake_chatbot()):
        r = client.post("/v1/query", json={"query": "질문"})
    assert r.status_code == 401


def test_query_with_wrong_key_rejected(monkeypatch):
    monkeypatch.setenv("RAG_API_KEYS", "secret1")
    with mock.patch.object(api_mod, "_get_chatbot", return_value=_fake_chatbot()):
        r = client.post("/v1/query", json={"query": "질문"}, headers={"Authorization": "Bearer wrong"})
    assert r.status_code == 401


def test_query_with_correct_key_accepted(monkeypatch):
    monkeypatch.setenv("RAG_API_KEYS", "secret1")
    with mock.patch.object(api_mod, "_get_chatbot", return_value=_fake_chatbot()):
        r = client.post("/v1/query", json={"query": "질문"}, headers={"Authorization": "Bearer secret1"})
    assert r.status_code == 200


def test_query_with_multiple_configured_keys(monkeypatch):
    monkeypatch.setenv("RAG_API_KEYS", "secret1, secret2")
    with mock.patch.object(api_mod, "_get_chatbot", return_value=_fake_chatbot()):
        r = client.post("/v1/query", json={"query": "질문"}, headers={"Authorization": "Bearer secret2"})
    assert r.status_code == 200
