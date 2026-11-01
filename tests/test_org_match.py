"""질문에서 기관 후보를 뽑을 때 '고유한 단어 하나'만 겹쳐도 인정하는 규칙(`src/utils/org_match.py`) 테스트.

기관 목록은 이 코퍼스의 실제 공고명을 줄인 것이다. 이전 규칙(겹치는 단어 2개 이상)은 `신목중학교`, `전주사랑의집`처럼
고유명이 단어 하나뿐인 기관을 놓쳤다.
"""

from src.utils.org_match import distinctive_token_candidates

GENERIC = {"학년도", "년도", "교복", "동복", "하복", "구매", "입찰", "공고", "공사", "사업", "견적", "계약", "소액수의", "제출"}


def is_generic(token: str) -> bool:
    import re

    return token in GENERIC or re.sub(r"^\d{4}", "", token) in GENERIC


ORGS = [
    "2027년도 신목중학교 교복구매",
    "2027학년도 서야고등학교 교복(동복 및 하복)구매 2단계입찰",
    "2027학년도 청주하이텍고등학교 교복(동복·하복) 학교주관구매 선정 입찰",
    "2027학년도 한림디자인고등학교 교복(동복,하복) 학교주관구매 선정 입찰 재공고",
    "전주사랑의집 시설공사 소액수의 견적 제출 공고",
    "용화지구 취약지역 생활여건 개조사업 마을회관 리모델링 공사(전기)",
    "용화지구 취약지역 생활여건 개조사업 마을회관 리모델링 공사(건축)",
]


def names(query: str, **kw) -> list[str]:
    return [org for _score, org in distinctive_token_candidates(query, ORGS, is_generic, **kw)]


class TestSingleDistinctiveToken:
    def test_school_name_alone_picks_that_school(self):
        q = "2027학년도 신목중학교 교복(동복 및 하복) 구매의 납품기한은 언제까지인가요?"
        assert names(q) == ["2027년도 신목중학교 교복구매"]

    def test_facility_name_alone_picks_that_notice(self):
        q = "전주사랑의집 남자생활실 타일공사의 기초금액은 얼마인가요?"
        assert names(q) == ["전주사랑의집 시설공사 소액수의 견적 제출 공고"]

    def test_other_schools_are_not_pulled_in_by_shared_wording(self):
        # 서야고 공고와 동복·하복·교복 같은 상투어를 공유해도 학교 이름이 다르면 후보가 아니다
        assert "2027학년도 서야고등학교 교복(동복 및 하복)구매 2단계입찰" not in names(
            "2027학년도 신목중학교 교복(동복 및 하복) 구매의 납품기한은 언제까지인가요?"
        )


class TestWhatDoesNotCount:
    def test_generic_words_never_match(self):
        assert names("교복 구매 입찰 공고의 납품기한은 언제까지인가요?") == []

    def test_word_in_two_notices_matches_both_but_not_when_limit_is_one(self):
        # `마을회관`은 용화지구 두 공고에 모두 있어 df=2 — 허용 한도(2)이면 둘 다 후보가 되고, 한도를 1로 두면 아무도 아니다
        assert len(names("마을회관 공사기간은 며칠인가요?")) == 2
        assert names("마을회관 공사기간은 며칠인가요?", max_doc_freq=1) == []

    def test_year_like_tokens_do_not_match(self):
        assert names("2027년도 납품기한은 언제까지인가요?") == []

    def test_short_tokens_do_not_match(self):
        assert names("고등 입찰의 기한은?") == []

    def test_question_without_any_org_returns_nothing(self):
        assert names("낙찰하한율이 가장 높은 공고는 무엇인가요?") == []


class TestScoring:
    def test_more_distinctive_hits_score_higher(self):
        two = distinctive_token_candidates("신목중학교 교복구매 확인", ORGS, is_generic)
        one = distinctive_token_candidates("신목중학교 확인", ORGS, is_generic)
        assert two[0][0] >= one[0][0]

    def test_returns_score_and_org_pairs(self):
        (score, org), = distinctive_token_candidates("신목중학교 납품", ORGS, is_generic)
        assert isinstance(score, int) and score > 0 and org == "2027년도 신목중학교 교복구매"


class TestExtraQueryTokens:
    """Kiwi가 조사를 뗀 질문 낱말을 넘기면, 조사가 붙은 질문에서도 기관이 잡힌다."""

    def test_particle_attached_name_is_found_through_extra_tokens(self):
        q = "신목중학교의 납품기한은 언제인가요?"
        assert names(q) == []
        got = [o for _s, o in distinctive_token_candidates(q, ORGS, is_generic, extra_query_tokens={"신목중학교"})]
        assert got == ["2027년도 신목중학교 교복구매"]

    def test_extra_tokens_obey_the_same_filters(self):
        got = distinctive_token_candidates("교복 구매의 기한", ORGS, is_generic, extra_query_tokens={"교복", "구매", "2027학년도"})
        assert got == []
