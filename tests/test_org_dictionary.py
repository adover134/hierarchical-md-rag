"""입찰공고 엑셀의 기관명으로 Kiwi 사용자 사전을 만드는 규칙(`src/utils/org_dictionary.py`) 테스트.

기관명은 이 코퍼스의 엑셀 `공고기관` 값이다.
"""

import pytest

from src.utils.org_dictionary import clean_org_name, new_kiwi, org_words, write_user_dictionary


class TestCleanOrgName:
    @pytest.mark.parametrize("raw, cleaned", [
        ("(주)한성케미칼", "한성케미칼"),
        ("두산에너빌리티 (주)", "두산에너빌리티"),
        ("엘에스이링크㈜", "엘에스이링크"),
        ("주식회사 에스알", "에스알"),
        ("(사）한국불교종단협의회", "한국불교종단협의회"),
        ("전주사랑의집", "전주사랑의집"),
        ("(재)청주문화재단", "청주문화재단"),
        ("(학)한서대학교", "한서대학교"),
        ("(유)대한상사", "대한상사"),
        ("합명회사 가나다", "가나다"),
    ])
    def test_legal_markers_are_removed(self, raw, cleaned):
        assert clean_org_name(raw) == cleaned

    def test_spaces_inside_the_name_are_kept(self):
        assert clean_org_name("충청북도교육청 한림디자인고등학교") == "충청북도교육청 한림디자인고등학교"


class TestOrgWords:
    def test_each_word_of_a_multi_word_name_is_an_entry(self):
        assert org_words(["서울특별시강서교육청 신목중학교"]) == ["서울특별시강서교육청", "신목중학교"]

    def test_duplicates_and_one_character_words_are_dropped(self):
        assert org_words(["선문대학교", "선문대학교", "가"]) == ["선문대학교"]

    def test_name_without_marker_is_added_alongside_the_marked_forms(self):
        words = org_words(["(주)한성케미칼"])
        assert words[0] == "한성케미칼"
        assert "(주)한성케미칼" in words and "한성케미칼(주)" in words

    def test_association_marker_variant_is_included(self):
        # 엑셀에는 `(사）한국불교종단협의회`처럼 괄호 모양이 섞여 있다
        words = org_words(["(사）한국불교종단협의회"])
        assert "한국불교종단협의회" in words and "(사)한국불교종단협의회" in words

    def test_separate_marker_is_attached_to_the_name(self):
        words = org_words(["두산에너빌리티 (주)", "주식회사 에스알"])
        assert "두산에너빌리티" in words and "(주)두산에너빌리티" in words
        assert "에스알" in words and "주식회사에스알" in words

    def test_non_legal_parentheses_are_part_of_the_name_and_kept(self):
        assert clean_org_name("경성대학교 (직속기관)") == "경성대학교 (직속기관)"

    def test_foundation_marker_variant_is_included(self):
        words = org_words(["(재)청주문화재단"])
        assert "청주문화재단" in words and "(재)청주문화재단" in words and "청주문화재단(재)" in words

    def test_a_marker_alone_is_never_an_entry(self):
        words = org_words(["두산에너빌리티 (주)", "엘에스이링크㈜", "주식회사 에스알"])
        assert not {"(주)", "주식회사", "㈜"} & set(words)


class TestUserDictionary:
    def test_written_in_kiwi_format(self, tmp_path):
        path = tmp_path / "org_dictionary.txt"
        write_user_dictionary(["신목중학교"], path)
        assert path.read_text(encoding="utf-8").splitlines() == ["신목중학교\tNNP\t0"]

    def test_proper_noun_stays_one_token_after_loading(self, tmp_path):
        path = tmp_path / "org_dictionary.txt"
        write_user_dictionary(["전주사랑의집"], path)
        kiwi = new_kiwi(path)
        forms = [m.form for m in kiwi.tokenize("전주사랑의집 남자생활실 타일공사의 기초금액은")]
        assert "전주사랑의집" in forms

    def test_missing_dictionary_file_gives_plain_kiwi(self, tmp_path):
        kiwi = new_kiwi(tmp_path / "none.txt")
        assert [m.form for m in kiwi.tokenize("공사기간")]


class TestExcelCoverage:
    """엑셀의 모든 기관명에서 표기를 뗀 뒤 괄호가 남으면, 목록에 없는 새 표기가 있다는 뜻이다."""

    def test_no_bracketed_marker_is_left_after_cleaning(self):
        from pathlib import Path

        from src.utils.bid_list_xlsx import read_bid_list_rows

        xlsx = Path(__file__).resolve().parent.parent / "RAG_프로세스_테스트_데이터_원본" / "입찰공고목록_20260808_20260809.xlsx"
        if not xlsx.is_file():
            pytest.skip("테스트 데이터 엑셀이 없다")
        left = {
            clean_org_name(row.get(col, ""))
            for row in read_bid_list_rows(xlsx)
            for col in ("공고기관", "수요기관")
            if any(ch in clean_org_name(row.get(col, "")) for ch in "()（）㈜")
        }
        assert not left, f"목록에 없는 법인 표기: {sorted(left)}"
