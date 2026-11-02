"""parser_bridge: 첫 청크 본문에 문서 제목 블록(document_title, source_file)이 들어가는지 확인한다. LLM·DB 없음."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from parser_bridge import process_file_no_regex_reextraction  # noqa: E402


def _write_md(tmp_path, name="공고_기관.md"):
    p = tmp_path / name
    p.write_text(
        "---\ntitle: 공고_기관.hwpx\n---\n\n## 1. 개요\n\n사업명: 테스트 사업\n\n## 2. 금액\n\n기초금액: 1,000원\n",
        encoding="utf-8",
    )
    return p


def test_first_chunk_carries_title_block_and_others_do_not(tmp_path):
    chunks = process_file_no_regex_reextraction(_write_md(tmp_path))
    assert len(chunks) >= 2
    first = chunks[0]["page_content"]
    assert first.startswith('---\ndocument_title: "공고_기관"\nsource_file: "공고_기관.hwpx"\n---\n')
    assert "사업명: 테스트 사업" in first
    assert all("document_title:" not in c["page_content"] for c in chunks[1:])


def test_chunk_size_counts_the_title_block(tmp_path):
    first = process_file_no_regex_reextraction(_write_md(tmp_path))[0]
    assert first["metadata"]["chunk_size"] == len(first["page_content"])


def test_source_file_falls_back_to_the_md_file_name(tmp_path):
    p = tmp_path / "이름만.md"
    p.write_text("## 1. 개요\n\n내용\n", encoding="utf-8")
    first = process_file_no_regex_reextraction(p)[0]["page_content"]
    assert 'source_file: "이름만.md"' in first
