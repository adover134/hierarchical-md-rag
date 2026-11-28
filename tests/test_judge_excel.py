"""검증자 전용 공고 목록 도구(`scripts/judge_excel.py`)의 테스트."""

import sys
from pathlib import Path

import openpyxl

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from judge_excel import excel_text, read_notices  # noqa: E402

HEADER = ["업무구분", "입찰공고번호", "공고명", "공고기관", "수요기관", "게시일시(입찰마감일시)", "사업 금액"]
ROWS = [
    ["공사", "R1", "도로 공사(1지역)", "아산시", "아산시", "2026/08/09 10:00", 100000000],
    ["공사", "R2", "도로 공사(2지역)", "아산시", "아산시", "2026/08/09 11:00", 200000000],
]
DOCS = [{"no": 7, "file": "도로 공사(2지역)_아산시", "lines": []}]


def _book(tmp_path):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["나라장터 검색 결과"])  # 머리글 앞의 안내 줄
    ws.append(HEADER)
    for row in ROWS:
        ws.append(row)
    wb.save(tmp_path / "입찰공고목록_test.xlsx")
    (tmp_path / "다른 표.xlsx").write_bytes((tmp_path / "입찰공고목록_test.xlsx").read_bytes())
    return read_notices(tmp_path)


def test_read_notices_reads_every_column_of_the_notice_list_only(tmp_path):
    notices = _book(tmp_path)
    assert len(notices) == 2 and list(notices[0]) == HEADER
    assert notices[0]["사업 금액"] == "100000000"


def test_a_search_shows_every_column_and_the_document_number(tmp_path):
    out = excel_text(_book(tmp_path), DOCS, "2지역")
    assert all(f"{name}=" in out for name in HEADER)
    assert "사업 금액=200000000" in out and "문서 7: 도로 공사(2지역)_아산시" in out and "R1" not in out


def test_the_best_matching_row_comes_first_and_amounts_match_with_commas(tmp_path):
    notices = _book(tmp_path)
    out = excel_text(notices, DOCS, "아산시 2지역")
    assert out.index("입찰공고번호=R2") < out.index("입찰공고번호=R1")
    assert "입찰공고번호=R2" in excel_text(notices, DOCS, "200,000,000")
    assert "문서 없음" in excel_text(notices, DOCS, "R1")


def test_an_empty_query_lists_the_columns_and_a_miss_says_so(tmp_path):
    notices = _book(tmp_path)
    assert excel_text(notices, DOCS, "") == f"공고 목록 2건. 열: {', '.join(HEADER)}"
    assert excel_text(notices, DOCS, "없는낱말") == "찾은 것이 없습니다."


def test_long_results_keep_whole_rows_and_say_how_many_are_left(tmp_path):
    rows = [{"공고명": f"공사 {n}", "사업 금액": "1" * 400} for n in range(30)]
    out = excel_text(rows, [], "공사")
    lines = out.split("\n")
    assert len(out) <= 4100 and all(line.startswith("공고명=") for line in lines[:-1])
    assert lines[-1] == f"... 외 {30 - len(lines) + 1}건. 낱말을 더 넣어 좁히세요."
