"""입찰공고목록 엑셀 어댑터 단위 테스트 — 임시 xlsx만 사용, LLM/DB 없음."""

import csv

import openpyxl
import pytest

from src.utils.bid_list_xlsx import bid_list_to_team_csv, load_bid_list_labels, read_bid_list_rows

HEADER = ["업무구분", "업무여부", "구분", "입찰공고번호", "공고명", "공고기관", "수요기관", "게시일시(입찰마감일시)"]


def _write_bid_list(path, rows):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["입찰공고목록"])
    ws.append(["생성자 : -"])
    ws.append(["생성일 : 2026/08/09"])
    ws.append([])
    ws.append(HEADER)
    for r in rows:
        ws.append(r)
    wb.save(path)


@pytest.fixture
def bid_xlsx(tmp_path):
    p = tmp_path / "입찰공고목록_test.xlsx"
    _write_bid_list(p, [
        ["공사", "-", "등록공고", "R26-1", "송림리 마을만들기사업(건축,기계)", "충청남도 서천군", "충청남도 서천군 농업기술센터", "2026/08/09 17:26(-)"],
        ["일반용역", "내자", "등록공고", "R26-2", "임도구조개량사업", "충청북도 영동군", "", "2026/08/08 10:00(-)"],
    ])
    return p


def test_read_rows_skips_preamble_and_uses_header_row(bid_xlsx):
    rows = read_bid_list_rows(bid_xlsx)
    assert len(rows) == 2
    assert rows[0]["공고명"] == "송림리 마을만들기사업(건축,기계)"
    assert rows[1]["수요기관"] == ""


def test_labels_include_title_and_both_orgs(bid_xlsx):
    labels = load_bid_list_labels(bid_xlsx)
    assert "송림리 마을만들기사업(건축,기계)" in labels
    assert "충청남도 서천군 농업기술센터" in labels
    assert "충청북도 영동군" in labels


def test_labels_support_legacy_schema(tmp_path):
    p = tmp_path / "나라장터_RFP_메타데이터.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["사업명", "발주 기관", "파일명"])
    ws.append(["교복 구매", "서울특별시강서교육청 신목중학교", "교복_신목중.pdf"])
    wb.save(p)
    labels = load_bid_list_labels(p)
    assert {"교복 구매", "서울특별시강서교육청 신목중학교", "교복_신목중.pdf"} <= set(labels)


def test_team_csv_schema_and_filename_matching(bid_xlsx, tmp_path):
    corpus = tmp_path / "docs"
    corpus.mkdir()
    (corpus / "송림리 마을만들기사업(건축,기계)_충청남도 서천군 농업기술센터.hwpx").write_bytes(b"")
    (corpus / "임도구조개량사업_충청북도 영동군.pdf").write_bytes(b"")
    out = tmp_path / "data_list.csv"
    stats = bid_list_to_team_csv(bid_xlsx, corpus, out)
    assert stats == {"rows": 2, "matched": 2}
    with open(out, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    assert rows[0]["공고 번호"] == "R26"; assert rows[0]["공고 차수"] == "1"
    assert rows[0]["사업명"] == "송림리 마을만들기사업(건축,기계)"
    assert rows[0]["발주 기관"] == "충청남도 서천군 농업기술센터"  # 수요기관 우선
    assert rows[0]["파일명"].endswith(".hwpx")
    assert rows[0]["파일형식"] == "hwpx"
    assert rows[1]["발주 기관"] == "충청북도 영동군"  # 수요기관 비면 공고기관
    assert rows[0]["사업 금액"] == "" and rows[0]["텍스트"] == ""


def test_unmatched_title_counted(bid_xlsx, tmp_path):
    corpus = tmp_path / "docs"
    corpus.mkdir()
    out = tmp_path / "data_list.csv"
    assert bid_list_to_team_csv(bid_xlsx, corpus, out) == {"rows": 2, "matched": 0}


def test_title_with_underscore_matches_by_prefix(tmp_path):
    p = tmp_path / "list.xlsx"
    _write_bid_list(p, [["공사", "-", "등록공고", "R26-9", "충전사업_14_아산여객_공사", "충남", "아산시", "2026/08/09 1:00(-)"]])
    corpus = tmp_path / "docs"
    corpus.mkdir()
    (corpus / "충전사업_14_아산여객_공사_엘에스이링크㈜.hwp").write_bytes(b"")
    out = tmp_path / "o.csv"
    assert bid_list_to_team_csv(p, corpus, out)["matched"] == 1


def test_chatbot_known_labels_read_bid_list(tmp_path, monkeypatch):
    """현재 버전의 문서 존재 게이트가 입찰공고목록 엑셀도 읽는다(기존 경로는 그대로)."""
    import src.graph.workflow as wf

    (tmp_path / "data_index").mkdir()
    _write_bid_list(tmp_path / "data_index" / "입찰공고목록_20260808_20260809.xlsx", [
        ["공사", "-", "등록공고", "R26-1", "송림리 마을만들기사업(건축,기계)", "충청남도 서천군", "충청남도 서천군 농업기술센터", "2026/08/09 17:26(-)"],
    ])
    monkeypatch.setattr(wf, "PROJECT_ROOT", tmp_path)
    bot = wf.RAGChatbotV17.__new__(wf.RAGChatbotV17)
    bot._known_document_labels_cache = None
    labels = bot._load_known_document_labels()
    assert "송림리 마을만들기사업(건축,기계)" in labels
    assert "충청남도 서천군 농업기술센터" in labels
