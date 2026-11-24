import csv
from pathlib import Path

import openpyxl
import pytest

from src.metadata.build import MetadataError, build_metadata_rows, write_metadata_csv

HEADER = ["업무구분", "업무여부", "구분", "입찰공고번호", "공고명", "공고기관", "수요기관", "게시일시(입찰마감일시)", "사업 금액"]


def make_xlsx(path: Path, rows, header=HEADER):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["입찰공고목록"])
    ws.append(["생성자 : -"])
    ws.append([])
    ws.append(header)
    for r in rows:
        ws.append(r)
    wb.save(path)


def make_docs(folder: Path, names):
    folder.mkdir(parents=True, exist_ok=True)
    for n in names:
        (folder / n).write_text("본문", encoding="utf-8")


ROW_A = ["공사", "-", "등록공고", "R1-000", "장성 승강기", "경찰청", "경찰청", "2026/08/09 17:26(2026/08/14 10:00)", 24867000]
ROW_B = ["일반용역", "내자", "등록공고", "R2-000", "한중일 회의", "(사)불교", "(사)불교", "2026/08/09 17:51(-)", None]


def test_columns_follow_excel_order_with_split_date_and_extra_columns(tmp_path):
    x = tmp_path / "list.xlsx"
    make_xlsx(x, [ROW_A])
    docs = tmp_path / "md"
    make_docs(docs, ["장성 승강기_경찰청.md"])
    header, rows = build_metadata_rows(x, docs)
    assert header == ["업무구분", "업무여부", "구분", "입찰공고번호", "공고명", "공고기관", "수요기관",
                      "게시일시", "입찰마감일시", "사업 금액", "사업 요약", "파일명",
                      "사업 금액 근거", "입찰마감일시 근거"]
    r = rows[0]
    assert r["게시일시"] == "2026/08/09 17:26"
    assert r["입찰마감일시"] == "2026/08/14 10:00"
    assert r["사업 금액"] == "24867000"
    assert r["사업 요약"] == ""
    assert r["파일명"] == "장성 승강기_경찰청.md"
    assert r["사업 금액 근거"] == "" and r["입찰마감일시 근거"] == ""


def test_dash_deadline_is_blank_and_missing_amount_is_blank(tmp_path):
    x = tmp_path / "list.xlsx"
    make_xlsx(x, [ROW_B])
    docs = tmp_path / "md"
    make_docs(docs, ["한중일 회의_(사)불교.md"])
    _, rows = build_metadata_rows(x, docs)
    assert rows[0]["입찰마감일시"] == ""
    assert rows[0]["사업 금액"] == ""
    assert rows[0]["게시일시"] == "2026/08/09 17:51"


def test_excel_without_amount_column_gets_one(tmp_path):
    x = tmp_path / "list.xlsx"
    make_xlsx(x, [ROW_A[:-1]], header=HEADER[:-1])
    docs = tmp_path / "md"
    make_docs(docs, ["장성 승강기_경찰청.md"])
    header, rows = build_metadata_rows(x, docs)
    assert "사업 금액" in header
    assert rows[0]["사업 금액"] == ""


def test_extra_file_with_same_prefix_is_reported_as_orphan(tmp_path):
    x = tmp_path / "list.xlsx"
    row = ["공사", "-", "등록공고", "R3-000", "충전 사업_14_아산", "아산", "아산", "2026/08/09 10:00(-)", None]
    make_xlsx(x, [row])
    docs = tmp_path / "md"
    make_docs(docs, ["충전 사업_14_아산_공사.md", "충전 사업_14_아산_공사_추가.md"])
    with pytest.raises(MetadataError) as e:
        build_metadata_rows(x, docs)
    assert "충전 사업_14_아산_공사_추가.md" in str(e.value)  # 주인 없는 파일


def test_unmatched_row_and_orphan_file_stop_with_a_list(tmp_path):
    x = tmp_path / "list.xlsx"
    make_xlsx(x, [ROW_A, ROW_B])
    docs = tmp_path / "md"
    make_docs(docs, ["장성 승강기_경찰청.md", "엉뚱한 문서_어딘가.md"])
    with pytest.raises(MetadataError) as e:
        build_metadata_rows(x, docs)
    msg = str(e.value)
    assert "한중일 회의" in msg and "엉뚱한 문서_어딘가.md" in msg


def test_allow_unmatched_keeps_going_with_blank_file_name(tmp_path):
    x = tmp_path / "list.xlsx"
    make_xlsx(x, [ROW_A, ROW_B])
    docs = tmp_path / "md"
    make_docs(docs, ["장성 승강기_경찰청.md"])
    _, rows = build_metadata_rows(x, docs, allow_unmatched=True)
    assert [r["파일명"] for r in rows] == ["장성 승강기_경찰청.md", ""]


def test_pdf_audited_file_matches_and_intermediate_file_is_ignored(tmp_path):
    x = tmp_path / "list.xlsx"
    make_xlsx(x, [ROW_A, ROW_B])
    hwp, pdf = tmp_path / "hwp", tmp_path / "pdf"
    make_docs(hwp, ["장성 승강기_경찰청.md"])
    make_docs(pdf, ["step1_parsed_한중일 회의_(사)불교.md", "step2_audited_한중일 회의_(사)불교.md"])
    _, rows = build_metadata_rows(x, [hwp, pdf])
    assert rows[1]["파일명"] == "step2_audited_한중일 회의_(사)불교.md"


def test_write_csv_round_trip_with_bom(tmp_path):
    x = tmp_path / "list.xlsx"
    make_xlsx(x, [ROW_A])
    docs = tmp_path / "md"
    make_docs(docs, ["장성 승강기_경찰청.md"])
    header, rows = build_metadata_rows(x, docs)
    out = tmp_path / "metadata.csv"
    write_metadata_csv(header, rows, out)
    assert out.read_bytes().startswith(b"\xef\xbb\xbf")
    with open(out, encoding="utf-8-sig", newline="") as f:
        back = list(csv.DictReader(f))
    assert back[0]["입찰마감일시"] == "2026/08/14 10:00"
    assert list(back[0].keys()) == header


def test_dictionary_is_built_from_the_metadata_csv_only(tmp_path):
    from src.utils.org_dictionary import build_dictionary_from_metadata

    x = tmp_path / "list.xlsx"
    row = ["공사", "-", "등록공고", "R4-000", "교복 구매", "서울특별시강서교육청 신목 중학교", "서울특별시강서교육청 신목 중학교", "2026/08/09 10:00(-)", None]
    make_xlsx(x, [row])
    docs = tmp_path / "md"
    make_docs(docs, ["교복 구매_서울특별시강서교육청 신목 중학교.md"])
    header, rows = build_metadata_rows(x, docs)
    csv_path = write_metadata_csv(header, rows, tmp_path / "metadata.csv")
    words = build_dictionary_from_metadata(csv_path, tmp_path / "org_dictionary.txt")
    assert "신목중학교" in words and "신목" in words
    assert (tmp_path / "org_dictionary.txt").read_text(encoding="utf-8").count("\tNNP\t0") == len(words)


def test_db_build_stops_without_metadata_or_dictionary(tmp_path):
    from src.metadata.build import require_metadata

    with pytest.raises(MetadataError) as e:
        require_metadata(tmp_path / "metadata.csv", tmp_path / "org_dictionary.txt")
    assert "build_metadata.py" in str(e.value)
    (tmp_path / "metadata.csv").write_text("x", encoding="utf-8")
    (tmp_path / "org_dictionary.txt").write_text("x", encoding="utf-8")
    require_metadata(tmp_path / "metadata.csv", tmp_path / "org_dictionary.txt")
