"""KPI 계산 함수.

검색 품질 메트릭을 계산한다:
- Top-k Hit Position
- Empty Retrieval Rate
- Recall@K
- MRR

답변 품질(정확성/충실성 등)은 `llm_judge.py`의 LLM-as-Judge가 담당한다 — 여기서는
검색 결과 자체의 정확도만 다룬다.
"""

from __future__ import annotations

import unicodedata
from pathlib import Path


_CONVERTED_DOC_EXTS = {"hwp", "hwpx", "pdf"}


def _normalize_source_name(source: str | None) -> str:
    """source 문자열을 비교 가능한 형태로 정규화한다.

    - Unicode NFC 정규화
    - 앞뒤 공백 제거
    - 파일명 기준 비교를 위해 basename 추출
    - 기본은 확장자 포함 exact 매칭
    """
    if not source:
        return ""
    normalized = unicodedata.normalize("NFC", str(source)).strip()
    normalized = Path(normalized).name
    return normalized.lower()


def _split_source_parts(source: str | None) -> tuple[str, str, str]:
    """정규화된 source를 (name, stem, ext)로 분해한다."""
    normalized = _normalize_source_name(source)
    if not normalized:
        return "", "", ""
    parsed = Path(normalized)
    ext = parsed.suffix.lower().lstrip(".")
    return normalized, parsed.stem.lower(), ext


def _normalize_stem_for_equivalence(stem: str) -> str:
    """파일 stem 비교를 위한 추가 정규화(구두점/공백 차이 무시)."""
    if not stem:
        return ""
    normalized = unicodedata.normalize("NFKC", stem.lower())
    return "".join(ch for ch in normalized if ch.isalnum())


def _is_equivalent_source_name(a: str | None, b: str | None) -> bool:
    """두 source 문자열이 동일 문서를 가리키는지 판정한다.

    규칙:
    - exact filename 일치면 동일
    - stem이 같고 확장자가 hwp/hwpx/pdf 변환군 내이면 동일
    - 한쪽이 확장자 없는 stem이어도 stem이 같으면 동일로 본다.
    """
    a_name, a_stem, a_ext = _split_source_parts(a)
    b_name, b_stem, b_ext = _split_source_parts(b)
    if not a_name or not b_name:
        return False
    if a_name == b_name:
        return True

    def _stem_match() -> bool:
        return _normalize_stem_for_equivalence(a_stem) == _normalize_stem_for_equivalence(b_stem)

    if _stem_match():
        # DB source를 확장자 없이 저장하는 모드 지원
        if not a_ext or not b_ext:
            return True
        if a_ext in _CONVERTED_DOC_EXTS and b_ext in _CONVERTED_DOC_EXTS:
            return True

    return False


def _normalize_ground_truth_sources(
    ground_truth_source: str | list[str] | tuple[str, ...] | set[str],
) -> list[str]:
    """ground truth source 입력을 정규화된 리스트로 변환한다."""
    if isinstance(ground_truth_source, str):
        values = [ground_truth_source]
    else:
        values = list(ground_truth_source)

    return [
        _normalize_source_name(v)
        for v in values
        if _normalize_source_name(v)
    ]


def _is_source_match(
    retrieved_source: str | None,
    ground_truth_sources: list[str],
) -> bool:
    """retrieved source가 정답 source 집합과 일치하는지 판정한다."""
    for gt_source in ground_truth_sources:
        if _is_equivalent_source_name(retrieved_source, gt_source):
            return True
    return False


