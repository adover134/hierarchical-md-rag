"""평가 전용: 입찰공고목록 엑셀을 팀 프로젝트가 읽는 `data_list.csv` 스키마로 바꾼다.

서비스 경로(메타데이터 단계, `src/metadata/`)와 무관하다. 실험에서 같은 엑셀 한 파일을 팀 버전에도 똑같이 넣으려는 용도다.
"""

from __future__ import annotations

import csv
import re
import unicodedata
from pathlib import Path

from src.metadata.build import split_dates
from src.utils.bid_list_xlsx import read_bid_list_rows


def _nfc_key(text: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFC", text))


def bid_list_to_team_csv(xlsx_path: Path | str, corpus_dir: Path | str, out_csv: Path | str) -> dict[str, int]:
    """입찰공고목록을 팀 프로젝트가 읽는 `data_list.csv` 스키마로 변환한다.

    `사업 금액`은 엑셀에 같은 이름의 열이 있으면 그 값을 쓰고, 없으면 빈 값으로 둔다.
    입찰마감일시는 엑셀의 괄호 안 값을 `입찰 참여 마감일`에 넣는다(`-`이면 빈 값).
    엑셀에 없는 `사업 요약/텍스트` 등도 빈 값으로 둔다(없는 정보를 만들어 넣지 않는다).
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
        posted, deadline = split_dates(row.get("게시일시(입찰마감일시)", ""))
        out_rows.append({
            "공고 번호": base_number or number,
            "공고 차수": round_no,
            "사업명": title,
            "사업 금액": row.get("사업 금액", ""),
            "발주 기관": org,
            "공개 일자": posted,
            "입찰 참여 시작일": "",
            "입찰 참여 마감일": deadline,
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
