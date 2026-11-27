"""Langfuse에 쌓인 질의 기록으로 방식별 시간과 토큰 비용을 집계한다(측정 방법: docs/11_비용측정.md).

사용 예:
    python scripts/cost_report.py --run-id cost1 --systems current_default current_multi_agent --context 8192
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def summarize(observations: list[dict]) -> dict:
    """한 세션의 Langfuse 관측(질문 span과 LLM generation)을 비용 지표로 묶는다."""
    questions = [o for o in observations if o["name"] == "rag-question"]
    calls = [o for o in observations if o["name"] == "llm"]
    usage = lambda o, key: (o.get("usageDetails") or {}).get(key, 0)
    per_trace: dict[str, int] = defaultdict(int)
    for call in calls:
        per_trace[call["traceId"]] += 1
    seconds = sorted(q["latency"] for q in questions)
    total = sum(seconds)
    single = [q["latency"] for q in questions if per_trace[q["traceId"]] <= 1]
    multi = [q["latency"] for q in questions if per_trace[q["traceId"]] > 1]
    mean = lambda values: round(statistics.mean(values), 1) if values else None
    return {
        "questions": len(questions),
        "llm_calls": len(calls),
        "failed_calls": sum(o.get("level") == "ERROR" for o in calls),
        "total_seconds": round(total, 1),
        "mean_seconds": mean(seconds),
        "median_seconds": round(statistics.median(seconds), 1) if seconds else None,
        "max_seconds": round(seconds[-1], 1) if seconds else None,
        "llm_share_percent": round(100 * sum(c["latency"] for c in calls) / total, 1) if total else None,
        "single_call_questions": len(single),
        "single_call_mean_seconds": mean(single),
        "multi_call_questions": len(multi),
        "multi_call_mean_seconds": mean(multi),
        "input_tokens": sum(usage(c, "input") for c in calls),
        "output_tokens": sum(usage(c, "output") for c in calls),
        "max_input_tokens": max((usage(c, "input") for c in calls), default=0),
        "max_context_tokens": max((usage(c, "input") + usage(c, "output") for c in calls), default=0),
        "records_with_text": sum(bool(o.get("input")) or bool(o.get("output")) for o in observations),
    }


def fetch(session: str, hours: float) -> list[dict]:
    from langfuse import Langfuse

    api = Langfuse().api.observations
    since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=hours)
    rows: list[dict] = []
    cursor = None
    while True:
        page = api.get_many(fields="core,basic,usage,metadata,io,model,time,metrics,trace_context",  # latency는 metrics에 있다
                            from_start_time=since, limit=100, cursor=cursor)
        rows += [o if isinstance(o, dict) else o.dict() for o in page.data]
        meta = page.meta if isinstance(page.meta, dict) else page.meta.dict()
        cursor = meta.get("cursor")
        if not cursor:
            break
    return [o for o in rows if o.get("sessionId") == session]


def gpu_peak(path: Path) -> int | None:
    if not path.exists():
        return None
    used = [int(line.split(",")[1]) for line in path.read_text().splitlines() if line.count(",") >= 2]
    return max(used, default=None)


def main() -> None:
    from dotenv import load_dotenv

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--systems", nargs="+", required=True)
    ap.add_argument("--context", type=int, required=True, help="Ollama 컨텍스트 크기(토큰)")
    ap.add_argument("--hours", type=float, default=24, help="최근 몇 시간의 기록에서 찾을지")
    args = ap.parse_args()
    load_dotenv(REPO_ROOT / ".env", override=False)

    run_dir = REPO_ROOT / "eval_resources" / "experiment_runs" / args.run_id
    report = {}
    for system in args.systems:
        raw = json.loads((run_dir / f"{system}_raw.json").read_text(encoding="utf-8"))
        expected = (len(raw), sum(e["stage"] == "llm" for r in raw for e in r["trace"]))
        for attempt in range(12):  # Langfuse에 기록이 보이기까지 시간이 걸린다
            summary = summarize(fetch(f"{args.run_id}:{system}", args.hours))
            if (summary["questions"], summary["llm_calls"]) == expected:
                break
            time.sleep(10)
        else:
            print(f"경고: {system} 기록 수가 로컬과 다릅니다(로컬 질문 {expected[0]}, 호출 {expected[1]}).", file=sys.stderr)
        summary["answer_errors"] = sum("error" in r for r in raw)
        summary["context"] = args.context
        summary["gpu_peak_mib"] = gpu_peak(run_dir / f"{system}_gpu.csv")
        report[system] = summary

    (run_dir / "cost_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    keys = list(next(iter(report.values())))
    print("| 항목 | " + " | ".join(report) + " |")
    print("|---|" + "---|" * len(report))
    for key in keys:
        print(f"| {key} | " + " | ".join(str(report[s][key]) for s in report) + " |")


if __name__ == "__main__":
    main()
