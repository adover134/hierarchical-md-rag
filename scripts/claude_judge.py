"""Claude 서브에이전트 채점용 내보내기 / 가져오기.

생성은 로컬 gpt-oss:20b가 하고, 채점은 항상 Claude가 한다(별도 API 키 없이 서브에이전트가 채점). 이 스크립트는 그 중간 단계다.

  export  저장된 답변(`<run>/<system>_raw.json`)을 시스템·실행 식별 없이 섞어 배치 파일로 내보낸다. 루브릭(`rubric.md`)과 매핑도 함께 쓴다.
          루브릭은 팀 rubric(`src/evaluation/llm_judge.py`)에 추가 기준 5개를 붙인 것이다(docs/judge_rules.md).
          서브에이전트는 배치 파일마다 채점해 `results/batch_XX.json`을 쓴다.
  import  결과를 검증하고 `run_experiment.py evaluate`가 읽는 캐시(`<run>/judge_cache/<system>/…json`)로 옮긴다.
          기존 gpt-oss 채점 캐시는 `judge_cache_gptoss_ref/`로 옮겨 참고용으로 남기고, 기존 summary.json도 `summary_gptoss_ref.json`으로 둔다.

사용 예:
    python scripts/claude_judge.py export --runs dbcmp3:proc_on_cur_db dbcmp4:proc_on_cur_db --out-dir eval_resources/claude_judge/round1
    python scripts/claude_judge.py import --out-dir eval_resources/claude_judge/round1
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import shutil
import sys
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
RUNS_DIR = REPO_ROOT / "eval_resources" / "experiment_runs"
DATASETS = ("eval_resources/eval_dataset_new20.yaml", "eval_resources/eval_dataset_new20_v2.yaml")
AXES = ("correctness", "answer_coverage", "faithfulness", "context_relevance")
# 큰 번호는 프로젝트 버전이 바뀔 때만 올리고, 같은 프로젝트 버전 안의 변경은 소수점 뒤를 올린다.
RUBRIC_VERSION = "v6.2"

EXTRA_CRITERIA = """

## 추가 기준
1. Correctness는 기대 답변의 주된 값(괄호 밖의 값과 사실)으로 판단한다.
   괄호 안의 값이 빠지거나 달라도 Correctness를 깎지 않는다.
   괄호 밖의 값과 사실은 모두 있어야 한다.
2. 비교 질문의 답은 비교 결과다. 비교의 근거가 된 값이 답변에 없어도
   Correctness와 Answer coverage를 깎지 않는다.
3. 질문이 묻는 금액의 이름과 답변이나 context가 쓴 이름이 달라도(예: 기초금액을 사업비로)
   값이 같으면 Correctness, Answer coverage, Context relevance를 깎지 않는다.
4. 질문에 적힌 사업 이름과 context의 공고명이나 문서 이름이 달라도, 그것만으로 다른 문서나 다른 사업이라고
   판단하지 않는다. 답변이 문서나 context의 공고명, 기관명을 쓴 것도 감점하지 않는다.
   공고명 말고도 다른 문서임을 보여 주는 내용(질문과 다른 기관, 질문과 무관한 본문)이 있으면 그 내용으로 판단한다.
   이 기준은 네 축 모두에 적용한다.
5. Context relevance는 기대 답변에서 context 방향으로 판단한다.
   질문의 공고(검증 결과의 공고)에서 온 context에 기대 답변의 주된 값(괄호 밖의 값과 사실)이 있으면 5점이고,
   함께 있는 다른 내용은 깎지 않는다. 확인되지 않는 정도에 따라 깎는다.
   다른 공고의 context는 값이 같아도 인정하지 않는다.
