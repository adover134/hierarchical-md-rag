import csv

from src.metadata.team_view import is_metadata_row, to_team_row
from src.parsers.csv_loader import CSVMarkdownConverter

ROW = {"업무구분": "공사", "입찰공고번호": "R26BK01-000", "공고명": "전주사랑의집 시설공사", "공고기관": "전주", "수요기관": "전주사랑의집",
       "게시일시": "2026/08/09 17:26", "입찰마감일시": "2026/08/14 10:00", "사업 금액": "50000000", "사업 요약": "", "파일명": "전주사랑의집 시설공사_전주사랑의집.md"}


def test_columns_are_renamed_without_changing_values():
    assert is_metadata_row(ROW)
    t = to_team_row(ROW)
    assert t["사업명"] == "전주사랑의집 시설공사" and t["발주 기관"] == "전주사랑의집"
    assert t["사업 금액"] == "50000000" and t["공고 번호"] == "R26BK01" and t["공고 차수"] == "000"
    assert t["입찰 참여 마감일"] == "2026/08/14 10:00" and t["공개 일자"] == "2026/08/09 17:26"


def test_loader_reads_metadata_csv_with_the_right_project_and_amount(tmp_path):
    p = tmp_path / "metadata.csv"
    with open(p, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(ROW)); w.writeheader(); w.writerow(ROW)
    docs = CSVMarkdownConverter().convert_file(p)
    assert len(docs) == 1
    text = docs[0].markdown
    assert "전주사랑의집 시설공사" in text and "50,000,000" in text
