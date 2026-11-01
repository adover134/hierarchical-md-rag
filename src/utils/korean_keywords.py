"""질문에서 조사·어미를 뗀 낱말을 뽑는다.

공백·기호로 나눈 토큰(`공사기간은`, `대집행복구공사의`, `며칠인가요`)은 어미가 붙어 있어 문서 줄과 부분 문자열로 맞지 않는다.
여기서는 Kiwi 형태소 분석으로 각 낱말의 앞쪽 내용 형태소(명사·어근·숫자·외래어)를 이어 붙이고, 처음 나오는 조사·어미·용언 앞에서 멈춘다.
"""

from __future__ import annotations

import re
from typing import Any

_WORD_RE = re.compile(r"[0-9a-zA-Z가-힣]{2,}")
# 명사류, 어근, 명사 파생 접사, 숫자·외래어·한자. 대명사(NP)와 조사·어미·용언은 넣지 않는다.
_CONTENT_TAGS = {"NNG", "NNP", "NNB", "NR", "XR", "XSN", "XPN", "SN", "SL", "SH"}


def stem_words(text: str, kiwi: Any) -> list[str]:
    """`text`의 낱말마다 조사·어미를 뗀 앞부분을 돌려준다. 내용 형태소가 없는 낱말은 뺀다.

    분석기가 실패하면 조사·어미를 못 떼므로 원래 낱말을 그대로 돌려준다.
    """
    if not text:
        return []
    spans = [(m.start(), m.end()) for m in _WORD_RE.finditer(text)]
    try:
        morphs = list(kiwi.tokenize(text))
    except Exception:
        return [text[s:e] for s, e in spans]

    stems: list[str] = []
    for start, end in spans:
        word = [m for m in morphs if start <= m.start < end]
        stem_end = None
        for pos, m in enumerate(word):
            if m.tag not in _CONTENT_TAGS:
                # 낱말 중간의 관형격 조사 '의' 뒤에 명사가 이어지면 고유명의 일부다(전주사랑의집). 낱말 끝의 '의'는 조사다.
                if m.tag == "JKG" and m.form == "의" and pos + 1 < len(word) and word[pos + 1].tag in _CONTENT_TAGS:
                    continue
                break
            stem_end = m.start + m.len
        if stem_end is not None:
            stem = text[start:min(stem_end, end)]
            if len(stem) >= 2:
                stems.append(stem)
    return stems
