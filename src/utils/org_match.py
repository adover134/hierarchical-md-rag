"""질문에서 기관(공고) 후보를 뽑는 보조 규칙.

기존 토큰 겹침 규칙은 "겹치는 단어가 2개 이상"이어야 후보로 인정한다. 그런데 질문이 기관을 `신목중학교`, `전주사랑의집`처럼
고유명 하나로만 가리키면 겹침이 1개라 후보에서 빠진다. 여기서는 그런 경우를 구제하되 오탐을 막기 위해 조건을 좁게 둔다.

  - 질문과 공고명이 정확히 같은 단어를 공유하고,
  - 그 단어가 상투어가 아니며(`교복`, `공사` 등), 날짜·차수처럼 숫자로 된 말이 아니고, 3글자 이상이며,
  - 기관 목록 전체에서 2곳 이하에만 나오는 드문 단어일 때만 후보로 본다.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from typing import Callable, Iterable

_TOKEN_RE = re.compile(r"[0-9a-zA-Z가-힣]{2,}")
_NUMERIC_LIKE_RE = re.compile(r"\d+[가-힣]{0,3}")
_LEGAL_FORM_TOKENS = {"주식회사", "유한회사", "합자회사", "사단법인", "재단법인", "학교법인", "의료법인", "사회복지법인"}


def _tokens(text: str) -> set[str]:
    return set(_TOKEN_RE.findall(unicodedata.normalize("NFKC", text or "").lower()))


def distinctive_token_candidates(
    query: str,
    org_names: Iterable[str],
    is_generic: Callable[[str], bool],
    *,
    max_doc_freq: int = 2,
    min_len: int = 3,
) -> list[tuple[int, str]]:
    """(점수, 기관명) 목록. 점수는 기존 토큰 겹침 규칙과 같은 형태(`겹친 단어 수 * 100 + 기관명 길이`)다."""
    orgs = list(org_names)
    org_tokens = {org: _tokens(org) for org in orgs}
    doc_freq = Counter(token for toks in org_tokens.values() for token in toks)
    query_tokens = _tokens(query)

    def eligible(token: str) -> bool:
        return (
            len(token) >= min_len
            and not is_generic(token)
            and token not in _LEGAL_FORM_TOKENS
            and not _NUMERIC_LIKE_RE.fullmatch(token)
            and doc_freq[token] <= max_doc_freq
        )

    found: list[tuple[int, str]] = []
    for org in orgs:
        hits = [t for t in org_tokens[org] & query_tokens if eligible(t)]
        if hits:
            found.append((len(hits) * 100 + len(org), org))
    return found
