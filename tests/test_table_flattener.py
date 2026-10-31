"""표 평탄화(`src/parsers/table_flattener.py`) 테스트.

입력은 모두 파서 skill(kordoc)이 실제로 낸 Markdown 표이거나 그 형태를 줄인 것이다.
"""

from src.parsers.table_flattener import flatten_table, flatten_tables_in_text


def lines(text: str) -> list[str]:
    return [line for line in text.split("\n") if line]


# --- 새 동작 1: 병합 2단 헤더 -----------------------------------------------------------

AMOUNT_TABLE = """\
| 추정금액 | 기 초 금 액 |  |  | 관 급 자 재 |  |
| --- | --- | --- | --- | --- | --- |
| 추정금액 | 계 | 추정가격 | 부가가치세 | 도급자설치 | 관급자설치 |
| 285,125,000 | 285,125,000 | 259,204,546 | 25,920,454 | - | 285,000 |"""


class TestMergedTwoRowHeader:
    def test_sub_header_is_combined_with_filled_forward_top_header(self):
        assert lines(flatten_table(AMOUNT_TABLE)) == [
            "추정금액: 285,125,000, 기 초 금 액 계: 285,125,000, 기 초 금 액 추정가격: 259,204,546, "
            "기 초 금 액 부가가치세: 25,920,454, 관 급 자 재 도급자설치: -, 관 급 자 재 관급자설치: 285,000"
        ]

    def test_sub_header_row_is_not_emitted_as_data(self):
        out = flatten_table(AMOUNT_TABLE)
        assert "계, 추정가격" not in out

    def test_several_data_rows(self):
        table = AMOUNT_TABLE + "\n| 1 | 2 | 3 | 4 | 5 | 6 |"
        assert len(lines(flatten_table(table))) == 2

    def test_grade_columns_under_one_merged_header(self):
        table = """\
| 구분 | 평가항목 | 등급 |  |  |  |  | 평점 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 구분 | 평가항목 | A | B | C | D | E | 평점 |
| 정량적<br>평가<br>(20점) | 【업체의 신뢰도】 | 10 | 8 | 6 | 4 | 2 | (      ) |"""
        out = flatten_table(table)
        for pair in ("구분: 정량적 평가 (20점)", "등급 A: 10", "등급 B: 8", "등급 E: 2"):
            assert pair in out

    def test_unmerged_top_cells_keep_their_own_label_when_equal(self):
        # 상위/하위 라벨이 같으면 한 번만 쓴다 (장성경찰서 표)
        table = """\
| 공사예정금액 (A=B+E) | 기초금액 (B=C+D) | 관급자재 |  |
| --- | --- | --- | --- |
| 공사예정금액 (A=B+E) | 기초금액 (B=C+D) | 도급자설치(E) | 관급자설치 |
| 368,467,000 | 334,970,000 | - | 55,380,000 |"""
        assert lines(flatten_table(table)) == [
            "공사예정금액 (A=B+E): 368,467,000, 기초금액 (B=C+D): 334,970,000, "
            "관급자재 도급자설치(E): -, 관급자재 관급자설치: 55,380,000"
        ]


# --- 새 동작 2: 헤더 없는 표(숫자·기호 셀) -----------------------------------------------

RATIO_TABLE = """\
| - 지반조성·포장공사업 | : | 14,045,146 | 5.4 | % |
| --- | --- | --- | --- | --- |
| - 실내건축공사업 | : | 47,615,183 | 18.4 | % |
| 전문공사 업종별 합계 | : | 259,204,546 | 100 | % |"""


class TestHeaderlessValueTable:
    def test_first_row_is_data_not_header(self):
        assert lines(flatten_table(RATIO_TABLE)) == [
            "지반조성·포장공사업: 14,045,146 (5.4%)",
            "실내건축공사업: 47,615,183 (18.4%)",
            "전문공사 업종별 합계: 259,204,546 (100%)",
        ]

    def test_two_row_table(self):
        table = "| - A공사업 | : | 1,000 | 50 | % |\n| --- | --- | --- | --- | --- |\n| - B공사업 | : | 1,000 | 50 | % |"
        assert lines(flatten_table(table)) == ["A공사업: 1,000 (50%)", "B공사업: 1,000 (50%)"]

    def test_year_header_table_is_not_mistaken_for_headerless(self):
        # 숫자 하나뿐인 진짜 헤더(연도)는 건드리지 않는다
        table = "| 구분 | 2026 | 2027 |\n| --- | --- | --- |\n| 예산 | 100 | 200 |"
        assert lines(flatten_table(table)) == ["구분: 예산, 2026: 100, 2027: 200"]


# --- 기존 동작 유지 (커밋 3728ab8 포함) ----------------------------------------------------

LABEL_VALUE_GRID = """\
| 사 업 명 | 2026년 산지전용지(구촌) 대집행복구공사 |  |  |
| --- | --- | --- | --- |
| 사업위치 | 영동군 일원 |  |  |
| 사업개요 | 공사 1식(산지복구 A=4,657㎡) |  |  |
| 공사기간 | 착공일로부터 60일 |  |  |
| 추정금액 | 금45,261,650원 | 기초금액 | 금45,261,650원 |
| 입찰 개시일시 | 2026.08.12.(수) 12:00 | 입찰 마감일시 | 2026.08.14.(금) 12:00 |"""


class TestExistingBehaviourIsKept:
    def test_headerless_label_value_grid(self):
        out = lines(flatten_table(LABEL_VALUE_GRID))
        assert out[0] == "사 업 명: 2026년 산지전용지(구촌) 대집행복구공사"
        assert "공사기간: 착공일로부터 60일" in out
        assert "추정금액: 금45,261,650원, 기초금액: 금45,261,650원" in out

    def test_two_column_key_value_table(self):
        table = "| 사업명 | 차세대 포털 |\n| --- | --- |\n| 사업기간 | 24개월 |"
        assert lines(flatten_table(table)) == ["사업명: 차세대 포털", "사업기간: 24개월"]

    def test_plain_multi_column_table_uses_headers(self):
        table = "| 연번 | 학교명 | 계약금액 |\n| --- | --- | --- |\n| 1 | 덕적고 | 1,000원 |"
        assert lines(flatten_table(table)) == ["연번: 1, 학교명: 덕적고, 계약금액: 1,000원"]

    def test_item_quantity_two_row_header_is_not_treated_as_label_grid(self):
        table = """\
| 시설명 | 수량 | 시설명 | 수량 |
| --- | --- | --- | --- |
| 시설명 | 수량 | 시설명 | 수량 |
| 미싱 | 3 | 오버로크 | 2 |"""
        out = flatten_table(table)
        assert "시설명: 미싱, 수량: 3, 시설명: 오버로크, 수량: 2" in out
        assert "시설명: 시설명" not in out

    def test_placeholder_headers_print_values_only(self):
        table = "| Col1 | Col2 |\n| --- | --- |\n| a | b |"
        assert lines(flatten_table(table)) == ["a, b"]

    def test_text_outside_tables_is_untouched(self):
        text = "제목 문장입니다.\n\n| 사업명 | 포털 |\n| --- | --- |\n| 기간 | 24개월 |\n\n끝."
        out = flatten_tables_in_text(text)
        assert "제목 문장입니다." in out and "끝." in out
        assert "기간: 24개월" in out
