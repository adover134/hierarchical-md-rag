"""질문 키워드에서 조사·어미를 떼는 규칙(`src/utils/korean_keywords.py`) 테스트.

실제 Kiwi 분석기를 쓴다. 기대값은 이 코퍼스의 평가 질문(m17, m11, n4)에서 가져왔다.
"""

import pytest

from src.utils.korean_keywords import stem_words


@pytest.fixture(scope="module")
def kiwi():
    from kiwipiepy import Kiwi

    return Kiwi()


class TestStemWords:
    def test_particle_is_stripped_from_compound_noun(self, kiwi):
        assert "공사기간" in stem_words("공사기간은 며칠인가요?", kiwi)
        assert "공사기간은" not in stem_words("공사기간은 며칠인가요?", kiwi)

    def test_copula_and_ending_after_noun_are_dropped(self, kiwi):
        assert stem_words("며칠인가요", kiwi) == ["며칠"]

    def test_possessive_particle_after_compound(self, kiwi):
        assert stem_words("전주사랑의집 남자생활실 타일공사의 기초금액은", kiwi) == [
            "전주사랑의집", "남자생활실", "타일공사", "기초금액",
        ]

    def test_parentheses_split_words_without_losing_them(self, kiwi):
        assert stem_words("산지전용지(구촌) 대집행복구공사의", kiwi) == ["산지전용지", "구촌", "대집행복구공사"]

    def test_number_with_counter_is_kept(self, kiwi):
        assert "2026년" in stem_words("2026년 공사", kiwi)

    def test_verb_derived_noun_keeps_only_the_noun(self, kiwi):
        assert stem_words("납품하는", kiwi) == ["납품"]

    def test_word_without_content_morpheme_is_dropped(self, kiwi):
        assert stem_words("은는이가", kiwi) == []

    def test_empty_text(self, kiwi):
        assert stem_words("", kiwi) == []

    def test_analyzer_failure_falls_back_to_raw_words(self):
        class Broken:
            def tokenize(self, _text):
                raise RuntimeError("boom")

        assert stem_words("공사기간은 며칠", Broken()) == ["공사기간은", "며칠"]