def calculate_hit_position(
    retrieved_docs: list[dict],
    ground_truth_source: str | list[str] | tuple[str, ...] | set[str],
    ground_truth_page: int | None = None,
) -> int | None:
    """정답 문서가 검색 결과에서 몇 번째에 위치하는지 반환한다.

    단일 source: 첫 번째 일치 위치를 반환한다.
    다중 source (strict): 모든 source가 발견된 경우, 마지막으로 발견된 source의
        위치를 반환한다 (= 모든 정답을 포함하기 위해 필요한 최소 rank).
        하나라도 누락이면 None.

    Args:
        retrieved_docs: 검색된 문서 리스트 (RetrievedDoc 딕셔너리).
        ground_truth_source: 정답 문서 source 값(단일 문자열 또는 리스트).
        ground_truth_page: 정답 페이지. 지정 시 source + page 모두 일치해야 hit.

    Returns:
        1-based 위치. 없으면 None.
    """
    gt_sources = _normalize_ground_truth_sources(ground_truth_source)
    if not gt_sources:
        return None

    if len(gt_sources) == 1:
        for idx, doc in enumerate(retrieved_docs, start=1):
            if not _is_source_match(doc.get("source"), gt_sources):
                continue
            if ground_truth_page is not None and doc.get("page") != ground_truth_page:
                continue
            return idx
        return None

    # Multi-source strict: 모든 GT source의 첫 출현 위치 수집 → max 반환
    # 하나라도 미발견이면 None
    found_at: dict[str, int] = {}
    for idx, doc in enumerate(retrieved_docs, start=1):
        retrieved_source = doc.get("source")
        for gt_source in gt_sources:
            if gt_source in found_at:
                continue
            if _is_equivalent_source_name(retrieved_source, gt_source):
                found_at[gt_source] = idx
        if len(found_at) == len(gt_sources):
            return max(found_at.values())
    return None  # 하나 이상 미발견


def calculate_empty_retrieval_rate(
    query_results: list[list[dict]],
) -> float:
    """전체 질의 중 검색 결과가 비어있는 비율.

    Args:
        query_results: 각 질의별 검색 결과 리스트의 리스트.

    Returns:
        0.0 ~ 1.0 사이의 비율.
    """
    if not query_results:
        return 0.0

    empty_count = sum(1 for results in query_results if not results)
    return empty_count / len(query_results)


def calculate_recall_at_k(
    retrieved_docs: list[dict],
    ground_truth_source: str | list[str] | tuple[str, ...] | set[str],
    ground_truth_page: int | None = None,
    k: int = 5,
) -> float:
    """Recall@K — top-K 내에 정답 source가 있으면 1.0, 아니면 0.0.

    - 단일 source: top-K 내 포함 시 1.0
    - 다중 source: top-K 내에 모든 source가 포함되어야 1.0 (strict)
    - page가 지정되면 단일 source 케이스에서 source + page 모두 일치해야 정답으로 판정한다.
    - 단, source 확장자가 hwp/hwpx/pdf 변환군인 경우 stem 동일 시 동일 문서로 간주한다.
    """
    gt_sources = _normalize_ground_truth_sources(ground_truth_source)
    if not gt_sources:
        return 0.0

    top_k_docs = retrieved_docs[:k]

    # 단일 source는 페이지 조건을 지원한다.
    if len(gt_sources) == 1:
        target = gt_sources[0]
        for doc in top_k_docs:
            if not _is_equivalent_source_name(doc.get("source"), target):
                continue
            if ground_truth_page is not None and doc.get("page") != ground_truth_page:
                continue
            return 1.0
        return 0.0

    # 다중 source는 strict match: 모든 GT source가 top-K 내 매칭되어야 hit.
    for gt_source in gt_sources:
        matched = any(_is_equivalent_source_name(doc.get("source"), gt_source) for doc in top_k_docs)
        if not matched:
            return 0.0
    return 1.0


def calculate_recall_at_k_summary(
    query_recalls: list[float],
) -> float:
    """Recall@K (summary) — per-query Recall@K의 평균 (= Hit Rate@K)."""
    if not query_recalls:
        return 0.0
    return sum(1 for r in query_recalls if r > 0) / len(query_recalls)


def _normalize_chunk_label(value: str | int | None) -> str:
    """청크 식별자를 비교 가능한 문자열로 정규화한다."""
    if value is None:
        return ""
    return unicodedata.normalize("NFKC", str(value)).strip().lower()


