"""나라장터 입찰공고 엑셀(`입찰공고목록_*.xlsx` 등)을 읽는 어댑터.

두 가지 스키마를 지원한다:
- 입찰공고목록: 상단 안내 줄 뒤에 헤더(`공고명/공고기관/수요기관/입찰공고번호/게시일시…`)가 있는 형식
- 나라장터_RFP_메타데이터: 첫 줄이 헤더(`사업명/발주 기관/파일명`)인 형식

실험(experiments/)에서 같은 엑셀 한 파일을 팀 버전과 현재 버전에 똑같이 입력하기 위해,
현재 버전은 라벨 목록(`load_bid_list_labels`)으로, 팀 버전은 자기 스키마의 CSV
(`bid_list_to_team_csv`)로 변환해 쓴다.
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


def _nfc_key(text: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFC", text))


def bid_list_to_team_csv(xlsx_path: Path | str, corpus_dir: Path | str, out_csv: Path | str) -> dict[str, int]:
    """입찰공고목록을 팀 프로젝트가 읽는 `data_list.csv` 스키마로 변환한다.

    엑셀에 없는 `사업 금액/사업 요약/텍스트` 등은 빈 값으로 둔다(없는 정보를 만들어 넣지 않는다).
    `파일명`은 공고명이 코퍼스 파일명(`공고명_기관.확장자`)의 앞부분과 같은 파일로 매칭한다.
    """
    corpus = Path(corpus_dir)
    files = [p for p in corpus.iterdir() if p.suffix.lower() in {".hwp", ".hwpx", ".pdf"}]
    # 공고명 자체에 "_"가 들어 있는 경우가 있어(예: "무공해차 충전인프라 보급 사업_14_아산여객_공사")
    # 파일명 첫 "_" 앞만 비교하지 않고 `공고명 + "_"` 접두사로 매칭한다.
    keyed = [(_nfc_key(p.stem) + "_", p) for p in files]

    def _find_file(title: str) -> Path | None:
        prefix = _nfc_key(title) + "_"
        hits = [p for key, p in keyed if key.startswith(prefix)]
        return min(hits, key=lambda p: len(p.stem)) if hits else None

    fieldnames = [
        "공고 번호", "공고 차수", "사업명", "사업 금액", "발주 기관", "공개 일자",
        "입찰 참여 시작일", "입찰 참여 마감일", "사업 요약", "파일형식", "파일명", "텍스트",
    ]
    rows = read_bid_list_rows(xlsx_path)
    matched = 0
    out_rows: list[dict[str, str]] = []
    for row in rows:
        title = row.get("공고명") or row.get("사업명", "")
        org = row.get("수요기관") or row.get("공고기관") or row.get("발주 기관", "")
        number = row.get("입찰공고번호", "")
        base_number, _, round_no = number.partition("-")
        match = _find_file(title) if title else None
        if match:
            matched += 1
        posted = row.get("게시일시(입찰마감일시)", "")
        out_rows.append({
            "공고 번호": base_number or number,
            "공고 차수": round_no,
            "사업명": title,
            "사업 금액": "",
            "발주 기관": org,
            "공개 일자": posted.split("(")[0].strip(),
            "입찰 참여 시작일": "",
            "입찰 참여 마감일": "",
            "사업 요약": "",
            "파일형식": match.suffix.lstrip(".").lower() if match else "",
            "파일명": match.name if match else "",
            "텍스트": "",
        })

    out = Path(out_csv)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(out_rows)
    return {"rows": len(rows), "matched": matched}
