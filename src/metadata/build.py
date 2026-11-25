"""나라장터 입찰공고목록 엑셀로 `data_index/metadata.csv`를 만든다.

원칙: 엑셀의 값은 버리지 않고, 엑셀에 없는 열만 문서에서 채운다(채우는 일은 다른 모듈이 한다).
열 순서는 엑셀을 따른다. `게시일시(입찰마감일시)` 한 열만 `게시일시`, `입찰마감일시` 두 열로 나눈다.
"""

from __future__ import annotations

import csv
import re
import unicodedata
from pathlib import Path

from src.utils.bid_list_xlsx import read_bid_list_rows

COMBINED_DATE = "게시일시(입찰마감일시)"
POSTED, DEADLINE, AMOUNT, SUMMARY, FILE_NAME = "게시일시", "입찰마감일시", "사업 금액", "사업 요약", "파일명"
AMOUNT_EVIDENCE, DEADLINE_EVIDENCE = f"{AMOUNT} 근거", f"{DEADLINE} 근거"
_TITLE_COLUMN = "공고명"
# PDF는 `step1_parsed_`(로더 출력)와 `step2_audited_`(검수 뒤, DB가 실제로 읽는 것)가 둘 다 생긴다.
# 문서로 보는 것은 `step2_audited_`뿐이고, 매칭할 때만 접두사를 뗀다.
_PDF_PREFIX = "step2_audited_"
_PDF_INTERMEDIATE = "step1_parsed_"
_DATE_PARTS = re.compile(r"^\s*(?P<posted>[^()]*?)\s*(?:\((?P<deadline>[^()]*)\))?\s*$")


class MetadataError(Exception):
    """엑셀과 문서가 맞지 않을 때(매칭 안 되는 행, 주인 없는 파일)."""


def split_dates(value: str) -> tuple[str, str]:
    """`2026/08/09 17:26(2026/08/14 10:00)` → (게시일시, 입찰마감일시). 마감이 `-`이거나 없으면 빈 값."""
    m = _DATE_PARTS.match(value or "")
    if not m:
        return (value or "").strip(), ""
    deadline = (m.group("deadline") or "").strip()
    return m.group("posted").strip(), "" if deadline in {"", "-"} else deadline


def _stem(path: Path) -> str:
    stem = unicodedata.normalize("NFC", path.stem)
    return stem[len(_PDF_PREFIX):] if stem.startswith(_PDF_PREFIX) else stem


def _key(text: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFC", text))


def _find_file(title: str, keyed: list[tuple[str, Path]]) -> Path | None:
    prefix = _key(title) + "_"
    hits = [p for key, p in keyed if key.startswith(prefix)]
    return min(hits, key=lambda p: len(_stem(p))) if hits else None


def _output_header(excel_header: list[str]) -> list[str]:
    header: list[str] = []
    for col in excel_header:
        if col == COMBINED_DATE:
            header += [POSTED, DEADLINE]
        elif col not in header:
            header.append(col)
    if DEADLINE not in header:
        header.append(DEADLINE)
    if AMOUNT not in header:
        header.append(AMOUNT)
    return header + [SUMMARY, FILE_NAME, AMOUNT_EVIDENCE, DEADLINE_EVIDENCE]


def build_metadata_rows(
    xlsx_path: Path | str, markdown_dir: Path | str | list[Path | str], allow_unmatched: bool = False
) -> tuple[list[str], list[dict[str, str]]]:
    excel_rows = read_bid_list_rows(xlsx_path)
    if not excel_rows:
        raise MetadataError(f"엑셀에서 행을 읽지 못했다: {xlsx_path}")
    header = _output_header(list(excel_rows[0].keys()))

    dirs = markdown_dir if isinstance(markdown_dir, (list, tuple)) else [markdown_dir]
    files = sorted(
        p for d in dirs for p in Path(d).glob("*.md")
        if not unicodedata.normalize("NFC", p.name).startswith(_PDF_INTERMEDIATE)
    )
    keyed = [(_key(_stem(p)) + "_", p) for p in files]

    rows: list[dict[str, str]] = []
    used: set[Path] = set()
    unmatched: list[str] = []
    for raw in excel_rows:
        row = {col: "" for col in header}
        for col, value in raw.items():
            if col == COMBINED_DATE:
                row[POSTED], row[DEADLINE] = split_dates(value)
            else:
                row[col] = value
        match = _find_file(raw.get(_TITLE_COLUMN, ""), keyed) if raw.get(_TITLE_COLUMN) else None
        if match is None:
            unmatched.append(raw.get(_TITLE_COLUMN, "") or "(공고명 없음)")
        else:
            used.add(match)
            row[FILE_NAME] = match.name
        rows.append(row)

    orphans = [p.name for p in files if p not in used]
    if (unmatched or orphans) and not allow_unmatched:
        lines = []
        if unmatched:
            lines.append("문서를 찾지 못한 엑셀 행:\n  - " + "\n  - ".join(unmatched))
        if orphans:
            lines.append("엑셀 행과 이어지지 않은 문서:\n  - " + "\n  - ".join(orphans))
        raise MetadataError("\n".join(lines))
    return header, rows


def require_metadata(csv_path: Path | str, dictionary_path: Path | str) -> None:
    """DB 구축 단계가 시작하기 전에 부른다. 메타데이터 CSV와 기관명 사전이 없으면 멈춘다."""
    missing = [str(p) for p in (csv_path, dictionary_path) if not Path(p).is_file()]
    if missing:
        raise MetadataError(
            "메타데이터 단계가 먼저 필요하다. 없는 파일: " + ", ".join(missing)
            + "\n  1) python scripts/build_index_new_parser.py --input <폴더> --parse-only (PDF는 index_pdf_originals.py --parse-only)"
            + "\n  2) python scripts/build_metadata.py --markdown-dir output/new_parser_md output"
        )


def filled_count(csv_path: Path | str) -> int:
    """이미 Claude가 채운 값(`<열> 근거`가 적힌 칸)의 수. CSV가 없으면 0."""
    path = Path(csv_path)
    if not path.is_file():
        return 0
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    return sum(1 for r in rows for k, v in r.items() if k.endswith(" 근거") and (v or "").strip())


def write_metadata_csv(header: list[str], rows: list[dict[str, str]], out_csv: Path | str) -> Path:
    out = Path(out_csv)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=header)
        writer.writeheader()
        writer.writerows(rows)
    return out