def _split_chunk_gt_labels(
    ground_truth_chunks: dict | str | int | list[str] | list[int] | tuple[str | int, ...] | set[str | int],
) -> tuple[list[str], list[str]]:
    """GT chunk 라벨을 uid 계열/순번 계열로 분리한다."""
    uid_labels: list[str] = []
    order_labels: list[str] = []

    def _append_label(value: str | int | None, prefer_uid: bool = False) -> None:
        normalized = _normalize_chunk_label(value)
        if not normalized:
            return
        # uid는 보통 "<hash>_<order>" 형태이며, order는 숫자형이 대부분이다.
        if prefer_uid or "_" in normalized or any(ch.isalpha() for ch in normalized):
            uid_labels.append(normalized)
        else:
            order_labels.append(normalized)

    if isinstance(ground_truth_chunks, dict):
        for value in ground_truth_chunks.get("chunk_uids", []) or []:
            _append_label(value, prefer_uid=True)
        for value in ground_truth_chunks.get("chunk_ids", []) or []:
            _append_label(value, prefer_uid=True)
        for value in ground_truth_chunks.get("chunks", []) or []:
            _append_label(value)
        for value in ground_truth_chunks.get("chunk_orders", []) or []:
            _append_label(value, prefer_uid=False)
    else:
        if isinstance(ground_truth_chunks, (str, int)):
            values = [ground_truth_chunks]
        else:
            values = list(ground_truth_chunks or [])
        for value in values:
            _append_label(value)

    # 중복 제거(순서 유지)
    uid_unique = list(dict.fromkeys(uid_labels))
    order_unique = list(dict.fromkeys(order_labels))
    return uid_unique, order_unique


def calculate_recall_at_k_chunk(
    retrieved_docs: list[dict],
    ground_truth_chunks: dict | str | int | list[str] | list[int] | tuple[str | int, ...] | set[str | int],
    k: int = 5,
) -> float | None:
    """Recall@K (chunk) — top-K 내 정답 청크 커버리지.

    반환값:
    - GT chunk 라벨이 없으면 None
    - 있으면 [0,1] 범위 비율 (matched / total_gt_chunks)
    """
    gt_uid_labels, gt_order_labels = _split_chunk_gt_labels(ground_truth_chunks)
    if not gt_uid_labels and not gt_order_labels:
        return None

    top_k_docs = retrieved_docs[:k]
    retrieved_uid_keys: set[str] = set()
    retrieved_order_keys: set[str] = set()
    for doc in top_k_docs:
        if not isinstance(doc, dict):
            continue
        chunk_id = _normalize_chunk_label(doc.get("chunk_id"))
        chunk_index = _normalize_chunk_label(doc.get("chunk_index"))
        if chunk_id:
            retrieved_uid_keys.add(chunk_id)
            # chunk_id가 "hash_12" 형태면 trailing order도 보조키로 추가한다.
            if "_" in chunk_id:
                trailing = chunk_id.rsplit("_", 1)[-1].strip()
                if trailing.isdigit():
                    retrieved_order_keys.add(trailing)
        if chunk_index:
            retrieved_order_keys.add(chunk_index)

    if not retrieved_uid_keys and not retrieved_order_keys:
        return 0.0

    recalls: list[float] = []
    if gt_uid_labels:
        matched_uid = sum(1 for gt in gt_uid_labels if gt in retrieved_uid_keys)
        recalls.append(matched_uid / len(gt_uid_labels))
    if gt_order_labels:
        matched_order = sum(1 for gt in gt_order_labels if gt in retrieved_order_keys)
        recalls.append(matched_order / len(gt_order_labels))

    if not recalls:
        return 0.0
    # uid/order 라벨이 동시에 있을 때는 더 신뢰도 높은 매칭 결과를 채택한다.
    return max(recalls)


def calculate_recall_at_k_chunk_summary(
    query_chunk_recalls: list[float | None],
) -> float | None:
    """Recall@K (chunk) 평균. 청크 라벨이 있는 질의만 평균한다."""
    valid = [r for r in query_chunk_recalls if r is not None]
    if not valid:
        return None
    return sum(valid) / len(valid)


def calculate_mrr(
    hit_positions: list[int | None],
) -> float:
    """Mean Reciprocal Rank — 첫 정답 순위의 역수 평균.

    Args:
        hit_positions: 각 쿼리별 정답의 1-based 위치. None이면 정답 없음.
    """
    if not hit_positions:
        return 0.0
    reciprocals = [1.0 / pos if pos is not None else 0.0 for pos in hit_positions]
    return sum(reciprocals) / len(reciprocals)


