"""입찰공고 엑셀의 기관명으로 Kiwi 사용자 사전을 만들고, 그 사전을 불러온 Kiwi를 돌려준다.

`전주사랑의집`, `신목중학교` 같은 기관 고유명은 일반 사전에 없어 `전주사랑 / 의 / 집`처럼 쪼개진다. 기관명을 미리 고유명사(NNP)로 등록하면
DB 구축(BM25 명사 추출)과 질의 처리(키워드 추출)가 같은 방식으로 기관명을 한 덩어리로 다룬다. 사전 파일은 DB 구축 단계에서 만들고
(`scripts/build_index_new_parser.py`, `scripts/index_pdf_originals.py`), 질의 시점에는 읽기만 한다.
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import Iterable

from src.utils.config import PROJECT_ROOT

DEFAULT_DICTIONARY_PATH = PROJECT_ROOT / "data_index" / "org_dictionary.txt"

_ORG_COLUMNS = ("공고기관", "수요기관", "발주 기관")
# 기관명에 붙는 법인 형태 표기. 종류를 고정해 둔다(괄호 묶음을 모두 떼면 `(직속기관)` 같은 이름의 일부까지 지운다).
# NFKC로 먼저 정규화하므로 `㈜`는 `(주)`로, `(사）`처럼 모양이 섞인 괄호는 `(사)`로 바뀐다.
#   약칭: (주)주식회사 (유)유한회사 (합)합명회사 (자)합자회사 [상법 회사, 검색으로 확인]
#         (사)사단법인 (재)재단법인 (학)학교법인 (의)의료법인 (복)사회복지법인 [관행 표기, 한국어 자료로는 확인하지 못함]
#   낱말: 상법의 5종 회사, 사단·재단·학교·의료·사회복지·농업회사 법인
# 새 표기가 나오면 여기에만 추가하고, tests/test_org_dictionary.py의 엑셀 점검이 목록 밖 표기를 잡는다.
_BRACKET_GROUP = re.compile(r"\(\s*(?:주|유|합|자|사|재|학|의|복)\s*\)")
_WORD_FORM = re.compile(
    r"(주식회사|유한책임회사|유한회사|합명회사|합자회사|사단법인|재단법인|학교법인|의료법인|사회복지법인|농업회사법인)"
)


def clean_org_name(name: str) -> str:
    """기관명에서 법인 형태 표기((주), ㈜, 주식회사, (사) 등)를 뗀다. 이름 안의 띄어쓰기는 그대로 둔다."""
    text = unicodedata.normalize("NFKC", name or "")
    text = _BRACKET_GROUP.sub(" ", text)
    text = _WORD_FORM.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


def _markers(name: str) -> list[str]:
    """기관명에 붙은 표기(괄호 묶음, 법인 형태 낱말)를 NFKC로 정규화해 돌려준다(`(사）` → `(사)`, `㈜` → `(주)`)."""
    text = unicodedata.normalize("NFKC", name or "")
    return [re.sub(r"\s+", "", m.group(0)) for m in _BRACKET_GROUP.finditer(text)] + [m.group(0) for m in _WORD_FORM.finditer(text)]


def org_words(names: Iterable[str]) -> list[str]:
    """기관명마다 사전에 넣을 낱말을 중복 없이 등록 순서대로 돌려준다. 한 글자 낱말은 뺀다.

    질문에는 `한성케미칼`처럼 법인 표기 없이, 문서에는 `(주)한성케미칼`처럼 표기가 붙어 나오므로 둘 다 넣는다.
      - 법인 표기를 뗀 낱말(공백 기준)
      - 법인 표기가 있던 기관은 그 표기를 앞·뒤에 붙인 낱말(`(주)한성케미칼`, `한성케미칼(주)`, `주식회사에스알`)
    표기만 있는 낱말(`(주)`, `주식회사`)은 넣지 않는다.
    """
    seen: dict[str, None] = {}
    for name in names:
        core_words = [w for w in clean_org_name(name).split() if len(w) >= 2]
        for word in core_words:
            seen.setdefault(word, None)
        for marker in _markers(name):
            for word in core_words:
                seen.setdefault(f"{marker}{word}", None)
                seen.setdefault(f"{word}{marker}", None)
    return list(seen)


def org_words_from_xlsx(xlsx_path: Path | str) -> list[str]:
    from src.utils.bid_list_xlsx import read_bid_list_rows

    names = [row.get(col, "") for row in read_bid_list_rows(xlsx_path) for col in _ORG_COLUMNS]
    return org_words(n for n in names if n)


def write_user_dictionary(words: Iterable[str], path: Path | str = DEFAULT_DICTIONARY_PATH) -> Path:
    """Kiwi 사용자 사전 형식(`단어<TAB>품사<TAB>점수`)으로 쓴다."""
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(f"{w}\tNNP\t0\n" for w in words), encoding="utf-8")
    return out


def build_dictionary_from_xlsx(xlsx_path: Path | str, path: Path | str = DEFAULT_DICTIONARY_PATH) -> list[str]:
    """DB 구축 단계에서 부른다. 엑셀의 기관명 낱말을 사전 파일로 쓰고 그 목록을 돌려준다."""
    words = org_words_from_xlsx(xlsx_path)
    write_user_dictionary(words, path)
    return words


def refresh_dictionary(xlsx_path: Path | str | None = None, path: Path | str = DEFAULT_DICTIONARY_PATH) -> list[str]:
    """DB 구축 스크립트가 처음에 부른다. 엑셀을 지정하지 않으면 `data_index/입찰공고목록*.xlsx` 중 첫 파일을 쓰고,
    엑셀이 없으면 사전을 건드리지 않는다(기존 사전 파일은 그대로 둔다)."""
    if xlsx_path is None:
        found = sorted((PROJECT_ROOT / "data_index").glob("입찰공고목록*.xlsx"))
        if not found:
            return []
        xlsx_path = found[0]
    return build_dictionary_from_xlsx(xlsx_path, path)


def new_kiwi(dictionary_path: Path | str | None = None):
    """기관명 사전을 불러온 Kiwi. 사전 파일이 없거나 읽을 수 없으면 기본 Kiwi를 돌려준다."""
    from kiwipiepy import Kiwi

    kiwi = Kiwi()
    path = Path(dictionary_path) if dictionary_path is not None else DEFAULT_DICTIONARY_PATH
    if path.is_file():
        try:
            kiwi.load_user_dictionary(str(path))
        except Exception:
            pass
    return kiwi
