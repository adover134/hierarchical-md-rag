"""재정렬 점수(`_score_result`)의 수치·제목 낱말 규칙 테스트. m9(전자입찰서 접수 마감일시)에서 드러난 오작동을 고정한다."""

import pytest

from src.utils.rerank_rules import FUNCTION_WORDS, has_answer_number


class TestHasAnswerNumber:
    @pytest.mark.parametrize("text", [
        "일   정: 2026. 08. 12. 15:00",
        "마감은 2026-08-12 입니다",
        "개찰: 16:00 이후",
        "공사기간: 착공일로부터 120일",
        "기초금액: 금51,330,000원",
        "할인율 5%",
    ])
    def test_values_that_answer_a_question(self, text):
        assert has_answer_number(text)

    @pytest.mark.parametrize("text", [
        "입찰금액의 100분의 5이상 투찰한 자",
        "제3절-1-나-9)에 따라",
        "문의 내용이 없습니다",
    ])
    def test_fractions_and_clause_numbers_are_not_answers(self, text):
        assert not has_answer_number(text)

    def test_function_words_are_listed(self):
        assert {"위한", "대한", "관한"} <= FUNCTION_WORDS


@pytest.fixture(scope="module")
def bot():
    from src.graph.workflow import RAGChatbotV17

    return object.__new__(RAGChatbotV17)


Q = "소상공인 상세페이지 제작지원을 위한 생성형 AI 콘텐츠 제작 서비스 공급 및 운영 용역의 전자입찰서 접수 마감일시는 언제인가요?"
ORG = "소상공인 상세페이지 제작지원을 위한 생성형 AI 콘텐츠 제작 서비스 공급 및 운영 용역"


def _item(text, org=ORG):
    return {"text": text, "metadata": {"org": org, "source": "s", "page": 1, "type": "hwp"}}


def _score(bot, text, org=ORG, org_name=ORG):
    return bot._score_result(Q, _item(text, org), org_name=org_name, prefer_original=True)


class TestFocusTerms:
    def test_particles_and_function_words_are_removed(self, bot):
        terms = bot._rerank_focus_terms(Q)
        assert "제작지원" in terms and "제작지원을" not in terms
        assert not set(terms) & FUNCTION_WORDS


class TestScoreResult:
    SCHEDULE = "## 2. 입찰일정\n\n구   분: 전자입찰서 접수마감일시, 일   정: 2026. 08. 12. 15:00, 비   고: 나라장터"
    LEGAL = "## 14. 기타사항\n\n가. 입찰에 참가하고자 하는 자는 국가를 당사자로 하는 계약에 관한 법률에 따른다."

    def test_schedule_chunk_beats_boilerplate_for_a_deadline_question(self, bot):
        assert _score(bot, self.SCHEDULE) > _score(bot, self.LEGAL)

    def test_fraction_does_not_earn_the_number_bonus(self, bot):
        fraction = _score(bot, "보증금은 입찰금액의 100분의 5 이상")
        percent = _score(bot, "보증금은 입찰금액의 100% 이상")
        assert percent - fraction >= 1.0

    def test_target_org_chunk_is_not_penalised_for_missing_title_words(self, bot):
        text = "일정 2026. 08. 12. 15:00"
        same_org = _score(bot, text)
        other_org = _score(bot, text, org="다른 공고")
        # 같은 기관이면 기관 일치 점수(+5)만 더 붙어야 한다. 제목 낱말 감점(-1.4)까지 풀리면 차이가 6.4가 된다
        assert same_org - other_org >= 6.0
