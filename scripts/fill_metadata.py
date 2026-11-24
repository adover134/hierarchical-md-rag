"""엑셀에 없는 값(사업 금액, 입찰마감일시)을 Claude 서브에이전트로 채운다.

    python scripts/fill_metadata.py export --markdown-dir output/new_parser_md output   # 빈 칸이 있는 문서의 배치 파일을 만든다
    (Claude 서브에이전트가 배치마다 문서를 읽고 답 파일을 쓴다)
    python scripts/fill_metadata.py import --answers data_index/metadata_fill/answers/*.json  # 검증 후 CSV에 기록
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.metadata.fill import FillError, export_batches, import_answers  # noqa: E402
from src.utils.config import PROJECT_ROOT  # noqa: E402

CSV_PATH = PROJECT_ROOT / "data_index" / "metadata.csv"
FILL_DIR = PROJECT_ROOT / "data_index" / "metadata_fill"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("export")
    e.add_argument("--markdown-dir", nargs="+", required=True)
    e.add_argument("--out", default=str(FILL_DIR / "batches"))
    e.add_argument("--batch-size", type=int, default=6)
    i = sub.add_parser("import")
    i.add_argument("--answers", nargs="+", required=True)
    args = ap.parse_args()

    if args.cmd == "export":
        paths = export_batches(CSV_PATH, args.markdown_dir, args.out, args.batch_size)
        print(f"배치 {len(paths)}개: {args.out}" if paths else "채울 칸이 없다")
    else:
        try:
            stats = import_answers(CSV_PATH, [Path(p) for p in args.answers])
        except FillError as err:
            raise SystemExit(str(err))
        print(f"기록 완료: {stats}")


if __name__ == "__main__":
    main()
