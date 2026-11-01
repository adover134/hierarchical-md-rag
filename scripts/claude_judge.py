"""Claude 서브에이전트 채점용 내보내기 / 가져오기.

생성은 로컬 gpt-oss:20b가 하고, 채점은 항상 Claude가 한다(별도 API 키 없이 서브에이전트가 채점). 이 스크립트는 그 중간 단계다.

  export  저장된 답변(`<run>/<system>_raw.json`)을 시스템·실행 식별 없이 섞어 배치 파일로 내보낸다. 루브릭(`rubric.md`)과 매핑도 함께 쓴다.
          서브에이전트는 배치 파일마다 채점해 `results/batch_XX.json`을 쓴다.
  import  결과를 검증하고 `run_experiment.py evaluate`가 읽는 캐시(`<run>/judge_cache/<system>/…json`)로 옮긴다.
          기존 gpt-oss 채점 캐시는 `judge_cache_gptoss_ref/`로 옮겨 참고용으로 남기고, 기존 summary.json도 `summary_gptoss_ref.json`으로 둔다.

사용 예:
    python scripts/claude_judge.py export --runs dbcmp3:proc_on_cur_db dbcmp4:proc_on_cur_db --out-dir eval_resources/claude_judge/round1
    python scripts/claude_judge.py import --out-dir eval_resources/claude_judge/round1
"""

from __future__ import annotations

import argparse
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

INSTRUCTIONS = """\
# 채점 지시

아래 루브릭으로 배치 파일의 항목을 하나씩 채점한다. 항목마다 질문, 기대 답변, 검색된 컨텍스트, 생성된 답변이 있다.

- 항목의 출처(어느 시스템·실행인지)는 알려지지 않았고 알려고 하지 않는다. 항목끼리 비교하지 말고 각 항목을 루브릭에만 비추어 독립적으로 채점한다.
- 점수는 0~5 정수. 4개 축(correctness, answer_coverage, faithfulness, context_relevance) 모두, 각각 한 문장 근거(reason)를 쓴다.
- Faithfulness와 Context Relevance는 항목의 `context` 필드만 기준으로 한다. 외부 지식으로 답이 맞는지 추측하지 않는다.
- 기대 답변과 의미가 같으면 표현이 달라도 감점하지 않는다. 기대 답변의 핵심 값이 틀리면 Correctness를 낮게 준다.
- 결과는 JSON 파일 하나로 쓴다: `{"<item_id>": {"correctness": {"score": 0, "reason": "..."}, "answer_coverage": {...}, "faithfulness": {...}, "context_relevance": {...}}, ...}`.
  배치의 모든 item_id가 빠짐없이 들어 있어야 한다.

---

"""


def _context(rec: dict, k: int) -> str:
    texts = [str(d.get("content", "")) for d in (rec.get("retrieved_docs") or [])[:k]]
    return "\n\n".join(p for p in (rec.get("evidence", ""), "\n\n".join(t for t in texts if t)) if p)


def build_items(
    records: dict[tuple[str, str], list[dict]], dataset_items: dict[tuple[str, str], dict], k: int, seed: int
) -> tuple[list[dict], dict[str, dict]]:
    """(run, system)별 기록을 하나로 합쳐 섞고 항목 번호를 새로 붙인다. 번호는 출처와 무관해서 채점자는 어느 시스템인지 알 수 없다."""
    rows: list[tuple[dict, dict]] = []
    for (run, system), recs in records.items():
        for rec in recs:
            item = dataset_items.get((rec.get("dataset"), rec.get("id")))
            if item is None or rec.get("error"):
                continue
            body = {
                "question": item["question"],
                "expected_answer": item.get("expected_answer", ""),
                "context": _context(rec, k),
                "generated_answer": rec.get("answer", ""),
            }
            origin = {"run": run, "system": system, "dataset": rec["dataset"], "id": rec["id"], "repeat": rec.get("repeat", 1)}
            rows.append((body, origin))
    random.Random(seed).shuffle(rows)
    items, mapping = [], {}
    for n, (body, origin) in enumerate(rows, start=1):
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
    sys.path.insert(0, str(REPO_ROOT))
    from src.evaluation.llm_judge import JUDGE_SYSTEM_PROMPT

    records = {}
    for spec in a.runs:
        run, system = spec.split(":", 1)
        records[(run, system)] = json.loads((RUNS_DIR / run / f"{system}_raw.json").read_text(encoding="utf-8"))
    items, mapping = build_items(records, _load_dataset_items(), a.k, a.seed)
    out = Path(a.out_dir)
    (out / "batches").mkdir(parents=True, exist_ok=True)
    (out / "results").mkdir(exist_ok=True)
    (out / "rubric.md").write_text(INSTRUCTIONS + JUDGE_SYSTEM_PROMPT, encoding="utf-8")
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
    for item_id, origin in mapping.items():
        run_dir = RUNS_DIR / origin["run"]
        cache = run_dir / "judge_cache" / origin["system"]
        ref = run_dir / "judge_cache_gptoss_ref" / origin["system"]
        if (origin["run"], origin["system"]) not in touched:
            touched.add((origin["run"], origin["system"]))
            if cache.exists() and not ref.exists():
                ref.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(cache), str(ref))
            if (run_dir / "summary.json").exists() and not (run_dir / "summary_gptoss_ref.json").exists():
                shutil.copy(run_dir / "summary.json", run_dir / "summary_gptoss_ref.json")
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
    e.set_defaults(fn=cmd_export)
    i = sub.add_parser("import")
    i.add_argument("--out-dir", required=True)
    i.set_defaults(fn=cmd_import)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
