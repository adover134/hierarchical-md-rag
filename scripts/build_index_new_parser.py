"""새 파서로 HWP/HWPX 문서를 인덱싱한다 — `preprocessor.py`(원본 팀 파이프라인)의 HWP→PDF→
audit 경로 대신 `parser_bridge.py`(hwp2md 직결)를 쓴다는 것만 다르고, 그 이후(청킹→Chroma 적재)는
`preprocessor.py`의 `process_single_pdf()`와 동일한 `build_db.py` 함수들을 그대로 재사용한다.

사용법:
    python scripts/build_index_new_parser.py --input <HWP/HWPX 폴더> [--backend groq]
        [--model openai/gpt-oss-20b] [--limit N]
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
import unicodedata
from pathlib import Path
from typing import Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from parser_bridge import convert_with_new_parser, process_file_no_regex_reextraction

SUPPORTED_EXTENSIONS = {".hwp", ".hwpx"}


def process_single_hwp(hwp_path: Path, work_dir: Path, output_dir: Path, backend: str, model: str) -> Dict:
    from src.retrievers.build_db import (
        compute_doc_id, assign_uids, build_hierarchy, apply_section_uids,
        upsert_hybrid_chunks, upsert_hierarchy_chroma,
    )

    result = {
        "file": hwp_path.name, "status": "success", "duration_sec": 0.0,
        "chunk_count": 0, "sparse_count": 0, "dense_count": 0, "hierarchy_count": 0,
        "reindexed": False, "error": "",
    }
    t0 = time.time()

    parsed_path = convert_with_new_parser(hwp_path, work_dir, backend=backend, model=model)
    chunks = process_file_no_regex_reextraction(parsed_path)
    result["chunk_count"] = len(chunks)

    if len(chunks) == 0:
        result["status"] = "failed"
        result["error"] = "zero chunks produced"
        result["duration_sec"] = time.time() - t0
        return result

    chunks_dir = output_dir / "chunks"
    chunks_dir.mkdir(parents=True, exist_ok=True)
    stem = unicodedata.normalize("NFC", hwp_path.stem)
    for i, chunk in enumerate(chunks):
        chunk["chunk_id"] = i
        chunk["doc_id"] = compute_doc_id(parsed_path)
        chunk_file = chunks_dir / f"chunk_{stem}_{i:05d}.json"
        with open(chunk_file, "w", encoding="utf-8") as f:
            json.dump(chunk, f, ensure_ascii=False, indent=2)

    assign_uids(chunks)
    hierarchy_entries, section_uid_map = build_hierarchy(chunks)
    apply_section_uids(chunks, section_uid_map)

    hybrid_count = upsert_hybrid_chunks(chunks)
    hierarchy_count = upsert_hierarchy_chroma(hierarchy_entries)

    result["sparse_count"] = hybrid_count
    result["dense_count"] = hybrid_count
    result["hierarchy_count"] = hierarchy_count
    result["reindexed"] = True
    result["duration_sec"] = time.time() - t0
    return result


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input", "-i", required=True, help="HWP/HWPX 원본 폴더")
    ap.add_argument("--backend", default="ollama", choices=["ollama", "openai", "groq", "gemini"])
    ap.add_argument("--model", default="qwen3.5:9b")
    ap.add_argument("--limit", type=int, help="처리할 문서 수 상한 (테스트용)")
    args = ap.parse_args()

    from src.utils.config import PROJECT_ROOT

    data_dir = Path(args.input).resolve()
    work_dir = PROJECT_ROOT / "output" / "new_parser_md"
    output_dir = PROJECT_ROOT / "output"

    files = sorted(p for p in data_dir.iterdir() if p.suffix.lower() in SUPPORTED_EXTENSIONS)
    if args.limit:
        files = files[: args.limit]
    print(f"대상 {len(files)}개 파일")

    results: List[Dict] = []
    for i, f in enumerate(files, 1):
        print(f"\n[{i}/{len(files)}] {f.name}")
        try:
            result = process_single_hwp(f, work_dir, output_dir, args.backend, args.model)
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

    summary_path = output_dir / "execution_summary_new_parser.csv"
    output_dir.mkdir(parents=True, exist_ok=True)
    with open(summary_path, "w", newline="", encoding="utf-8") as f:
        fieldnames = ["file", "status", "duration_sec", "chunk_count", "sparse_count", "dense_count", "hierarchy_count", "reindexed", "error"]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results)

    ok = sum(1 for r in results if r["status"] == "success")
    print(f"\n완료: {ok}/{len(results)} 성공 -> {summary_path}")


if __name__ == "__main__":
    main()
