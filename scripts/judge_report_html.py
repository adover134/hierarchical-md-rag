"""Claude 채점 한 회차를 팀의 HTML 보고서(`scripts/build_eval_report.py`)로 만든다.

채점 입력(질문, 기대 답변, context, 생성 답변)과 채점 결과(4개 축 점수와 사유)를 문항별로 보여준다.
저장된 파일만 읽고 점수를 바꾸지 않는다. 방식마다 `eval_resources/eval_results_<label>.json`과
`eval_resources/eval_report_<label>.html`을 만든다(둘 다 git 제외).

사용 예:
    python scripts/judge_report_html.py --round-dir eval_resources/claude_judge/round19
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path

from build_eval_report import build_html

REPO_ROOT = Path(__file__).resolve().parent.parent
RUNS_DIR = REPO_ROOT / "eval_resources" / "experiment_runs"
AXES = ("correctness", "answer_coverage", "faithfulness", "context_relevance")
SYSTEM_NAMES = {"current_default": "two_stage", "current_multi_agent": "multi_agent"}


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def build_results(round_dir: Path, run: str, system: str, dataset: dict, runs_dir: Path = RUNS_DIR) -> dict:
    """한 실행의 한 방식을 팀의 `eval_results` 형식으로 바꾼다. `judge_context`는 채점자가 받은 context다."""
    mapping = json.loads(_read(round_dir / "mapping.json"))
    items, scores, batch_of = {}, {}, {}
    for f in sorted((round_dir / "batches").glob("batch_*.json")):
        for item in json.loads(_read(f)):
            items[item["item_id"]], batch_of[item["item_id"]] = item, f.stem
    for f in sorted((round_dir / "results").glob("batch_*.json")):
        scores.update(json.loads(_read(f)))

    run_dir = runs_dir / run
    raw = {(r["dataset"], r["id"]): r for r in json.loads(_read(run_dir / f"{system}_raw.json"))}
    summary = json.loads(_read(run_dir / "summary.json"))
    metrics = summary["systems"][system]["metrics"]
    rows = {(r["dataset"], r["id"]): r for r in summary["systems"][system]["per_query"]}

    per_query = []
    for item_id, origin in mapping.items():
        if (origin["run"], origin["system"]) != (run, system):
            continue
        key = (origin["dataset"], origin["id"])
        item, record, row, question = items[item_id], raw[key], rows[key], dataset[key]
        sources = [str(d.get("source", "")) for d in record.get("retrieved_docs") or []]
        per_query.append({
            "id": key[1], "question": item["question"], "query_type": question.get("query_type", "unknown"),
            "memo": f"{batch_of[item_id]} · {item_id}",
            "expected_answer": item["expected_answer"], "generated_answer": item["generated_answer"],
            "judge_context": item["context"],
            **({"verification": item["검증 결과"]} if "검증 결과" in item else {}),
            **{ax: scores[item_id][ax] for ax in AXES},
            "hit_position": row.get("source_hit_position"), "recall_at_k": row.get("source_recall"), "ndcg": row.get("source_ndcg"),
            "recall_at_k_chunk": row.get("chunk_recall"), "num_retrieved": len(sources),
            "csv_short_circuit": record.get("csv_short_circuit", False), "source_type": record.get("source_type", ""),
            "ground_truth_sources": question.get("ground_truth", {}).get("sources", []),
            "retrieved_sources": list(dict.fromkeys(sources)), "latencies": record.get("latencies", {}),
        })
    per_query.sort(key=lambda q: (q["id"][0], int("".join(c for c in q["id"] if c.isdigit()) or 0)))
    label = f"{run}_{SYSTEM_NAMES.get(system, system)}"
    return {
        "summary": {
            "num_queries": metrics["n_queries"], "num_evaluated": metrics["n_scored"], "top_k": summary["top_k"],
            "avg_correctness": metrics["correctness_all"], "avg_answer_coverage": metrics["answer_coverage_all"],
            "avg_faithfulness": metrics["faithfulness_all"], "avg_context_relevance": metrics["context_relevance_all"],
            "recall_at_k_source": metrics["source_recall_at_k"], "ndcg_source": metrics["source_ndcg"],
            "recall_at_k_chunk": metrics["chunk_recall_at_k"], "num_chunk_labeled_queries": metrics["chunk_recall_labeled_n"],
        },
        "per_query": per_query,
        "meta": {
            "label": f"{label} · {round_dir.name}", "judge_model": "Claude(격리 호출, Opus)" if (round_dir / "calls.json").exists() else "Claude(subagent, Opus)",
            "generated": dt.date.today().isoformat(), "elapsed_seconds": "-", "insights": False,
            "rubric": _read(round_dir / "rubric.md"), "instruction": _read(round_dir / "instruction.txt"),
            "grader_note": _read(round_dir / "grader_note.txt"),
        },
    }


def main() -> None:
    from claude_judge import _load_dataset_items

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--round-dir", required=True)
    a = ap.parse_args()
    round_dir = Path(a.round_dir)
    mapping = json.loads(_read(round_dir / "mapping.json"))
    dataset = _load_dataset_items()
    for run, system in sorted({(o["run"], o["system"]) for o in mapping.values()}):
        results = build_results(round_dir, run, system, dataset)
        label = f"{run}_{SYSTEM_NAMES.get(system, system)}"
        out = REPO_ROOT / "eval_resources"
        (out / f"eval_results_{label}.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        page = build_html(results).replace("<\\/script>", "</script>")  # 팀 script의 main과 같은 후처리
        (out / f"eval_report_{label}.html").write_text(page, encoding="utf-8")
        print(out / f"eval_report_{label}.html")


if __name__ == "__main__":
    main()
