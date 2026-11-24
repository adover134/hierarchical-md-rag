"""`metadata.csv`의 한 행을 질의 쪽 CSV 로더(`CSVMarkdownConverter`)가 읽는 열 이름으로 바꾼다.

질의 쪽 로더는 팀 프로젝트의 `data_list.csv` 열 이름(`사업명`, `발주 기관`, `공개 일자` …)을 기대한다.
`metadata.csv`는 엑셀의 열 이름(`공고명`, `수요기관`, `게시일시` …)을 그대로 쓰므로, 읽을 때만 이름을 맞춘다. 값은 바꾸지 않는다.
"""

from __future__ import annotations

_AGENCY_COLUMNS = ("수요기관", "공고기관", "발주 기관")


def is_metadata_row(row: dict[str, str]) -> bool:
    return "공고명" in row and "입찰공고번호" in row


def to_team_row(row: dict[str, str]) -> dict[str, str]:
    number = row.get("입찰공고번호", "")
    base, _, round_no = number.partition("-")
    return {
        "공고 번호": base or number,
        "공고 차수": round_no,
        "사업명": row.get("공고명", ""),
        "사업 금액": row.get("사업 금액", ""),
        "발주 기관": next((row[c] for c in _AGENCY_COLUMNS if row.get(c)), ""),
        "공개 일자": row.get("게시일시", ""),
        "입찰 참여 시작일": "",
        "입찰 참여 마감일": row.get("입찰마감일시", ""),
        "사업 요약": row.get("사업 요약", ""),
        "파일형식": "",
        "파일명": row.get("파일명", ""),
        "텍스트": "",
    }
