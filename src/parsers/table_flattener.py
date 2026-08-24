"""마크다운 테이블 → 자연어 텍스트 변환 모듈.

PDF 파서가 생성하는 마크다운 테이블(|Col1|Col2|...)을 자연어 형태로
평탄화하여 임베딩 유사도를 높인다.

Before: |사업명|차세대 포털|\n|---|---|\n|사업기간|24개월|
After:  사업명: 차세대 포털\n사업기간: 24개월
"""

from __future__ import annotations

import re

# 마크다운 테이블 행: | 로 시작하고 | 로 끝남
_TABLE_ROW_RE = re.compile(r"^\|.+\|$")
# 구분선: |---|---| 또는 |:---|:---| 등
_TABLE_SEP_RE = re.compile(r"^\|[-:\s|]+\|$")
# 플레이스홀더 헤더: Col1, Col2, Column1, ... 등
_PLACEHOLDER_HEADER_RE = re.compile(r"^(Col(umn)?\s*\d+)$", re.IGNORECASE)
# 한국어 일반 KV 헤더: "항목/내용", "구분/설명" 등 → 의미 없는 열 제목
_GENERIC_KV_HEADERS = {"항목", "내용", "구분", "설명", "비고", "분류", "세부내용"}
# <br> 태그
_BR_TAG_RE = re.compile(r"<br\s*/?>", re.IGNORECASE)


def _parse_cells(row: str) -> list[str]:
    """테이블 행에서 셀 값을 파싱한다."""
    # 양 끝 | 제거 후 | 로 분할
    inner = row.strip().strip("|")
    cells = [_BR_TAG_RE.sub(" ", c).strip() for c in inner.split("|")]
    return cells


def _is_separator_row(row: str) -> bool:
    """구분선 행인지 판별한다."""
    return bool(_TABLE_SEP_RE.match(row.strip()))


def _is_placeholder_header(headers: list[str]) -> bool:
    """헤더가 Col1/Col2 같은 플레이스홀더인지 판별한다."""
    return all(_PLACEHOLDER_HEADER_RE.match(h) for h in headers if h)


def _is_key_value_table(headers: list[str]) -> bool:
    """2열 key-value 테이블인지 판별한다."""
    return len(headers) == 2


# 순수 숫자/금액/기호로만 이루어진 셀 — 라벨이 아니라 값으로 본다("368,467,000",
# "-", "334,970,000" 등). 컬럼당 표본이 적을 때(예: 남은 데이터 행이 1개뿐인
# 경우) 우연히 "라벨과 다른 값 하나"만으로 반복 그리드로 오판하는 걸 막는다.
_LOOKS_LIKE_VALUE_RE = re.compile(r"^[\-\d,.:%()원억만천\s]+$")


def _looks_like_repeating_kv_grid(headers: list[str], data_rows: list[list[str]]) -> bool:
    """헤더가 없는 "라벨|값|라벨|값" 반복 그리드인지 판별한다.

    GFM 마크다운은 헤더+구분선 행을 강제하는데, 원본 HWP 표가 애초에 헤더 없이
    "라벨: 값"을 나열만 하는 표면(hwp2md가 이런 표도 만든다), 어쩔 수 없이 첫
    데이터 행이 헤더 자리에 찍힌다. 이런 표는 짝수 컬럼(0, 2, ...) 자리에 오는
    문자열이 행마다 계속 달라진다 — 진짜 헤더 열이라면 같은 자리에 고정된
    카테고리명(예: "품명", "규격")이 반복돼야 하는데, 값 자체가 행마다 다르다는
    건 그 컬럼이 고정 카테고리가 아니라 가변 필드명이라는 뜻이다.

    단, 표본이 3개 미만인 컬럼(대개 표의 "두 번째 라벨:값 쌍" 자리처럼 일부
    행만 채워진 보조 열)은 판단 근거로 안 쓴다 — 첫 번째 라벨열(항상 채워짐)
    하나만으로도 충분히 신뢰할 수 있고, 표본이 적은 보조 열까지 강제로 통과
    시키면 "데이터 행이 1개뿐이라 라벨과 값이 우연히 다름"만으로 오탐하기
    쉽다(실측: 헤더 복제 행 제거 후 데이터 1행만 남는 표에서 발생).

    또한, 헤더 행의 "값 자리"(홀수 인덱스: 헤더가 첫 데이터 행이라면 그 자리에
    와야 할 실제 값)가 전부 "수량"/"단가(원)"처럼 짧은 일반 열 제목처럼 보이면
    반복 그리드로 보지 않는다 — 진짜 2단 헤더 표(예: "시설명|수량|시설명|수량"
    처럼 품목을 2개씩 나란히 나열하는 표)에서, 데이터 행의 품목명(미단뜨기
    미싱/오버로크 등)이 우연히 서로 다 다르다는 이유만으로 "라벨이 행마다
    바뀐다"고 오판하는 걸 막는다(실측 확인). 반대로 진짜 헤더 없는 KV 표라면
    첫 데이터 행이 헤더 자리에 찍힌 것이므로 그 값 자리에는 사업명처럼 구체적이고
    긴 실제 값이 온다.
    """
    if len(headers) < 4 or len(headers) % 2 != 0:
        return False
    value_slot_cells = [headers[i] for i in range(1, len(headers), 2) if i < len(headers) and headers[i]]
    if not value_slot_cells or all(len(v) <= 8 for v in value_slot_cells):
        return False
    all_rows = [headers, *data_rows]
    checked_any = False
    for idx in range(0, len(headers), 2):
        values_at_col = [row[idx] for row in all_rows if idx < len(row) and row[idx]]
        if len(values_at_col) < 3:
            continue
        checked_any = True
        if any(_LOOKS_LIKE_VALUE_RE.match(v) for v in values_at_col):
            return False
        if len(set(values_at_col)) < len(values_at_col) * 0.6:
            return False
    return checked_any