def calculate_avg_score(
    retrieved_docs: list[dict],
    ground_truth_source: str | list[str] | tuple[str, ...] | set[str],
    ground_truth_page: int | None = None,
) -> float | None:
    """정답 청크의 평균 유사도 점수를 반환한다. 정답이 없으면 None."""
    gt_sources = _normalize_ground_truth_sources(ground_truth_source)
    if not gt_sources:
        return None

    scores = []
    for doc in retrieved_docs:
        if not _is_source_match(doc.get("source"), gt_sources):
            continue
        if ground_truth_page is not None and doc.get("page") != ground_truth_page:
            continue
        scores.append(doc.get("score", 0.0))
    return sum(scores) / len(scores) if scores else None


# ============================================================================
# 실험용 지표 — DB/청크 ID와 무관하게 3개 시스템을 같은 잣대로 비교하기 위한 함수들.
# (청크 ID는 DB마다 달라 청크 단위 Recall은 시스템 간 비교가 안 된다 — 대신 정답에 들어
#  있는 값(금액·일수·날짜 등)이 검색된 텍스트에 실제로 있는지를 본다.)
# ============================================================================

import re as _re

_ZERO_WIDTH_RE = _re.compile(r"[​‌‍﻿]")
_DATE_RE = _re.compile(
    r"(?<!\d)(\d{4})\s*[.\-/년]\s*(\d{1,2})\s*[.\-/월]\s*(\d{1,2})\s*(?:일|\.)?"
)
# 숫자 뒤에 바로 붙는 단위(원/일/%/개월 등). 단위가 없으면 3자리 이상(또는 쉼표 포함)일 때만 핵심값으로 본다.
_UNIT_PATTERN = r"(?:개월|원|일|%|퍼센트|년|월|시간|시|분|명|개|건|회|차|주|점|배)"
_NUMBER_RE = _re.compile(
    rf"(?<![\d,.])(\d{{1,3}}(?:,\d{{3}})+|\d+)(\.\d+)?\s?({_UNIT_PATTERN})?"
)


def normalize_for_match(text: str) -> str:
    """공백·쉼표·제로폭 문자를 지우고 날짜를 YYYYMMDD 형태로 통일한다."""
    s = _ZERO_WIDTH_RE.sub("", str(text or ""))
    s = _DATE_RE.sub(lambda m: f"D{int(m.group(1)):04d}{int(m.group(2)):02d}{int(m.group(3)):02d}", s)
    return _re.sub(r"[\s,]", "", s)


def extract_key_values(expected_answer: str) -> list[str]:
    """정답 문장에서 검색 텍스트에 그대로 들어 있어야 할 핵심값(숫자+단위, 날짜)을 뽑는다.

    평가셋을 고치지 않고 `expected_answer`에서 결정론적으로 추출한다. 단위 없는 1~2자리
    숫자는 너무 모호해(번호·항목 수 등) 제외한다. 날짜는 한 토큰으로 취급한다.
    """
    text = str(expected_answer or "")
    values: list[str] = []
    spans: list[tuple[int, int]] = []

    for m in _DATE_RE.finditer(text):
        values.append(m.group(0).strip())
        spans.append(m.span())

    for m in _NUMBER_RE.finditer(text):
        if any(s <= m.start() < e for s, e in spans):
            continue
        integer, frac, unit = m.group(1), m.group(2) or "", m.group(3) or ""
        digits = integer.replace(",", "")
        if not unit and len(digits) < 3 and "," not in integer:
            continue
        values.append(f"{integer}{frac}{unit}")

    ordered = sorted(
        zip(values, [text.find(v) for v in values]), key=lambda pair: pair[1]
    )
    seen: set[str] = set()
    result: list[str] = []
    for value, _ in ordered:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def calculate_key_value_hit_position(
    retrieved_texts: list[str], key_values: list[str]
) -> int | None:
    """모든 핵심값이 상위 r개 청크 텍스트(누적)에 처음 모두 나타나는 최소 r(1-based)."""
    keys = [normalize_for_match(v) for v in key_values if normalize_for_match(v)]
    if not keys:
        return None
    cumulative = ""
    for rank, text in enumerate(retrieved_texts, start=1):
        cumulative += normalize_for_match(text)
        if all(k in cumulative for k in keys):
            return rank
    return None


