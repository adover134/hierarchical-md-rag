"""나라장터 입찰공고 엑셀(`입찰공고목록_*.xlsx` 등)을 읽는 어댑터.

두 가지 스키마를 지원한다:
- 입찰공고목록: 상단 안내 줄 뒤에 헤더(`공고명/공고기관/수요기관/입찰공고번호/게시일시…`)가 있는 형식
- 나라장터_RFP_메타데이터: 첫 줄이 헤더(`사업명/발주 기관/파일명`)인 형식

실험(experiments/)에서 같은 엑셀 한 파일을 팀 버전과 현재 버전에 똑같이 입력하기 위해,
현재 버전은 라벨 목록(`load_bid_list_labels`)으로, 팀 버전은 자기 스키마의 CSV
(`src/evaluation/team_csv.py`의 `bid_list_to_team_csv`)로 변환해 쓴다.
"""

from __future__ import annotations

import csv
import re
import unicodedata
from pathlib import Path

_HEADER_MARKERS = ("공고명", "사업명")
_TITLE_COLUMNS = ("공고명", "사업명")
_ORG_COLUMNS = ("수요기관", "공고기관", "발주 기관")


def _cell(value: object) -> str:
    return "" if value is None else str(value).strip()


def read_bid_list_rows(xlsx_path: Path | str) -> list[dict[str, str]]:
    """헤더 행을 자동으로 찾아 이후 행을 {컬럼명: 값} 리스트로 돌려준다(빈 행 제외)."""
    import openpyxl

    wb = openpyxl.load_workbook(xlsx_path, read_only=True, data_only=True)
    try:
        grid = [[_cell(c) for c in row] for row in wb.worksheets[0].iter_rows(values_only=True)]
    finally:
        wb.close()

    header_idx = next(
        (i for i, row in enumerate(grid) if any(cell in _HEADER_MARKERS for cell in row)), None
    )
    if header_idx is None:
        return []
    header = grid[header_idx]
    rows: list[dict[str, str]] = []
    for raw in grid[header_idx + 1:]:
        if not any(raw):
            continue
        rows.append({header[i]: raw[i] for i in range(min(len(header), len(raw))) if header[i]})
    return rows


def load_bid_list_labels(xlsx_path: Path | str) -> list[str]:
    """문서 존재 판정에 쓸 라벨(사업명/공고명, 기관명, 파일명) 목록."""
    labels: list[str] = []
    for row in read_bid_list_rows(xlsx_path):
        for col in (*_TITLE_COLUMNS, "공고기관", "수요기관", "발주 기관", "파일명"):
            value = row.get(col, "")
            if value:
                labels.append(value)
    return labels