def flatten_table(table_text: str) -> str:
    """마크다운 테이블을 자연어 텍스트로 변환한다.

    - 2열 key-value 테이블: "key: value" 형식
    - 다열 테이블: "header1: val1, header2: val2" (행별)
    - 플레이스홀더 헤더(Col1/Col2): 헤더 없이 값만 출력
    - 테이블 앞 텍스트(섹션 제목 등)는 보존

    Args:
        table_text: 마크다운 테이블 텍스트 (앞에 섹션 제목 포함 가능).

    Returns:
        자연어로 변환된 텍스트.
    """
    lines = table_text.split("\n")

    # 테이블 앞의 비테이블 텍스트(섹션 제목 등)를 분리
    prefix_lines: list[str] = []
    table_lines: list[str] = []
    in_table = False

    for line in lines:
        stripped = line.strip()
        if _TABLE_ROW_RE.match(stripped):
            in_table = True
            table_lines.append(stripped)
        elif in_table:
            # 테이블 중간에 빈 줄이 나오면 테이블 끝으로 간주
            if stripped:
                table_lines.append(stripped)
            else:
                table_lines.append("")
        else:
            prefix_lines.append(line)

    if not table_lines:
        return table_text

    # 헤더/구분선/데이터 행 분리
    headers: list[str] = []
    data_rows: list[list[str]] = []

    for i, line in enumerate(table_lines):
        if not line.strip():
            continue
        if _is_separator_row(line):
            continue
        cells = _parse_cells(line)
        if i == 0 and not headers:
            headers = cells
        else:
            data_rows.append(cells)

    # 헤더만 있고 데이터 행이 없으면 원본 반환
    if not data_rows:
        return table_text

    placeholder = _is_placeholder_header(headers)
    kv_table = _is_key_value_table(headers) and not placeholder
    repeating_kv_grid = (
        not kv_table and not placeholder and _looks_like_repeating_kv_grid(headers, data_rows)
    )

    # KV 테이블에서는 헤더 행도 데이터 — 단, 일반적 열 제목은 제외
    if kv_table:
        header_vals = {h.strip() for h in headers if h.strip()}
        if not header_vals.issubset(_GENERIC_KV_HEADERS):
            data_rows.insert(0, headers)
    elif repeating_kv_grid:
        # 이 표는 애초에 헤더가 없고 첫 데이터 행이 GFM 문법 때문에 어쩔 수 없이
        # 헤더 자리에 찍힌 것이므로, 헤더 행도 그대로 데이터로 취급한다.
        data_rows.insert(0, headers)

    result_lines: list[str] = []

    # 접두사 텍스트 보존
    prefix = "\n".join(prefix_lines).strip()
    if prefix:
        result_lines.append(prefix)

    if kv_table:
        # 2열 key-value: 각 행의 첫 셀을 key, 두 번째를 value로
        for row in data_rows:
            key = row[0] if len(row) > 0 else ""
            val = row[1] if len(row) > 1 else ""
            if key and val:
                result_lines.append(f"{key}: {val}")
            elif key:
                result_lines.append(key)
            elif val:
                result_lines.append(val)
    elif repeating_kv_grid:
        # 라벨:값이 반복되는 그리드 — 컬럼 인덱스(짝수=라벨/홀수=값)를 고정
        # 신뢰하지 않는다. HWP 병합 셀이 마크다운으로 복원될 때 값 칸이 한 칸
        # 밀려 빈 칸이 끼는 경우(예: |c| |c'| |, 원래는 한 쌍인데 두 번째 자리로
        # 밀림)가 있어서, 컬럼 위치가 아니라 "실제 값이 있는 칸"만 왼쪽부터
        # 순서대로 모아 (1,2)/(3,4)... 로 순차 페어링한다.
        for row in data_rows:
            non_empty = [v for v in row if v]
            pairs: list[str] = []
            it = iter(non_empty)
            for label in it:
                val = next(it, None)
                pairs.append(f"{label}: {val}" if val is not None else label)
            if pairs:
                result_lines.append(", ".join(pairs))
    elif placeholder:
        # 플레이스홀더 헤더: 값만 콤마로 연결
        for row in data_rows:
            values = [v for v in row if v]
            if values:
                result_lines.append(", ".join(values))
    else:
        # 다열 테이블: "header: value" 쌍을 콤마로 연결.
        # 원본 HWP 표가 2행짜리 헤더(대분류+소분류)일 때, hwp2md가 소분류 행을
        # 헤더 다음에 데이터처럼 한 번 더 찍어내는 경우가 있다 — 그 소분류 행은
        # 일부(또는 전부) 칸이 자기 컬럼의 헤더 라벨과 완전히 같은 문자열을
        # 그대로 반복한다. 행 전체가 헤더와 동일한지가 아니라(부분만 겹치는
        # 경우가 실제로 있음 — 실측 확인) 칸 단위로, 값이 자기 컬럼 헤더와
        # 같으면 그 칸만 "라벨: 라벨" 형태로 찍히지 않도록 건너뛴다.
        for row in data_rows:
            pairs: list[str] = []
            for j, val in enumerate(row):
                if not val:
                    continue
                header_j = headers[j] if j < len(headers) else ""
                if header_j and val == header_j:
                    continue
                if header_j:
                    pairs.append(f"{header_j}: {val}")
                else:
                    pairs.append(val)
            if pairs:
                result_lines.append(", ".join(pairs))

    return "\n".join(result_lines)


