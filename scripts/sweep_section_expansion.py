"""섹션 확장 설정(섹션 단위 × 글자 수 예산)을 훑어본다 — 검색은 다시 하지 않고 저장된 원시 검색 결과를 재사용한다.

`scripts/eval_retriever.py`가 만든 `raw_current_default.json`(질의별 상위 30개 청크)과 청크 덤프, 청크 정답(qrels)으로,
설정마다 "검색된 청크를 그 섹션 전체로 확장"했을 때의 지표를 계산한다. 확장된 섹션은 순위 한 칸을 차지하는 하나의 결과다.

사용 예:
    python scripts/sweep_section_expansion.py --raw-dir eval_resources/retrieval/run1 --snapshots ../hmr_db_snapshots
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
from eval_retriever import DATASETS, doc_run, map_qrels, section_units, source_key, to_run  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--raw-dir", required=True, help="eval_retriever 출력 폴더(raw_current_default.json 포함)")
    ap.add_argument("--snapshots", required=True)
    ap.add_argument("--levels", nargs="*", default=["section_uid", "section_level1"])
    ap.add_argument("--budgets", type=int, nargs="*", default=[1000, 1500, 2000, 3000, 100000])
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--out", help="결과 JSON 경로(선택)")
    a = ap.parse_args()

    from ranx import Qrels, Run, evaluate

    questions = [q for d in DATASETS for q in yaml.safe_load((REPO_ROOT / d).read_text(encoding="utf-8"))]
    ids = [q["id"] for q in questions]
    raw = json.loads((Path(a.raw_dir) / "raw_current_default.json").read_text(encoding="utf-8"))
    chunks = json.loads((Path(a.snapshots) / "current_default" / "chunks.json").read_text(encoding="utf-8"))
    chars = {c["uid"]: len(c["text"]) for c in chunks}
    qrels = json.loads((REPO_ROOT / "eval_resources/retrieval/qrels_current_default.json").read_text(encoding="utf-8"))["qrels"]
    doc_qrels = {q["id"]: {source_key(s): 1 for s in q["ground_truth"]["sources"]} for q in questions}
    k = a.k
    metrics = [f"hit_rate@1", f"hit_rate@{k}", f"recall@{k}", f"ndcg@{k}", f"mrr@{k}"]

    def score(unit_of):
        runs, qr, drun, totals, expanded = {}, {}, {}, [], 0
        for i in ids:
            rows = raw[i]
            run, _ = to_run(rows, unit_of, k, chars)
            runs[i] = run
            qr[i] = map_qrels(qrels[i], unit_of)
            drun[i] = doc_run(rows, k)
            _, total = to_run(rows, unit_of, k, chars)
            totals.append(total)
            members = {u: m["members"] for m in (unit_of or {}).values() for u in [m["unit"]]}
            top_units = list(run)
            if any(len(members.get(u, [u])) > 1 for u in top_units):
                expanded += 1
        chunk = {m: round(float(evaluate(Qrels.from_dict(qr), Run.from_dict(runs), m)), 3) for m in metrics}
        doc = {m: round(float(evaluate(Qrels.from_dict(doc_qrels), Run.from_dict(drun), m)), 3) for m in metrics}
        return {"chunk": chunk, "doc": doc, "avg_chars_top_k": round(sum(totals) / len(totals)), "queries_expanded": expanded}

    rows_out = {"확장 없음(현재)": score(None)}
    for level in a.levels:
        for budget in a.budgets:
            unit_of = section_units(chunks, level, budget)
            multi = len({m["unit"] for m in unit_of.values() if len(m["members"]) > 1})
            r = score(unit_of)
            r["expandable_sections"] = multi
            rows_out[f"{level} / 예산 {budget}"] = r

    head = f"{'설정':<34}{'확장 가능 섹션':>14}{'확장된 질의':>10}{'평균 글자':>9}" + "".join(f"{m:>13}" for m in metrics)
    print("[청크 단위]\n" + head)
    for name, r in rows_out.items():
        print(f"{name:<34}{r.get('expandable_sections', 0):>14}{r['queries_expanded']:>10}{r['avg_chars_top_k']:>9}"
              + "".join(f"{r['chunk'][m]:>13}" for m in metrics))
    print("\n[문서 단위]")
    for name, r in rows_out.items():
        print(f"{name:<34}" + "".join(f"{r['doc'][m]:>13}" for m in metrics))
    if a.out:
        Path(a.out).write_text(json.dumps(rows_out, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
