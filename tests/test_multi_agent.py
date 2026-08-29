"""`HWP_RAG_ANSWER_STRATEGY=multi_agent` 경로(`RFPAnswerGenerator`의 신규 메서드) 테스트.

`ChatOpenAI`(실제 LLM 호출)는 목(mock)으로 대체한다 — 여기서 검증하는 건 답변 품질이
아니라 각 메서드의 파싱/폴백 배선이다: JSON 파싱 실패, 코드블록 래핑, LLM 없음/예외
상황에서 안전하게 저하하는지. 서비스 제공자가 배포 전에 `pytest tests/test_multi_agent.py`로
바로 돌려볼 수 있다(LLM 호출 없이 즉시 실행됨)."""

from __future__ import annotations

from unittest import mock

from src.graph.nodes import RFPAnswerGenerator


def _gen(content: str | None = None, side_effect=None) -> RFPAnswerGenerator:
    gen = RFPAnswerGenerator(llm=mock.Mock())
    if side_effect is not None:
        gen.llm.invoke.side_effect = side_effect
    else:
        gen.llm.invoke.return_value = mock.Mock(content=content)
    return gen


class TestPlanSteps:
    def test_parses_clean_json(self):
        gen = _gen('{"steps": ["step A", "step B"]}')
        assert gen.plan_steps("복합 질문") == ["step A", "step B"]

    def test_parses_code_fenced_json(self):
        gen = _gen('```json\n{"steps": ["only one"]}\n```')
        assert gen.plan_steps("단순 질문") == ["only one"]

    def test_falls_back_to_original_query_on_garbage_output(self):
        gen = _gen("not json at all")
        assert gen.plan_steps("원본 질의") == ["원본 질의"]

    def test_falls_back_when_llm_missing(self):
        gen = RFPAnswerGenerator(llm=None)
        assert gen.plan_steps("q") == ["q"]

    def test_falls_back_on_exception(self):
        gen = _gen(side_effect=RuntimeError("boom"))
        assert gen.plan_steps("q") == ["q"]

    def test_caps_at_three_steps(self):
        gen = _gen('{"steps": ["a", "b", "c", "d", "e"]}')
        assert gen.plan_steps("q") == ["a", "b", "c"]

    def test_empty_steps_list_falls_back(self):
        gen = _gen('{"steps": []}')
        assert gen.plan_steps("원본") == ["원본"]


class TestRefineStepQuery:
    def test_returns_clean_text(self):
        gen = _gen("장성경찰서 건축 공사 기초금액")
        result = gen.refine_step_query("장성경찰서 건축/통신 비교", "건축 공사 기초금액")
        assert result == "장성경찰서 건축 공사 기초금액"

    def test_strips_surrounding_quotes(self):
        gen = _gen('"따옴표로 감싼 결과"')
        assert gen.refine_step_query("q", "step") == "따옴표로 감싼 결과"

    def test_falls_back_to_step_text_on_exception(self):
        gen = _gen(side_effect=RuntimeError("boom"))
        assert gen.refine_step_query("q", "original step text") == "original step text"

    def test_falls_back_when_llm_missing(self):
        gen = RFPAnswerGenerator(llm=None)
        assert gen.refine_step_query("q", "step") == "step"

    def test_falls_back_to_step_text_when_response_empty(self):
        gen = _gen("")
        assert gen.refine_step_query("q", "step text") == "step text"


class TestGenerateMultiAgent:
    def test_single_llm_call_returns_answer_and_counts_calls(self):
        gen = _gen("기초금액은 368,467,000원입니다.")
        answer = gen.generate_multi_agent("질문", "[기관 - source]\n건축 공사 기초금액 368,467,000원")
        assert answer == "기초금액은 368,467,000원입니다."
        assert gen.last_generation_llm_calls == 1
        gen.llm.invoke.assert_called_once()

    def test_handles_missing_llm(self):
        gen = RFPAnswerGenerator(llm=None)
        assert gen.generate_multi_agent("q", "ctx") == "LLM 클라이언트가 없습니다."

    def test_handles_exception_gracefully(self):
        gen = _gen(side_effect=RuntimeError("boom"))
        answer = gen.generate_multi_agent("q", "ctx")
        assert answer.startswith("오류:")

    def test_does_not_reselect_evidence_from_ranked_context(self):
        """이 경로의 핵심 목적: 이미 랭킹된 컨텍스트를 다시 추려내는 재판단(Stage 1과
        동일한 실패 유형) 없이 그대로 생성 프롬프트에 전달돼야 한다."""
        gen = _gen("답변")
        ranked_context = "[기관 - source]\n중요한 근거 텍스트"
        gen.generate_multi_agent("질문", ranked_context, history="이전 대화 요약")
        sent_messages = gen.llm.invoke.call_args[0][0]
        combined = "\n".join(str(getattr(m, "content", "")) for m in sent_messages)
        assert "중요한 근거 텍스트" in combined
        assert "이전 대화 요약" in combined
