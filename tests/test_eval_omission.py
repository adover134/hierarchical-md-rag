"""누락 측정(`scripts/eval_omission.py`)의 정규화와 coverage 계산 테스트."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from eval_omission import coverage, normalize  # noqa: E402


class TestNormalize:
    def test_drops_spaces_punctuation_and_bold(self):
        assert normalize("**기초 금액**: 50,000,000원") == "기초금액50000000원"

    def test_nfkc_makes_fullwidth_and_halfwidth_equal(self):
        assert normalize("（주）한성") == normalize("(주)한성")


class TestCoverage:
    def test_full_text_kept_gives_one(self):
        text = "공사기간은 착공일로부터 60일입니다. 납품기한은 2026년 12월 31일까지입니다."
        assert coverage(text, [text])["coverage"] == 1.0

    def test_missing_sentence_lowers_coverage(self):
        a = "공사기간은 착공일로부터 육십일입니다."
        b = "납품기한은 이천이십육년 십이월 삼십일일까지입니다."
        got = coverage(a + " " + b, [a])
        assert 0.3 < got["coverage"] < 0.7
        assert got["lost_shingles"] > 0

    def test_split_across_chunks_still_counts_when_each_piece_is_long_enough(self):
        text = "입찰참가자격은 지방자치단체를 당사자로 하는 계약에 관한 법률 시행령에 따른다"
        assert coverage(text, [text[:20], text[20:]], n=4)["coverage"] > 0.8

    def test_frontmatter_is_not_counted_as_source_text(self):
        body = "공사기간은 착공일로부터 60일입니다"
        doc = "---\ndocument_title: 아주긴제목아주긴제목아주긴제목\n---\n" + body
        assert coverage(doc, [body])["coverage"] == 1.0

    def test_extra_chunk_text_raises_ratio_not_coverage(self):
        text = "기초금액은 오천만원입니다 공사기간은 육십일입니다"
        got = coverage(text, [text, text])
        assert got["coverage"] == 1.0 and got["chunk_over_loader"] == 2.0

    def test_empty_source_has_no_coverage(self):
        assert coverage("", ["아무 내용"])["coverage"] is None
