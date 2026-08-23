"""PDF 원본 문서를 팀의 기존(수정 안 한) PDF 경로로 인덱싱한다.

이 문서들은 HWP/HWPX가 아니라 애초에 PDF로 발급된 원본이라, 새 파서(hwp2md, kordoc 기반)의
대상이 아니다 — kordoc 자체가 HWP/HWPX 전용이므로 여기 적용할 수 없다. 그래서 이 문서들은
`preprocessor.py`의 원래 PDF 경로(`pdf_loader.load_pdf` → `auditor.audit_file` →
`chunker.process_file`, 전부 원본 그대로, 수정 없음)를 그대로 써서 같은 ChromaDB에 추가한다 —
HWP 경로만 새 파서로 바뀌었을 뿐, PDF 경로는 원래 팀 파이프라인 로직을 그대로 신뢰한다.

사용법:
    python scripts/index_pdf_originals.py --input <PDF 원본 폴더> [--limit N]
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path
from typing import Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from preprocessor import process_single_pdf


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input", "-i", required=True, help="PDF 원본 폴더")
    ap.add_argument("--limit", type=int)
    args = ap.parse_args()

    from src.utils.config import PROJECT_ROOT

    data_dir = Path(args.input).resolve()
    output_dir = PROJECT_ROOT / "output"
    output_dir.mkdir(parents=True, exist_ok=True)

    files = sorted(data_dir.glob("*.pdf"))
    if args.limit:
        files = files[: args.limit]
    print(f"대상 {len(files)}개 PDF")

    results: List[Dict] = []
    for i, f in enumerate(files, 1):
        print(f"\n[{i}/{len(files)}] {f.name}")
        try:
            result = process_single_pdf(f, output_dir)
        except Exception as e:
            result = {
                "file": f.name, "status": "failed", "duration_sec": 0.0,
                "chunk_count": 0, "sparse_count": 0, "dense_count": 0,
                "hierarchy_count": 0, "reindexed": False, "error": str(e),
            }
            print(f"  실패: {e}")
        results.append(result)
        if result["status"] == "success":
            print(f"  완료: 청크 {result['chunk_count']}개, {result['duration_sec']:.1f}s")
        else:
            print(f"  실패: {result.get('error')}")

    summary_path = output_dir / "execution_summary_pdf_originals.csv"
    with open(summary_path, "w", newline="", encoding="utf-8") as f:
        fieldnames = ["file", "status", "duration_sec", "chunk_count", "sparse_count", "dense_count", "hierarchy_count", "reindexed", "error"]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results)

    ok = sum(1 for r in results if r["status"] == "success")
    print(f"\n완료: {ok}/{len(results)} 성공 -> {summary_path}")


if __name__ == "__main__":
    main()
