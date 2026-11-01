r"""재정렬 점수(`_score_result`)에서 쓰는 수치·낱말 규칙.

수치 질문(얼마, 마감, 언제 …)에서 "답이 들어 있을 만한 숫자"를 판별한다. 예전 규칙은 `\d+(원|일|분 …)`만 인정해서
정답의 날짜·시각 서식(`2026. 08. 12. 15:00`)은 놓치고, 답과 무관한 `100분의 5`(비율)의 `100분`은 시간으로 세었다.
"""

from __future__ import annotations

import re

_UNIT_NUMBER = re.compile(r"\d+\s*(원|억|만|명|건|개|일|시간|분(?!의)|mb|gb|kb|%)", re.IGNORECASE)
_DATE_OR_TIME = re.compile(r"\d{4}\s*[.\-/]\s*\d{1,2}\s*[.\-/]\s*\d{1,2}|\d{1,2}\s*:\s*\d{2}")

# 법령형 문단 어디에나 나오는 기능어. 질문의 "핵심 낱말"로 쓰면 아무 법령 청크나 맞는다.
FUNCTION_WORDS = frozenset({"위한", "대한", "관한", "따른", "통한", "위해", "대해", "관해", "따라", "통해"})


def has_answer_number(text: str) -> bool:
    """단위가 붙은 수, 날짜(2026. 08. 12.), 시각(15:00)이 있으면 참. `100분의 5` 같은 비율의 `100분`은 세지 않는다."""
    return bool(_UNIT_NUMBER.search(text or "") or _DATE_OR_TIME.search(text or ""))
