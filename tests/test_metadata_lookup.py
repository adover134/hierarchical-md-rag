from src.metadata.lookup import org_fields_for

CSV = "공고명,수요기관,공고기관,파일명\n교복 구매_1차,신목중학교,교육청,교복 구매_1차_신목중학교.md\n빈 기관,,,빈 기관_x.md\n"


def test_org_is_the_title_and_project_name_is_the_agency_even_if_title_has_underscore(tmp_path):
    p = tmp_path / "metadata.csv"
    p.write_text(CSV, encoding="utf-8-sig")
    assert org_fields_for("교복 구매_1차_신목중학교.md", p) == ("교복 구매_1차", "신목중학교")


def test_unknown_file_or_missing_csv_gives_none(tmp_path):
    p = tmp_path / "metadata.csv"
    p.write_text(CSV, encoding="utf-8-sig")
    assert org_fields_for("없는 문서.md", p) is None
    assert org_fields_for("x.md", tmp_path / "nope.csv") is None
    assert org_fields_for("빈 기관_x.md", p) is None
