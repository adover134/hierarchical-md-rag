"""채점 검증용 원본 검색(`scripts/judge_search.py`)의 테스트."""

import struct
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from judge_search import docs_text, hwp_section_text, hwpx_text, search_text, show_text  # noqa: E402

HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"


def _record(tag, payload):
    size = len(payload)
    head = tag | (min(size, 0xFFF) << 20)
    extra = struct.pack("<I", size) if size >= 0xFFF else b""
    return struct.pack("<I", head) + extra + payload


def test_hwp_text_keeps_characters_and_skips_inline_controls_and_other_records():
    tab = struct.pack("<8H", 9, 0, 0, 0, 0, 0, 0, 9)  # 탭은 8글자 자리를 쓰는 제어 문자
    paragraph = "기초금액".encode("utf-16-le") + tab + "100원".encode("utf-16-le") + struct.pack("<H", 13)
    long_text = ("가" * 3000).encode("utf-16-le")  # 크기가 4095byte 이상이면 길이를 따로 적는다
    data = _record(66, b"\0" * 8) + _record(67, paragraph) + _record(67, long_text)
    assert hwp_section_text(data).split("\n") == ["기초금액 100원", "가" * 3000]


def test_hwpx_text_reads_paragraphs_in_section_order(tmp_path):
    def section(text):
        return f'<s xmlns:hp="{HP}"><hp:p><hp:run><hp:t>{text}</hp:t></hp:run></hp:p></s>'

    path = tmp_path / "a.hwpx"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("Contents/section10.xml", section("뒤"))
        z.writestr("Contents/section2.xml", section("앞"))
    assert hwpx_text(path) == "앞\n뒤"


CORPUS = {
    "documents": [
        {"no": 1, "file": "도로 공사(1지역)_아산시", "lines": ["아산시 공고 제1호", "공사건명: 도로 공사(1지역)", "기초금액: 100,000,000원"]},
        {"no": 2, "file": "도로 공사(2지역)_아산시", "lines": ["아산시 공고 제2호", "공사건명: 도로 공사(2지역)", "기초금액: 100,000,000원"]},
    ],
}


def test_search_ranks_the_document_with_the_rarer_word_first_and_ignores_misses():
    found = search_text(CORPUS, "기초금액 2지역")
    assert found.index("[문서 2]") < found.index("[문서 1]")
    assert search_text(CORPUS, "없는낱말") == "찾은 것이 없습니다."


def test_search_matches_numbers_written_with_or_without_commas():
    assert "[문서 1]" in search_text(CORPUS, "100000000")


def test_docs_lists_every_document_with_its_number():
    assert docs_text(CORPUS) == "문서 1: 도로 공사(1지역)_아산시\n문서 2: 도로 공사(2지역)_아산시"


def test_show_returns_numbered_lines_from_the_start_line():
    assert show_text(CORPUS, 2, start=2, lines=1) == "[문서 2] 도로 공사(2지역)_아산시 (전체 3줄)\n2: 공사건명: 도로 공사(2지역)"
    assert show_text(CORPUS, 9) == "문서 9가 없습니다."
