"""엑셀(나라장터 입찰공고목록)과 Markdown 폴더로 `data_index/metadata.csv`를 만든다.

    python scripts/build_metadata.py --markdown-dir output/new_parser_md output [--bid-list-xlsx <엑셀>] [--allow-unmatched]

이미 Claude가 채운 값이 있는 CSV는 덮어쓰지 않고 멈춘다(`--rebuild`로 일부러 다시 만들 때만 덮어쓴다).
순서는 파싱 → 메타데이터(이 스크립트) → 채우기(Claude) → 청킹과 DB다. 채운 뒤에는 이 단계를 다시 돌리지 않는다.
매칭 안 되는 행이나 주인 없는 문서가 있으면 목록을 보여 주고 멈춘다(`--allow-unmatched`면 파일명을 비운 채 계속).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.metadata.build import MetadataError, build_metadata_rows, filled_count, write_metadata_csv  # noqa: E402
from src.utils.config import PROJECT_ROOT  # noqa: E402
from src.utils.org_dictionary import DEFAULT_DICTIONARY_PATH, build_dictionary_from_metadata  # noqa: E402

DEFAULT_OUT = PROJECT_ROOT / "data_index" / "metadata.csv"


def find_excel(explicit: str | None) -> Path:
    if explicit:
        return Path(explicit)
    found = sorted((PROJECT_ROOT / "data_index").glob("입찰공고목록*.xlsx"))
    if not found:
        raise SystemExit("엑셀을 찾지 못했다. --bid-list-xlsx로 알려 주거나 data_index/입찰공고목록*.xlsx에 둔다.")
    return found[0]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--markdown-dir", required=True, nargs="+", help="파서와 PDF 로더가 만든 Markdown 폴더(여러 개 가능)")
    ap.add_argument("--bid-list-xlsx")
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--allow-unmatched", action="store_true")
    ap.add_argument("--rebuild", action="store_true", help="채운 값이 있어도 엑셀로 CSV를 다시 만든다(채운 값은 사라진다)")
    args = ap.parse_args()

    kept = filled_count(args.out)
    if kept and not args.rebuild:
        raise SystemExit(f"중단: {args.out}에 Claude가 채운 값이 {kept}건 있다. 메타데이터는 한 번 만들고 채운 뒤에는 다시 만들지 않는다.\n  일부러 다시 만들려면 --rebuild를 붙인다(채운 값은 사라진다).")
    xlsx = find_excel(args.bid_list_xlsx)
    try:
        header, rows = build_metadata_rows(xlsx, args.markdown_dir, allow_unmatched=args.allow_unmatched)
    except MetadataError as e:
        raise SystemExit(f"중단: 엑셀과 문서가 맞지 않는다.\n{e}")
    out = write_metadata_csv(header, rows, args.out)
    blank_deadline = sum(1 for r in rows if not r["입찰마감일시"])
    blank_amount = sum(1 for r in rows if not r["사업 금액"])
    words = build_dictionary_from_metadata(out, DEFAULT_DICTIONARY_PATH if args.out == str(DEFAULT_OUT) else Path(args.out).with_name("org_dictionary.txt"))
    print(f"기관명 사전: {len(words)}개 낱말")
    print(f"{out}: {len(rows)}행 (입찰마감일시 빈 값 {blank_deadline}, 사업 금액 빈 값 {blank_amount})")


if __name__ == "__main__":
    main()