"""


def rubric_text() -> str:
    """채점자가 읽는 `rubric.md`: 팀 rubric 그대로에 승인받은 추가 기준 5개만 붙인다."""
    sys.path.insert(0, str(REPO_ROOT))
    from src.evaluation.llm_judge import JUDGE_SYSTEM_PROMPT

    return JUDGE_SYSTEM_PROMPT + EXTRA_CRITERIA


def chunk_metadata(db_path: Path) -> dict[str, dict]:
    """DB의 chunk id별 metadata(읽기만 한다)."""
    import chromadb

    got = chromadb.PersistentClient(path=str(db_path)).get_collection("chunks").get(include=["metadatas"])
    return dict(zip(got["ids"], got["metadatas"]))


def shortcut_metadata(csv_path: Path) -> dict[str, dict]:
    """단축 경로 답의 문서(파일 이름)별 metadata. DB와 같이 `org`는 공고명, `project_name`은 기관명이다."""
    with open(csv_path, encoding="utf-8-sig", newline="") as f:
        return {r["파일명"]: {"source": r["파일명"], "org": r["공고명"], "project_name": r["공고기관"]} for r in csv.DictReader(f)}


def _header(doc: dict, chunks: dict, rows: dict) -> str:
    """답변 모델의 prompt에 붙는 머리글과 같은 형식(src/graph/workflow.py의 `_build_context`)."""
    md = chunks.get(str(doc.get("chunk_id"))) or rows.get(doc.get("source")) or {}
    source = md.get("source") or doc.get("source") or "Unknown"
    page = doc.get("page")  # 검색 결과의 쪽 번호(prompt의 p.N)
    header = f"[{md.get('org', '')} - {source}{f' p.{page}' if page is not None else ''}]"
    project_name = md.get("project_name") or md.get("사업명")
    if project_name:
        header += f" | project={project_name}"
    if md.get("notice_num"):
        header += f" | notice={md['notice_num']}"
    return header


def _context(rec: dict, k: int, chunks: dict, rows: dict) -> str:
    texts = [f"{_header(d, chunks, rows)}\n{d.get('content', '')}"
             for d in (rec.get("retrieved_docs") or [])[:k] if d.get("content")]
    return "\n\n".join(p for p in (rec.get("evidence", ""), "\n\n".join(texts)) if p)


def build_items(
    records: dict[tuple[str, str], list[dict]], dataset_items: dict[tuple[str, str], dict], k: int, seed: int,
    chunks: dict | None = None, rows: dict | None = None,
) -> tuple[list[dict], dict[str, dict]]:
    """(run, system)별 기록을 하나로 합쳐 섞고 항목 번호를 새로 붙인다. 번호는 출처와 무관해서 채점자는 어느 시스템인지 알 수 없다."""
    collected: list[tuple[dict, dict]] = []
    for (run, system), recs in records.items():
        for rec in recs:
            item = dataset_items.get((rec.get("dataset"), rec.get("id")))
            if item is None or rec.get("error"):
                continue
            body = {
                "question": item["question"],
                "expected_answer": item.get("expected_answer", ""),
                "context": _context(rec, k, chunks or {}, rows or {}),
                "generated_answer": rec.get("answer", ""),
            }
            origin = {"run": run, "system": system, "dataset": rec["dataset"], "id": rec["id"], "repeat": rec.get("repeat", 1)}
            collected.append((body, origin))
    random.Random(seed).shuffle(collected)
    items, mapping = [], {}
    for n, (body, origin) in enumerate(collected, start=1):
        item_id = f"j{n:04d}"
        items.append({"item_id": item_id, **body})
        mapping[item_id] = origin
    return items, mapping


def split_batches(items: list, size: int) -> list[list]:
    return [items[i:i + size] for i in range(0, len(items), size)]


def validate_results(results: dict[str, Any], expected_ids: list[str]) -> list[str]:
    """결과의 빠진 항목, 모르는 항목, 빠진 축, 0~5 정수가 아닌 점수를 문제 목록으로 돌려준다(비어 있으면 통과)."""
    problems = [f"빠진 항목 {i}" for i in expected_ids if i not in results]
    problems += [f"모르는 항목 {i}" for i in results if i not in set(expected_ids)]
    for item_id in expected_ids:
        entry = results.get(item_id)
        if not isinstance(entry, dict):
            continue
        for axis in AXES:
            node = entry.get(axis)
            if not isinstance(node, dict):
                problems.append(f"{item_id}: 축 {axis} 없음")
                continue
            score = node.get("score")
            if isinstance(score, bool) or not isinstance(score, int) or not 0 <= score <= 5:
                problems.append(f"{item_id}: {axis} 점수가 0~5 정수가 아님 ({score!r})")
            if not str(node.get("reason", "")).strip():
                problems.append(f"{item_id}: {axis} 근거 없음")
    return problems


def _load_dataset_items() -> dict[tuple[str, str], dict]:
    out = {}
    for path in DATASETS:
        name = Path(path).stem.replace("eval_dataset_", "")
        for q in yaml.safe_load((REPO_ROOT / path).read_text(encoding="utf-8")):
            out[(name, q["id"])] = q
    return out


def cmd_export(a: argparse.Namespace) -> None:
    records = {}
    for spec in a.runs:
        run, system = spec.split(":", 1)
        records[(run, system)] = json.loads((RUNS_DIR / run / f"{system}_raw.json").read_text(encoding="utf-8"))
    data_index = Path(a.data_index)
    items, mapping = build_items(records, _load_dataset_items(), a.k, a.seed,
                                 chunks=chunk_metadata(data_index / "chroma_B"),
                                 rows=shortcut_metadata(data_index / "metadata.csv"))
    out = Path(a.out_dir)
    (out / "batches").mkdir(parents=True, exist_ok=True)
    (out / "results").mkdir(exist_ok=True)
    (out / "rubric.md").write_text(rubric_text(), encoding="utf-8")
    (out / "rubric_version.txt").write_text(RUBRIC_VERSION + "\n", encoding="utf-8")
    (out / "mapping.json").write_text(json.dumps(mapping, ensure_ascii=False, indent=1), encoding="utf-8")
    batches = split_batches(items, a.batch_size)
    for n, batch in enumerate(batches, start=1):
        (out / "batches" / f"batch_{n:02d}.json").write_text(json.dumps(batch, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"항목 {len(items)}개 → 배치 {len(batches)}개 ({a.batch_size}개씩), 출력 {out}")


def cmd_import(a: argparse.Namespace) -> None:
    out = Path(a.out_dir)
    mapping = json.loads((out / "mapping.json").read_text(encoding="utf-8"))
    merged: dict[str, Any] = {}
    for f in sorted((out / "results").glob("batch_*.json")):
        merged.update(json.loads(f.read_text(encoding="utf-8")))
    problems = validate_results(merged, list(mapping))
    if problems:
        print("검증 실패:\n  " + "\n  ".join(problems[:40]))
        raise SystemExit(1)
    touched = set()
    # 이전 캐시를 어디에 남기는지: 지금 버전의 채점이면 이전 v6 채점을 `judge_cache_v6_ref`에,
    # 그 밖에는 이전 gpt-oss 채점을 `judge_cache_gptoss_ref`에 둔다.
    version_file = out / "rubric_version.txt"
    version = version_file.read_text(encoding="utf-8").strip() if version_file.exists() else ""
    previous = "v6" if version == RUBRIC_VERSION else "gptoss"
    ref_name, summary_ref = f"judge_cache_{previous}_ref", f"summary_{previous}_ref.json"
    for item_id, origin in mapping.items():
        run_dir = RUNS_DIR / origin["run"]
        cache = run_dir / "judge_cache" / origin["system"]
        ref = run_dir / ref_name / origin["system"]
        if (origin["run"], origin["system"]) not in touched:
            touched.add((origin["run"], origin["system"]))
            if cache.exists() and not ref.exists():
                ref.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(cache), str(ref))
            if (run_dir / "summary.json").exists() and not (run_dir / summary_ref).exists():
                shutil.copy(run_dir / "summary.json", run_dir / summary_ref)
            cache.mkdir(parents=True, exist_ok=True)
        (cache / f"{origin['dataset']}__{origin['id']}__{origin['repeat']}.json").write_text(
            json.dumps({ax: merged[item_id][ax] for ax in AXES}, ensure_ascii=False), encoding="utf-8")
    print(f"캐시 {len(mapping)}건 저장, 대상 {sorted(touched)}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("export")
    e.add_argument("--runs", nargs="+", required=True, help="<run-id>:<system> 형식")
    e.add_argument("--out-dir", required=True)
    e.add_argument("--batch-size", type=int, default=10)
    e.add_argument("--k", type=int, default=5, help="컨텍스트에 넣는 검색 청크 수(run_experiment의 top_k와 같게)")
    e.add_argument("--seed", type=int, default=20261102)
    e.add_argument("--data-index", default=str(REPO_ROOT / "data_index"), help="실행에 쓴 DB 폴더(머리글의 metadata를 읽는다)")
    e.set_defaults(fn=cmd_export)
    i = sub.add_parser("import")
    i.add_argument("--out-dir", required=True)
    i.set_defaults(fn=cmd_import)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
