"""두 가지 청킹 전략을 같은 인터페이스로 제공한다 — 비교가 목적이므로 둘 다 `list[Chunk]`를
반환하고, 차이는 오직 "헤더 구조를 보는지 여부"에만 있다.

- `chunk_hierarchical`: `#`/`##`/`###` 헤더 경계로 먼저 나누고, 각 조각에 조상 헤더 전체를
  이어붙인 `section_path`를 메타데이터로 붙인다. 한 섹션이 너무 크면(`max_chars` 초과) 그 섹션
  내부에서만 고정 크기로 추가 분할한다(`section_path`는 유지).
- `chunk_flat`: 헤더를 완전히 무시하고 문서 전체를 고정 크기+오버랩으로 자른다 — "구조 정보가
  없는 마크다운"을 흉내내는 베이스라인.

두 전략이 정확히 같은 문서에서 같은 `max_chars`/`overlap` 파라미터로 도는 것이 비교의 전제다."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_HEADER_RE = re.compile(r"^(#{1,6})\s+(.+)$")


@dataclass
class Chunk:
    text: str
    section_path: str  # hierarchical: "1. 입찰에 부치는 사항 > 가. 공고명" / flat: ""
    chunk_index: int
    metadata: dict = field(default_factory=dict)


def _split_fixed(text: str, max_chars: int, overlap: int) -> list[str]:
    """단순 고정 크기+오버랩 분할. 문단(빈 줄) 경계에서 최대한 자르되, 한 문단이 너무 길면
    글자 수로 강제 분할한다."""
    if len(text) <= max_chars:
        return [text] if text.strip() else []

    paragraphs = re.split(r"\n\s*\n", text)
    pieces: list[str] = []
    current = ""
    for p in paragraphs:
        candidate = f"{current}\n\n{p}" if current else p
        if len(candidate) <= max_chars:
            current = candidate
            continue
        if current:
            pieces.append(current)
        if len(p) <= max_chars:
            current = p
        else:
            # 한 문단 자체가 상한을 넘으면 글자 수로 강제 분할
            for i in range(0, len(p), max_chars - overlap):
                pieces.append(p[i : i + max_chars])
            current = ""
    if current:
        pieces.append(current)

    # 오버랩 적용: 각 조각 앞에 이전 조각의 꼬리를 덧붙인다
    overlapped = []
    for i, piece in enumerate(pieces):
        if i == 0 or overlap <= 0:
            overlapped.append(piece)
        else:
            tail = pieces[i - 1][-overlap:]
            overlapped.append(f"{tail}\n{piece}")
    return overlapped


def chunk_flat(text: str, max_chars: int = 1000, overlap: int = 200) -> list[Chunk]:
    pieces = _split_fixed(text, max_chars, overlap)
    return [Chunk(text=p, section_path="", chunk_index=i) for i, p in enumerate(pieces)]


def chunk_hierarchical(text: str, max_chars: int = 1000, overlap: int = 200) -> list[Chunk]:
    lines = text.split("\n")

    # (level, title) 스택 기반으로 각 줄이 속한 섹션의 조상 경로를 구성한다.
    sections: list[tuple[str, list[str]]] = []  # (body_text, section_path_parts)
    stack: list[tuple[int, str]] = []  # (level, title)
    body_lines: list[str] = []

    def flush():
        if body_lines and any(line.strip() for line in body_lines):
            path_parts = [title for _, title in stack]
            sections.append(("\n".join(body_lines).strip(), path_parts))
        body_lines.clear()

    for line in lines:
        m = _HEADER_RE.match(line.strip())
        if m:
            flush()
            level = len(m.group(1))
            title = m.group(2).strip()
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, title))
            body_lines.append(line)  # 헤더 자체도 그 섹션의 본문에 포함(문맥 보존)
        else:
            body_lines.append(line)
    flush()

    chunks: list[Chunk] = []
    idx = 0
    for body, path_parts in sections:
        section_path = " > ".join(path_parts)
        for piece in _split_fixed(body, max_chars, overlap):
            chunks.append(Chunk(text=piece, section_path=section_path, chunk_index=idx))
            idx += 1
    return chunks
