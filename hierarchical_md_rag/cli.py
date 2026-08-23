"""`mdrag-eval <markdown_dir> <queries.yaml>` — 폴더 안의 모든 .md를 계층 기반/평문 두 방식으로
각각 청킹·인덱싱한 뒤, 같은 질의셋으로 Recall@K/MRR을 비교해서 표로 출력한다.

markdown 파일들은 이 도구가 만드는 게 아니다 — `#`/`##`/`###` 헤더가 이미 달린 markdown을
준비해서 넣어야 한다(한글 공문서라면
https://github.com/adover134/korean_official_document_parser_skill 참고)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml

from .chunk import chunk_flat, chunk_hierarchical
from .eval import evaluate


def load_queries(path: Path) -> list[dict]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    queries = data["queries"] if isinstance(data, dict) else data
    for q in queries:
        if "query" not in q or "expected_contains" not in q:
            raise ValueError(f"질의셋 형식 오류 — 'query'/'expected_contains' 필드가 필요함: {q}")
        if isinstance(q["expected_contains"], str):
            q["expected_contains"] = [q["expected_contains"]]
    return queries


def load_markdown_chunks(markdown_dir: Path, strategy, max_chars: int, overlap: int):
    all_chunks = []
    md_files = sorted(markdown_dir.glob("*.md"))
    if not md_files:
        raise SystemExit(f"{markdown_dir} 안에 .md 파일이 없습니다.")
    for f in md_files:
        text = f.read_text(encoding="utf-8")
        for c in strategy(text, max_chars=max_chars, overlap=overlap):
            c.metadata["source"] = f.name
            all_chunks.append(c)
    return all_chunks


def print_report(name: str, chunk_count: int, result: dict, top_k: int) -> None:
    print(f"\n=== {name} (청크 {chunk_count}개) ===")
    print(f"  Recall@{top_k}: {result['recall_at_k']:.1%}")
    print(f"  MRR: {result['mrr']:.3f}")
    misses = [r for r in result["results"] if not r.hit]
    if misses:
        print(f"  놓친 질의 {len(misses)}개:")
        for r in misses:
            print(f"    - {r.query!r}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("markdown_dir", help="헤더가 달린 .md 파일들이 있는 폴더")
    ap.add_argument("queries", help="질의셋 YAML (형식은 examples/queries.example.yaml 참고)")
    ap.add_argument("--top-k", type=int, default=5)
    ap.add_argument("--max-chars", type=int, default=1000)
    ap.add_argument("--overlap", type=int, default=200)
    ap.add_argument("--model", default="intfloat/multilingual-e5-small")
    ap.add_argument("--json", help="결과를 이 경로에 JSON으로도 저장")
    args = ap.parse_args()

    markdown_dir = Path(args.markdown_dir)
    queries = load_queries(Path(args.queries))
    print(f"질의 {len(queries)}개, 문서 폴더: {markdown_dir}")

    strategies = {"hierarchical": chunk_hierarchical, "flat": chunk_flat}
    report = {}
    for name, strategy in strategies.items():
        chunks = load_markdown_chunks(markdown_dir, strategy, args.max_chars, args.overlap)
        result = evaluate(chunks, queries, args.model, args.top_k)
        print_report(name, len(chunks), result, args.top_k)
        report[name] = {
            "chunk_count": len(chunks),
            "recall_at_k": result["recall_at_k"],
            "mrr": result["mrr"],
        }

    print(f"\n=== 요약 (top_k={args.top_k}) ===")
    print(f"{'전략':<14}{'청크 수':>8}{'Recall@K':>12}{'MRR':>8}")
    for name, r in report.items():
        print(f"{name:<14}{r['chunk_count']:>8}{r['recall_at_k']:>11.1%}{r['mrr']:>8.3f}")

    if args.json:
        Path(args.json).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nJSON 저장 -> {args.json}")


if __name__ == "__main__":
    main()
