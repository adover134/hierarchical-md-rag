"""표 처리 단계별 측정 — 프로젝트·브랜치와 무관하게 로더 출력(Markdown)과 그 프로젝트의 평탄화 코드만 있으면 된다.

DB·LLM이 필요 없다. 정답 `라벨: 값` 쌍(experiments/table_samples.yaml)마다 세 가지를 잰다.

  표 검출률        로더 출력에서 라벨-값 연결이 살아 있는가 (같은 표 블록 안의 셀, 또는 한 줄에서 `라벨 : 값` / `값 : 라벨` / `값(라벨)`)
  평탄화·정리 정합률  검출된 쌍이 평탄화(step2)와 텍스트 정리(step2b) 뒤에도 `라벨: 값`으로 남는가
  종단 정합률       최종 청크에 `라벨: 값`이 남는가 (재청킹 또는 청크 덤프 기준)

평탄화는 대상 프로젝트의 코드(`<project-root>/src/parsers`)를 별도 프로세스로 불러 적용한다. 이 저장소와 팀 저장소가
모두 `src.*` 모듈명을 쓰기 때문에 한 프로세스에서 같이 import할 수 없어서다.

사용 예 (이 저장소의 현재 코드, 캐시된 skill 출력을 재청킹):
    python scripts/eval_parsing.py --project-root . --loader-md-dir output/new_parser_md --rechunk --tag after
다른 체크아웃(청킹 진입점이 없으면 청크 덤프로 종단 정합률을 계산):
    python scripts/eval_parsing.py --project-root ../RAG_project --loader-md-dir output \\
        --loader-md-glob "step1_parsed_*.md" --chunk-dump runs/team_final_chunks.json --tag before
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import unicodedata
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SAMPLES = REPO_ROOT / "experiments" / "table_samples.yaml"
DEFAULT_OUT_DIR = REPO_ROOT / "eval_resources" / "parsing_runs"


def source_key(value: Any) -> str:
    return unicodedata.normalize("NFC", str(value or "")).rsplit(".", 1)[0].strip().lower()


def loader_md_path(root: Path, loader_md_dir: str, source: str, glob: str = "*.md") -> Path | None:
    """로더 Markdown 출력 중 샘플 문서의 것을 찾는다(파일명에 문서 키가 들어 있는 것)."""
    key = source_key(source)
    for f in sorted((root / loader_md_dir).glob(glob)):
        if key in source_key(f.name):
            return f
    return None


def flatten_files(project_root: str, spec_file: str, out_file: str) -> None:
    """대상 프로젝트의 평탄화·텍스트 정리(+선택: 재청킹)를 로더 출력 파일들에 적용한다. 대상 프로젝트 루트에서 실행된다.

    두 파이프라인 모두 청킹 전에 "표 평탄화(step2) → 텍스트 정리(step2b: 굵게 표시 ** 제거 등)" 순으로 처리한다.
    평탄화 단계의 결과는 정리까지 거친 텍스트로 본다(정리 전에는 `**값**`처럼 라벨:값 인접이 깨져 보인다).
    """
    root = Path(project_root).resolve()
    sys.path.insert(0, str(root))
    os.chdir(root)
    spec = json.loads(Path(spec_file).read_text(encoding="utf-8"))
    from src.parsers.chunker import parse_frontmatter, step2_flatten_tables, step2b_clean_text

    rechunk = None
    if spec.get("rechunk"):
        from scripts.parser_bridge import process_file_no_regex_reextraction as rechunk
    result: dict[str, Any] = {}
    for path in spec["paths"]:
        text = Path(path).read_text(encoding="utf-8")
        _, body = parse_frontmatter(text)
        entry: dict[str, Any] = {"flattened": step2b_clean_text(step2_flatten_tables(body))}
        if rechunk:
            entry["chunks"] = [c["page_content"] for c in rechunk(Path(path))]
        result[path] = entry
    Path(out_file).write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")


def parsing_summary(records: list[dict]) -> dict[str, Any]:
    def rate(num: int, den: int) -> float | None:
        return round(num / den, 4) if den else None

    n = len(records)
    det = [r for r in records if r["detected"]]
    return {
        "pairs_n": n,
        "detected_n": len(det),
        "detection_rate": rate(len(det), n),
        "flatten_ok_of_detected": rate(sum(r["flatten_ok"] for r in det), len(det)),
        "flatten_ok_n": sum(r["flatten_ok"] for r in det),
        "end_to_end_rate": rate(sum(r["e2e_ok"] for r in records), n)
        if records and all(r["e2e_ok"] is not None for r in records) else None,
        "end_to_end_n": sum(bool(r["e2e_ok"]) for r in records),
    }


def evaluate_system(system: dict, samples: list[dict], work_dir: Path, tag: str) -> dict[str, Any]:
    """한 시스템(프로젝트 체크아웃)을 샘플 전체에 대해 측정한다.

    system: name, title, project_root, loader_md_dir, [loader_md_glob], [rechunk], [chunk_dump], [env]
    """
    sys.path.insert(0, str(REPO_ROOT))
    from src.evaluation import metrics as M

    name = system["name"]
    root = Path(system["project_root"]).resolve()
    paths = {s["source"]: loader_md_path(root, system["loader_md_dir"], s["source"], system.get("loader_md_glob", "*.md"))
             for s in samples}
    work_dir.mkdir(parents=True, exist_ok=True)
    spec_file = work_dir / f"parsing_{tag}_{name}_in.json"
    flat_file = work_dir / f"parsing_{tag}_{name}_flat.json"
    spec_file.write_text(json.dumps({"paths": sorted({str(p) for p in paths.values() if p}),
                                     "rechunk": bool(system.get("rechunk"))}, ensure_ascii=False), encoding="utf-8")
    subprocess.run([sys.executable, str(Path(__file__).resolve()), "_flatten_files", "--project-root", str(root),
                    "--spec", str(spec_file), "--out", str(flat_file)],
                   cwd=root, env={**os.environ, **system.get("env", {})}, check=True)
    flat = json.loads(flat_file.read_text(encoding="utf-8"))
    dump_file = system.get("chunk_dump")
    dump = json.loads(Path(dump_file).read_text(encoding="utf-8")) if dump_file and Path(dump_file).exists() else []

    records: list[dict] = []
    for smp in samples:
        md_path = paths[smp["source"]]
        pairs = [(p["label"], p["value"]) for p in smp["pairs"]]
        if md_path is None:
            flags, flat_text, doc_chunks = [False] * len(pairs), "", []
        else:
            md_text = md_path.read_text(encoding="utf-8")
            flags, _ = M.calculate_table_detection(M.markdown_table_blocks(md_text), pairs, text=md_text)
            entry = flat[str(md_path)]
            flat_text = entry["flattened"]
            key = source_key(smp["source"])
            doc_chunks = entry.get("chunks") or [
                c["text"] for c in dump
                if key in source_key(c.get("source", "")) or key in source_key(c.get("document_title", ""))
            ]
        for (label, value), detected in zip(pairs, flags):
            records.append({
                "source": smp["source"], "kind": smp.get("kind"), "group": smp.get("group", "base"),
                "label": label, "value": value, "detected": detected,
                "flatten_ok": M.table_pair_present([flat_text], label, value) if flat_text else False,
                "e2e_ok": M.table_pair_present(doc_chunks, label, value) if doc_chunks else None,
            })
    return {
        "title": system.get("title", name),
        "all": parsing_summary(records),
        "base": parsing_summary([r for r in records if r["group"] == "base"]),
        "added": parsing_summary([r for r in records if r["group"] == "added"]),
        "records": records,
    }


def render_parsing(out: dict[str, Any], tag: str) -> str:
    pct = lambda v: "-" if v is None else f"{v * 100:.1f}%"
    lines = [f"### 표 지표 — 단계별 ({tag})", "",
             "| 시스템 | 표본 | 표 검출률 (로더) | 평탄화·정리 정합률 (검출된 쌍 중) | 종단 정합률 (최종 청크) |",
             "|---|---|---|---|---|"]
    for d in out.values():
        for label, key in (("전체", "all"), ("기존 10표", "base"), ("추가분", "added")):
            s = d[key]
            if not s["pairs_n"]:
                continue
            lines.append(
                f"| {d['title']} | {label} ({s['pairs_n']}쌍) | {pct(s['detection_rate'])} ({s['detected_n']}/{s['pairs_n']}) "
                f"| {pct(s['flatten_ok_of_detected'])} ({s['flatten_ok_n']}/{s['detected_n']}) "
                f"| {pct(s['end_to_end_rate'])} ({s['end_to_end_n']}/{s['pairs_n']}) |")
    return "\n".join(lines) + "\n"


def run_parsing(systems: list[dict], samples_path: Path, out_dir: Path, tag: str) -> str:
    """시스템 목록을 측정해 `parsing_<tag>.json`·`.md`를 쓰고 Markdown 표를 돌려준다."""
    samples = yaml.safe_load(Path(samples_path).read_text(encoding="utf-8")) or []
    out_dir.mkdir(parents=True, exist_ok=True)
    out = {s["name"]: evaluate_system(s, samples, out_dir, tag) for s in systems}
    (out_dir / f"parsing_{tag}.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    text = render_parsing(out, tag)
    (out_dir / f"parsing_{tag}.md").write_text(text, encoding="utf-8")
    return text


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "_flatten_files":  # 내부용: 대상 프로젝트 루트에서 호출됨
        ap = argparse.ArgumentParser()
        ap.add_argument("_cmd")
        ap.add_argument("--project-root", required=True)
        ap.add_argument("--spec", required=True)
        ap.add_argument("--out", required=True)
        a = ap.parse_args()
        return flatten_files(a.project_root, a.spec, a.out)

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project-root", default=".", help="측정할 프로젝트 체크아웃(기본: 현재 폴더)")
    ap.add_argument("--loader-md-dir", required=True, help="프로젝트 루트 기준 로더 Markdown 출력 폴더")
    ap.add_argument("--loader-md-glob", default="*.md", help="폴더 안에서 볼 파일 패턴(기본 *.md)")
    ap.add_argument("--rechunk", action="store_true",
                    help="프로젝트의 scripts/parser_bridge.py로 재청킹해 종단 정합률 계산(DB 미사용)")
    ap.add_argument("--chunk-dump", help="재청킹을 못 쓸 때 종단 정합률 계산에 쓸 청크 덤프 JSON")
    ap.add_argument("--name", default="system", help="결과에 붙일 시스템 이름")
    ap.add_argument("--title", help="표에 보일 이름(기본: --name)")
    ap.add_argument("--samples", default=str(DEFAULT_SAMPLES), help="정답 쌍 YAML")
    ap.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR), help="결과 폴더")
    ap.add_argument("--tag", default="run", help="결과 파일 꼬리표(예: before/after)")
    a = ap.parse_args()
    system = {"name": a.name, "title": a.title or a.name, "project_root": a.project_root,
              "loader_md_dir": a.loader_md_dir, "loader_md_glob": a.loader_md_glob,
              "rechunk": a.rechunk, "chunk_dump": a.chunk_dump}
    print(run_parsing([system], Path(a.samples), Path(a.out_dir), a.tag))


if __name__ == "__main__":
    main()