def calculate_context_hit_rate(hit_positions: list[int | None], k: int) -> float | None:
    """핵심값 적격 문항 중 상위 K 안에서 핵심값이 모두 확보된 비율. 적격 문항이 없으면 None."""
    if not hit_positions:
        return None
    return sum(1 for p in hit_positions if p is not None and p <= k) / len(hit_positions)


def calculate_key_value_mrr(hit_positions: list[int | None]) -> float | None:
    """핵심값이 처음 모두 확보된 순위의 역수 평균. 적격 문항이 없으면 None."""
    if not hit_positions:
        return None
    return sum(1.0 / p if p else 0.0 for p in hit_positions) / len(hit_positions)


def _has_section_label(value: object) -> bool:
    return str(value or "").strip().upper() not in {"", "N/A", "NONE", "NULL"}


def calculate_header_inclusion_rate(chunks: list[dict], k: int) -> float | None:
    """상위 K 청크 중 상위 대분류/중분류(section_level1/2) 메타데이터가 보존된 비율."""
    top = chunks[:k]
    if not top:
        return None
    kept = sum(
        1
        for c in top
        if _has_section_label(c.get("section_level1")) or _has_section_label(c.get("section_level2"))
    )
    return kept / len(top)


def table_pair_present(chunk_texts: list[str], label: str, value: str) -> bool:
    """어느 한 청크 안에 `라벨: 값`이 붙어서(라벨 뒤 곧바로 값) 존재하는지."""
    pattern = _re.compile(
        _re.escape(normalize_for_match(label)) + r"[:：]" + _re.escape(normalize_for_match(value))
    )
    return any(pattern.search(normalize_for_match(t)) for t in chunk_texts)


_PIPE_ROW_RE = _re.compile(r"^\|.+\|$")
_PIPE_SEP_RE = _re.compile(r"^\|[-:\s|]+\|$")


def markdown_table_blocks(text: str) -> list[list[list[str]]]:
    """Markdown 텍스트에서 표 블록(연속된 `|...|` 행)을 뽑아 `블록 → 행 → 셀` 목록으로 돌려준다.

    평탄화 코드(`table_flattener`)가 표를 찾는 규칙과 같다: 구분선 행은 버리고, 셀의 `<br>`는
    공백으로, 굵게 표시(`**`)는 지운다. 표가 아닌 줄(평문)은 블록에 들어가지 않는다.
    """
    blocks: list[list[list[str]]] = []
    current: list[list[str]] = []
    for line in str(text or "").split("\n"):
        stripped = line.strip()
        if _PIPE_ROW_RE.match(stripped):
            if _PIPE_SEP_RE.match(stripped):
                continue
            cells = [
                _re.sub(r"<br\s*/?>", " ", c, flags=_re.IGNORECASE).replace("**", "").strip()
                for c in stripped.strip("|").split("|")
            ]
            current.append(cells)
        elif current:
            blocks.append(current)
            current = []
    if current:
        blocks.append(current)
    return blocks


def _cell_matches(cell: str, target: str) -> bool:
    """셀이 목표 텍스트와 맞는지. 4자 이상이면 포함, 그보다 짧으면(예: 'B', '8') 셀 전체 일치만 인정한다."""
    c, t = normalize_for_match(cell), normalize_for_match(target)
    if not t:
        return False
    return c == t or (len(t) >= 4 and t in c)


def table_pair_detected(blocks: list[list[list[str]]], label: str, value: str) -> bool:
    """로더가 `라벨`과 `값`을 같은 표 블록 안의 셀로 내놓았는지(평탄화 이전 단계의 표 검출)."""
    for block in blocks:
        cells = [c for row in block for c in row]
        if any(_cell_matches(c, label) for c in cells) and any(_cell_matches(c, value) for c in cells):
            return True
    return False


