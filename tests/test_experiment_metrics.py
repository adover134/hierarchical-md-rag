"""실험용 신규 지표(`src/evaluation/metrics.py`)의 단위 테스트 — LLM/DB 호출 없음."""

import pytest

from src.evaluation.metrics import (
    calculate_context_hit_rate,
    calculate_header_inclusion_rate,
    calculate_key_value_hit_position,
    calculate_key_value_mrr,
    calculate_table_pair_accuracy,
    extract_key_values,
    judge_numeric_comparison,
    normalize_for_match,
    table_pair_present,
)


class TestExtractKeyValues:
    def test_amount_with_commas_and_unit(self):
        assert extract_key_values("기초금액은 금285,125,000원(금이억팔천오백일십이만오천원)입니다.") == ["285,125,000원"]

    def test_days_with_unit(self):
        assert extract_key_values("공사기간은 착공일로부터 60일입니다.") == ["60일"]

    def test_percent(self):
        assert extract_key_values("낙찰하한율은 87.745%입니다.") == ["87.745%"]

    def test_date_is_one_token(self):
        assert extract_key_values("입찰 마감일은 2026. 8. 9.입니다.") == ["2026. 8. 9."]

    def test_bare_short_number_is_dropped(self):
        # 단위 없는 1~2자리 숫자는 너무 모호해서 핵심값으로 쓰지 않는다
        assert extract_key_values("총 3개 항목 중 2번째") == ["3개"]

    def test_no_numbers_returns_empty(self):
        assert extract_key_values("최저가 낙찰제입니다.") == []

    def test_dedup_preserves_order(self):
        assert extract_key_values("A는 100,000원, B는 200,000원, 다시 100,000원") == ["100,000원", "200,000원"]


class TestNormalizeForMatch:
    def test_removes_whitespace_and_commas(self):
        assert normalize_for_match("285, 125,000 원") == "285125000원"

    def test_date_canonicalised(self):
        assert normalize_for_match("2026. 8. 9.") == normalize_for_match("2026년 08월 09일")


class TestKeyValueHit:
    def test_hit_position_is_first_rank_where_all_values_present(self):
        texts = ["무관한 청크", "기초금액 285,125,000원", "공사기간 60일"]
        assert calculate_key_value_hit_position(texts, ["285,125,000원"]) == 2
        assert calculate_key_value_hit_position(texts, ["285,125,000원", "60일"]) == 3

    def test_values_may_span_chunks_cumulatively(self):
        texts = ["A 100,000원", "B 200,000원"]
        assert calculate_key_value_hit_position(texts, ["100,000원", "200,000원"]) == 2

    def test_miss_returns_none(self):
        assert calculate_key_value_hit_position(["없음"], ["60일"]) is None

    def test_no_key_values_returns_none(self):
        assert calculate_key_value_hit_position(["아무거나"], []) is None

    def test_comma_and_space_insensitive(self):
        assert calculate_key_value_hit_position(["금 285125000 원"], ["285,125,000원"]) == 1


class TestAggregates:
    def test_context_hit_rate_counts_only_eligible(self):
        positions = [1, 4, None, 7]
        assert calculate_context_hit_rate(positions, k=3) == pytest.approx(1 / 4)
        assert calculate_context_hit_rate(positions, k=5) == pytest.approx(2 / 4)

    def test_context_hit_rate_empty_is_none(self):
        assert calculate_context_hit_rate([], k=5) is None

    def test_mrr(self):
        assert calculate_key_value_mrr([1, 2, None, 4]) == pytest.approx((1 + 0.5 + 0 + 0.25) / 4)

    def test_mrr_empty_is_none(self):
        assert calculate_key_value_mrr([]) is None


class TestHeaderInclusion:
    def test_fraction_of_top_k_with_section_metadata(self):
        chunks = [
            {"section_level1": "1. 입찰개요", "section_level2": "N/A"},
            {"section_level1": "N/A", "section_level2": "N/A"},
            {"section_level1": "", "section_level2": ""},
            {"section_level1": "2. 계약", "section_level2": "2-1"},
        ]
        assert calculate_header_inclusion_rate(chunks, k=4) == pytest.approx(2 / 4)
        assert calculate_header_inclusion_rate(chunks, k=1) == pytest.approx(1.0)

    def test_missing_metadata_counts_as_absent(self):
        assert calculate_header_inclusion_rate([{}], k=1) == 0.0

    def test_empty_returns_none(self):
        assert calculate_header_inclusion_rate([], k=5) is None


class TestTablePairs:
    def test_pair_present_with_flattener_format(self):
        chunk = "공사기간: 착공일로부터 60일\n착공일: 2026-09-01"
        assert table_pair_present([chunk], "공사기간", "착공일로부터 60일")

    def test_label_value_scrambling_is_not_a_match(self):
        # 라벨이 뒤섞인 실제 사례(헤더 없는 표의 첫 행이 헤더로 오인됨)
        chunk = "사 업 명: 공사기간, 산지전용지: 착공일로부터 60일"
        assert not table_pair_present([chunk], "공사기간", "착공일로부터 60일")

    def test_whitespace_in_label_tolerated(self):
        assert table_pair_present(["사 업 명: 임도구조개량사업"], "사업명", "임도구조개량사업")

    def test_fullwidth_colon(self):
        assert table_pair_present(["기초금액： 285,125,000원"], "기초금액", "285,125,000원")

    def test_accuracy(self):
        chunks = ["공사기간: 60일", "기초금액: 100원"]
        pairs = [("공사기간", "60일"), ("기초금액", "100원"), ("납품기한", "30일")]
        assert calculate_table_pair_accuracy(chunks, pairs) == pytest.approx(2 / 3)

    def test_accuracy_no_pairs_is_none(self):
        assert calculate_table_pair_accuracy(["x"], []) is None


class TestNumericComparison:
    def test_larger_correct(self):
        ok = judge_numeric_comparison(
            answer="A 사업(285,125,000원)이 B 사업(120,000,000원)보다 큽니다. 더 큰 곳은 A입니다.",
            expected_values=["285,125,000원", "120,000,000원"],
            expected_winner="A",
        )
        assert ok is True

    def test_wrong_winner(self):
        ok = judge_numeric_comparison(
            answer="B가 더 큽니다. A는 285,125,000원, B는 120,000,000원입니다.",
            expected_values=["285,125,000원", "120,000,000원"],
            expected_winner="A",
        )
        assert ok is False

    def test_missing_value_is_wrong(self):
        ok = judge_numeric_comparison(
            answer="A가 더 큽니다.",
            expected_values=["285,125,000원", "120,000,000원"],
            expected_winner="A",
        )
        assert ok is False

    def test_without_winner_only_values_checked(self):
        ok = judge_numeric_comparison(
            answer="공사기간은 60일과 90일입니다.",
            expected_values=["60일", "90일"],
            expected_winner=None,
        )
        assert ok is True