def flatten_tables_in_text(text: str) -> str:
    """텍스트 내 모든 마크다운 테이블을 찾아서 평탄화한다.

    테이블 블록(연속된 |..| 행)을 감지하여 flatten_table()로 변환하고,
    일반 텍스트는 그대로 보존한다.

    Args:
        text: 마크다운 테이블이 포함된 전체 텍스트.

    Returns:
        모든 테이블이 자연어로 변환된 텍스트.
    """
    lines = text.split("\n")
    result_parts: list[str] = []
    table_block: list[str] = []
    # 테이블 직전의 비테이블 텍스트(제목 등) — 짧으면 테이블에 병합
    pending_prefix: list[str] = []

    def _flush_table():
        """누적된 테이블 블록을 평탄화하여 결과에 추가."""
        if not table_block:
            if pending_prefix:
                result_parts.extend(pending_prefix)
                pending_prefix.clear()
            return

        # pending_prefix를 테이블 앞에 붙여서 평탄화
        full_block = "\n".join(pending_prefix + table_block)
        pending_prefix.clear()
        flattened = flatten_table(full_block)
        result_parts.append(flattened)
        table_block.clear()

    for line in lines:
        stripped = line.strip()
        is_table_line = bool(_TABLE_ROW_RE.match(stripped))

        if is_table_line:
            table_block.append(line)
        else:
            if table_block:
                # 테이블 블록이 끝남
                _flush_table()
                result_parts.append(line)
            else:
                # 아직 테이블 시작 전 — 짧은 라인은 다음 테이블의 접두사 후보
                if stripped and len(stripped) < 80:
                    pending_prefix.append(line)
                else:
                    if pending_prefix:
                        result_parts.extend(pending_prefix)
                        pending_prefix.clear()
                    result_parts.append(line)

    # 마지막에 남은 블록 처리
    if table_block:
        _flush_table()
    if pending_prefix:
        result_parts.extend(pending_prefix)

    return "\n".join(result_parts)
