"""전체 실행 한 번의 팀 지표와 비용을 `eval_resources/eval_history.jsonl`에 한 줄로 남긴다.

같은 run id를 다시 넣으면 그 줄을 바꿔 맨 뒤에 둔다. 마지막 줄이 현재 결과다.

사용 예:
    python scripts/eval_history.py --run-id eval_20261127 --commit 3d9c004 --rubric v5
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
HISTORY = REPO_ROOT / "eval_resources" / "eval_history.jsonl"
PRICE_IN, PRICE_OUT = 0.075, 0.30  # Groq openai/gpt-oss-20b, 100만 token당 달러(docs/11_비용측정.md)


def build_entry(run_id: str, commit: str, rubric: str, summary: dict, cost: dict) -> dict:
    systems = {}
    for name, data in summary["systems"].items():
        m, c = data["metrics"], cost[name]
        systems[name] = {
            "n_scored": m["n_scored"],
            "correctness": m["correctness_all"],
            "answer_coverage": m["answer_coverage_all"],
            "faithfulness": m["faithfulness_all"],
            "context_relevance": m["context_relevance_all"],
            "source_recall_at_5": m["source_recall_at_k"],
            "source_mrr": m["source_mrr"],
            "chunk_recall_at_5": m["chunk_recall_at_k"],
            "chunk_recall_n": m["chunk_recall_labeled_n"],
            "chunk_recall_at_5_searched": m["chunk_recall_at_k_searched"],
            "chunk_recall_searched_n": m["chunk_recall_searched_n"],
            "latency_sec": {"analyze": m["latency_analyze_sec"], "retrieve": m["latency_retrieve_sec"],
                            "evidence": m["latency_evidence_sec"], "generate": m["latency_generate_sec"],
                            "wall": m["latency_wall_sec"]},
            "total_seconds": c["total_seconds"],
            "llm_calls": c["llm_calls"],
            "input_tokens": c["input_tokens"],
            "output_tokens": c["output_tokens"],
            "estimated_price_usd": round((c["input_tokens"] * PRICE_IN + c["output_tokens"] * PRICE_OUT) / 1_000_000, 4),
        }
    return {"run_id": run_id, "commit": commit, "rubric": rubric, "top_k": summary["top_k"], "systems": systems}


def upsert(path: Path, entry: dict) -> None:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()] if path.exists() else []
    rows = [r for r in rows if r.get("run_id") != entry["run_id"]] + [entry]
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--commit", required=True, help="답변을 만든 코드의 commit")
    ap.add_argument("--rubric", required=True)
    ap.add_argument("--out", default=str(HISTORY))
    a = ap.parse_args()
    run_dir = REPO_ROOT / "eval_resources" / "experiment_runs" / a.run_id
    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    cost = json.loads((run_dir / "cost_report.json").read_text(encoding="utf-8"))
    upsert(Path(a.out), build_entry(a.run_id, a.commit, a.rubric, summary, cost))
    print(f"{a.out}에 {a.run_id} 기록")


if __name__ == "__main__":
    main()
