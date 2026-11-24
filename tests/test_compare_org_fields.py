import compare_org_fields as C

CSV = "공고명,수요기관,공고기관,파일명\n충전_14_아산,엘에스,x,충전_14_아산_엘에스.md\n충전_16_의성,엘에스,x,충전_16_의성_엘에스.md\n가사업,나기관,x,가사업_나기관.md\n"


def test_only_changed_documents_are_listed_with_the_shared_old_org_count(tmp_path):
    p = tmp_path / "metadata.csv"
    p.write_text(CSV, encoding="utf-8-sig")
    changed, _ = C.compare(p)
    assert [c["file"] for c in changed] == ["충전_14_아산_엘에스.md", "충전_16_의성_엘에스.md"]
    assert changed[0]["old"] == ("충전", "14_아산_엘에스") and changed[0]["new"] == ("충전_14_아산", "엘에스")
    assert changed[0]["old_org_shared"] == 2
