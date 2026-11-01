"""DB 구축 단계의 누락 측정 — 로더 출력의 글이 최종 청크에 얼마나 남아 있는가.

문서마다 로더 출력(Markdown)과 그 문서의 최종 청크 텍스트를 같은 방식으로 정규화(한글·영문·숫자만 남김)한 뒤,
로더 출력의 연속 `n`글자 조각(기본 8)이 청크 텍스트에도 있는 비율을 센다.

  coverage          로더 출력의 조각 중 청크에 남은 비율 (낮을수록 누락이 많다)
  chunk_over_loader 청크 전체 글자 수 / 로더 출력 글자 수 (1보다 크면 청크에 겹침·삽입으로 늘어난 부분이 있다)

한계: 표 평탄화는 `라벨: 값`을 만들며 머리글을 끼워 넣어 표 안쪽 조각이 일부 깨지므로, 표가 많은 문서의 coverage는 낮게 나온다
(하한값). 그래서 값 하나로 누락을 단정하지 않고 두 시스템의 같은 문서를 나란히 본다. PDF 원본 문서는 현재 버전의 로더 출력이 없어 제외한다.

사용 예:
    python scripts/eval_omission.py --snapshots ../hmr_db_snapshots --team-md ../RAG_project/output --current-md output/new_parser_md
"""

from __future__ import annotations

import argparse
import json
import re
import unicodedata
from pathlib import Path

_KEEP = re.compile(r"[^0-9a-zA-Z가-힣]")
_FRONTMATTER = re.compile(r"\A---\n.*?\n---\n", re.DOTALL)


def normalize(text: str) -> str:
    """한글·영문·숫자만 남긴다. 표 구분선, 굵게 표시, 공백 차이를 무시하기 위해서다."""
    return _KEEP.sub("", unicodedata.normalize("NFKC", text or "")).lower()


def shingles(text: str, n: int = 8) -> set[str]:
    return {text[i : i + n] for i in range(max(0, len(text) - n + 1))}


def coverage(source_text: str, chunk_texts: list[str], n: int = 8) -> dict:
    """source_text의 n글자 조각 중 청크 텍스트에 남아 있는 비율과 글자 수 비."""
    src = normalize(_FRONTMATTER.sub("", source_text, count=1))
    chunks = normalize("".join(chunk_texts))
    src_sh = shingles(src, n)
    kept = len(src_sh & shingles(chunks, n))
    return {
        "coverage": round(kept / len(src_sh), 4) if src_sh else None,
        "source_chars": len(src),
        "chunk_chars": len(chunks),
        "chunk_over_loader": round(len(chunks) / len(src), 3) if src else None,
        "lost_shingles": len(src_sh) - kept,
    }


def doc_key(value: str) -> str:
    return unicodedata.normalize("NFC", value).rsplit(".", 1)[0].strip().lower()


def find_md(md_dir: Path, source: str, glob: str) -> Path | None:
    key = doc_key(source)
    for f in sorted(md_dir.glob(glob)):
        if key in doc_key(f.name):
            return f
    return None


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--snapshots", required=True)
    ap.add_argument("--team-md", required=True, help="팀 로더 출력 폴더(step1_parsed_*.md)")
    ap.add_argument("--current-md", required=True, help="현재 로더 출력 폴더(skill 최종 md)")
    ap.add_argument("--n", type=int, default=8)
    ap.add_argument("--out", help="결과 JSON 경로")
    a = ap.parse_args()

    spec = {"team_final": (Path(a.team_md), "step1_parsed_*.md"), "current_default": (Path(a.current_md), "*.md")}
    result: dict[str, dict] = {}
    for name, (md_dir, glob) in spec.items():
        chunks = json.loads((Path(a.snapshots) / name / "chunks.json").read_text(encoding="utf-8"))
        by_source: dict[str, list[str]] = {}
        for c in chunks:
            by_source.setdefault(c["source"], []).append(c["text"])
        rows = {}
        for source, texts in by_source.items():
            md = find_md(md_dir, source, glob)
            if md is None:
                continue
            rows[source] = coverage(md.read_text(encoding="utf-8"), texts, a.n)
        result[name] = rows
    common = sorted(set(result["team_final"]) & set(result["current_default"]))
    print(f"비교 가능한 문서(두 시스템의 로더 출력이 모두 있는 것): {len(common)}개")
    for name, rows in result.items():
        vals = [rows[s]["coverage"] for s in common if rows[s]["coverage"] is not None]
        print(f"[{name}] 평균 coverage {sum(vals) / len(vals):.3f}, 0.9 미만 문서 {sum(v < 0.9 for v in vals)}개, 0.8 미만 {sum(v < 0.8 for v in vals)}개")
    # 교차 비교: 한쪽 로더 출력의 글이 상대 시스템의 최종 청크에 남아 있는가. 한쪽에만 있는 내용이 로더 단계의 누락 후보다.
    chunk_texts = {n: {} for n in spec}
    for name in spec:
        for c in json.loads((Path(a.snapshots) / name / "chunks.json").read_text(encoding="utf-8")):
            chunk_texts[name].setdefault(c["source"], []).append(c["text"])
    cross = {"team_loader_in_current_chunks": {}, "current_loader_in_team_chunks": {}}
    for source in common:
        t_md = find_md(Path(a.team_md), source, spec["team_final"][1])
        c_md = find_md(Path(a.current_md), source, spec["current_default"][1])
        cross["team_loader_in_current_chunks"][source] = coverage(t_md.read_text(encoding="utf-8"), chunk_texts["current_default"][source], a.n)
        cross["current_loader_in_team_chunks"][source] = coverage(c_md.read_text(encoding="utf-8"), chunk_texts["team_final"][source], a.n)
    result["cross"] = cross
    for label, rows in cross.items():
        vals = [r["coverage"] for r in rows.values() if r["coverage"] is not None]
        print(f"[교차 {label}] 평균 {sum(vals) / len(vals):.3f}, 0.9 미만 {sum(v < 0.9 for v in vals)}개, 0.8 미만 {sum(v < 0.8 for v in vals)}개, 0.7 미만 {sum(v < 0.7 for v in vals)}개")
    if a.out:
        Path(a.out).write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
