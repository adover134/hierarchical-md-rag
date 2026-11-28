"""채점 검증자 전용: 공고 목록 엑셀 원본을 읽는다.

찾은 행은 모든 열(사업 금액, 게시일시 포함)을 보여준다. 답변 생성이 공고 목록을 먼저 보므로 검증자도 같은 값을 볼 수 있어야 한다.

사용 예:
    python scripts/judge_excel.py                      # 건수와 열 이름
    python scripts/judge_excel.py 한성케미칼
    python scripts/judge_excel.py R26BK01647662-001
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from judge_search import CORPUS_PATH, MAX_OUTPUT, REPO_ROOT, SOURCE_DIR, load_corpus, norm  # noqa: E402

NOTICE_LIST = "입찰공고목록*.xlsx"


def read_notices(source_dir: Path = SOURCE_DIR) -> list[dict[str, str]]:
    """원본 폴더의 공고 목록 엑셀을 행으로 읽는다. 열을 빼지 않는다."""
    sys.path.insert(0, str(REPO_ROOT))
    from src.utils.bid_list_xlsx import read_bid_list_rows  # 머리글 행을 찾아 {열 이름: 값}으로 읽는 일만 한다

    return [row for xlsx in sorted(Path(source_dir).glob(NOTICE_LIST)) for row in read_bid_list_rows(xlsx)]


def excel_text(notices: list[dict], documents: list[dict], query: str = "") -> str:
    """낱말이 든 행을 많이 맞은 순서로, 행마다 모든 열과 원본 문서의 번호와 이름을 붙여 돌려준다."""
    words = [norm(w) for w in query.split() if norm(w)]
    if not words:
        return f"공고 목록 {len(notices)}건. 열: {', '.join(notices[0])}" if notices else "공고 목록이 비었습니다."
    found = []
    for row in notices:
        joined = norm(" ".join(str(v) for v in row.values()))
        hits = sum(w in joined for w in words)
        if hits:
            title = norm(row.get("공고명", ""))
            docs = [f"문서 {d['no']}: {d['file']}" for d in documents if norm(d["file"]).startswith(title + "_")]
            found.append((hits, " | ".join(f"{k}={v}" for k, v in row.items()) + f" | {', '.join(docs) or '문서 없음'}"))
    if not found:
        return "찾은 것이 없습니다."
    lines = [line for _, line in sorted(found, key=lambda f: -f[0])]
    shown: list[str] = []
    for line in lines:  # 행을 중간에서 자르지 않는다
        if shown and sum(len(s) + 1 for s in shown) + len(line) > MAX_OUTPUT:
            break
        shown.append(line)
    if len(shown) < len(lines):
        shown.append(f"... 외 {len(lines) - len(shown)}건. 낱말을 더 넣어 좁히세요.")
    return "\n".join(shown)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("query", nargs="*")
    ap.add_argument("--source", default=str(SOURCE_DIR))
    ap.add_argument("--corpus", default=str(CORPUS_PATH), help="문서 번호를 붙일 때 읽는 검색 자료")
    a = ap.parse_args()
    documents = load_corpus(Path(a.corpus))["documents"] if Path(a.corpus).exists() else []
    print(excel_text(read_notices(Path(a.source)), documents, " ".join(a.query)))


if __name__ == "__main__":
    main()