def table_pair_in_text(text: str, label: str, value: str) -> bool:
    """표가 아닌 텍스트 줄에서 라벨과 값이 바로 이어져 있는지 (줄 단위, 양쪽 순서 인정).

    - 라벨 → 값: `라벨 : 값` (`:` 하나)
    - 값 → 라벨: `값 : 라벨` 또는 `값(라벨)` — 명시적 구분자가 있을 때만 인정한다.
    줄마다 따로 정규화해서 보므로 줄 사이는 잇지 않는다. 값→라벨을 구분자 없이 인정하면 평탄화된 행에서
    "앞 항목의 값"과 "다음 항목의 라벨"이 붙어 엉뚱한 쌍(`259204546부가가치세`)이 맞는 것으로 잡히기 때문이다.
    콜론이 두 번 끼는 `합계: :, 85,530,000`처럼 짝이 어긋난 줄은 맞지 않는다.
    """
    lab, val = normalize_for_match(label), normalize_for_match(value)
    if not lab or not val:
        return False
    el, ev = _re.escape(lab), _re.escape(val)
    patterns = [
        _re.compile(el + r"[:：]" + ev),
        _re.compile(ev + r"[:：]" + el),
        _re.compile(ev + r"[(（]" + el + r"[)）]"),
    ]
    for line in str(text or "").split("\n"):
        norm = normalize_for_match(line)
        if any(pat.search(norm) for pat in patterns):
            return True
    return False


def calculate_table_detection(
    blocks: list[list[list[str]]], pairs: list[tuple[str, str]], text: str | None = None
) -> tuple[list[bool], float | None]:
    """쌍별 검출 여부와 검출률. 쌍이 없으면 비율은 None.

    검출 = 같은 표 블록 안의 셀로 있거나(`table_pair_detected`), `text`가 주어지면 그 텍스트의 한 줄에서
    라벨과 값이 바로 이어져 있음(`table_pair_in_text`). 로더가 표를 문단 줄로 내놓아도 연결이 살아 있으면 검출이다.
    """
    flags = [
        table_pair_detected(blocks, label, value) or (text is not None and table_pair_in_text(text, label, value))
        for label, value in pairs
    ]
    return flags, (sum(flags) / len(flags) if flags else None)


def calculate_table_pair_accuracy(
    chunk_texts: list[str], pairs: list[tuple[str, str]]
) -> float | None:
    """정답 `라벨: 값` 쌍 중 청크에 정확히 존재하는 비율. 쌍이 없으면 None."""
    if not pairs:
        return None
    return sum(1 for label, value in pairs if table_pair_present(chunk_texts, label, value)) / len(pairs)


_BIGGER_CUE_RE = _re.compile(r"더 ?크|큽니다|큰 |큰$|더 ?많|많습니다|더 ?높|높습니다|가장|최대|최고")
_SMALLER_CUE_RE = _re.compile(r"더 ?작|작습니다|더 ?적|적습니다|더 ?낮|낮습니다|최소|최저")


def judge_numeric_comparison(
    answer: str,
    expected_values: list[str],
    expected_winner: str | None,
    expected_loser: str | None = None,
) -> bool:
    """수치 비교 질의의 답을 문자열로 결정론적으로 판정한다(LLM 미사용).

    1) 기대 값이 모두 답에 들어 있고, 2) `expected_winner`(큰 쪽)가 주어지면 비교 표현이 있는 문장에서
    승자가 언급돼야 한다. `expected_loser`도 주면 방향까지 본다 — "A가 B보다 크다"류는 승자가 패자보다
    앞에, "A가 B보다 작다"류는 승자가 패자보다 뒤에 나와야 한다. 패자가 문장에 없으면 승자 언급만 본다.
    문장 단위 휴리스틱이라 복잡한 서술은 오판할 수 있다는 한계가 있다.
    """
    normalized_answer = normalize_for_match(answer)
    for value in expected_values:
        if normalize_for_match(value) not in normalized_answer:
            return False
    if not expected_winner:
        return True
    winner = normalize_for_match(expected_winner)
    loser = normalize_for_match(expected_loser) if expected_loser else ""
    for sentence in _re.split(r"(?<=[.!?。])\s+|\n+", str(answer or "")):
        bigger = bool(_BIGGER_CUE_RE.search(sentence))
        smaller = bool(_SMALLER_CUE_RE.search(sentence))
        if not (bigger or smaller):
            continue
        norm = normalize_for_match(sentence)
        w = norm.find(winner)
        if w < 0:
            continue
        l = norm.find(loser) if loser else -1
        if l < 0:
            return True
        if smaller and not bigger:
            if w > l:
                return True
        elif w < l:
            return True
    return False
