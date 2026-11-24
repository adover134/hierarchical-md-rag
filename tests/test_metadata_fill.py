import json

import pytest

from src.metadata.fill import FillError, export_batches, find_blanks, import_answers, read_csv, write_csv

HEADER = ["입찰공고번호", "공고명", "입찰마감일시", "사업 금액", "파일명", "사업 금액 근거", "입찰마감일시 근거"]


def make_csv(path):
    rows = [
        dict(zip(HEADER, ["R1-000", "가", "", "", "가_x.md", "", ""])),
        dict(zip(HEADER, ["R2-000", "나", "2026/08/14 10:00", "5000", "나_x.md", "", ""])),
        dict(zip(HEADER, ["R3-000", "다", "", "7", "다_x.md", "", "문서에 없음"])),
    ]
    write_csv(path, HEADER, rows)


def test_only_blank_cells_without_evidence_are_exported(tmp_path):
    make_csv(tmp_path / "m.csv")
    _, rows = read_csv(tmp_path / "m.csv")
    todo = find_blanks(rows)
    assert [(t["id"], t["fill"]) for t in todo] == [("R1-000", ["사업 금액", "입찰마감일시"])]


def test_export_writes_batches_with_the_rules_and_markdown_path(tmp_path):
    make_csv(tmp_path / "m.csv")
    md = tmp_path / "md"
    md.mkdir()
    (md / "가_x.md").write_text("본문", encoding="utf-8")
    paths = export_batches(tmp_path / "m.csv", [md], tmp_path / "out")
    data = json.loads(paths[0].read_text(encoding="utf-8"))
    assert data["items"][0]["markdown_path"].endswith("가_x.md")
    assert "기초금액" in data["instructions"]["사업 금액"]


def test_import_fills_blanks_checks_form_and_never_overwrites(tmp_path):
    make_csv(tmp_path / "m.csv")
    ans = tmp_path / "a.json"
    ans.write_text(json.dumps([
        {"id": "R1-000", "사업 금액": "98886000", "사업 금액 근거": "기초금액", "입찰마감일시": "", "입찰마감일시 근거": ""},
        {"id": "R2-000", "사업 금액": "1", "사업 금액 근거": "기초금액"},
    ], ensure_ascii=False), encoding="utf-8")
    stats = import_answers(tmp_path / "m.csv", [ans])
    _, rows = read_csv(tmp_path / "m.csv")
    assert rows[0]["사업 금액"] == "98886000" and rows[0]["사업 금액 근거"] == "기초금액"
    assert rows[0]["입찰마감일시"] == "" and rows[0]["입찰마감일시 근거"] == "문서에 없음"
    assert rows[1]["사업 금액"] == "5000"
    assert stats == {"filled": 1, "not_in_document": 1, "skipped_existing": 1}


@pytest.mark.parametrize("answer", [
    {"id": "R1-000", "사업 금액": "98,886,000", "사업 금액 근거": "기초금액"},
    {"id": "R1-000", "사업 금액": "1000", "사업 금액 근거": ""},
    {"id": "R1-000", "입찰마감일시": "8월 14일", "입찰마감일시 근거": "본문"},
    {"id": "없는id", "사업 금액": "1", "사업 금액 근거": "기초금액"},
])
def test_bad_answers_stop_the_import_and_leave_the_csv_unchanged(tmp_path, answer):
    make_csv(tmp_path / "m.csv")
    before = (tmp_path / "m.csv").read_bytes()
    ans = tmp_path / "a.json"
    ans.write_text(json.dumps([answer], ensure_ascii=False), encoding="utf-8")
    with pytest.raises(FillError):
        import_answers(tmp_path / "m.csv", [ans])
    assert (tmp_path / "m.csv").read_bytes() == before
