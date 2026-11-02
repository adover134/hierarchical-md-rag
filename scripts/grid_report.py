"""3x2 비교(프로세스 3 x DB 2) 보고서 생성기.

`<run>/<system>_raw.json`(저장된 답변)과 `<run>/judge_cache/<system>/`(Claude 채점)을 읽어
  1. 칸별 평균 점수 표, 2. DB 효과(프로세스별) / 프로세스 효과(DB별) 쌍체 비교, 3. 문항별 조합 답변 부록
을 마크다운으로 쓴다. 채점은 항상 Claude 서브에이전트(`scripts/claude_judge.py`)가 만든 캐시만 읽는다.

사용 예:
    python scripts/grid_report.py --run-id dbcmp6 --summary-out /tmp/summary.md --answers-out docs/dbcmp6_answers.md
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
RUNS_DIR = REPO_ROOT / "eval_resources" / "experiment_runs"
AXES = ("correctness", "answer_coverage", "faithfulness", "context_relevance")
AXIS_KO = {"correctness": "Correctness", "answer_coverage": "Answer coverage",
           "faithfulness": "Faithfulness", "context_relevance": "Context relevance"}
PROCESSES = (("team", "팀 프로세스"), ("proc", "main(two_stage)"), ("multi", "멀티 에이전트"))
DBS = (("team_db", "팀 DB"), ("cur_db", "현재 DB(main2)"))
DATASETS = {"new20": "eval_dataset_new20.yaml", "new20_v2": "eval_dataset_new20_v2.yaml"}


def cell_name(proc: str, db: str) -> str:
    return f"{proc}_on_{db}"


def paired_summary(a: list[float], b: list[float]) -> dict:
    """같은 문항에 대한 두 점수열(b - a)의 평균 차이, 부호 검정 p값(양측), 늘어난/줄어든/같은 문항 수."""
    diffs = [y - x for x, y in zip(a, b)]
    up, down = sum(d > 0 for d in diffs), sum(d < 0 for d in diffs)
    n = up + down
    p = 1.0
    if n:
        k = min(up, down)
        p = min(1.0, 2 * sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n)
    return {"mean_diff": sum(diffs) / len(diffs) if diffs else 0.0, "up": up, "down": down,
            "same": len(diffs) - n, "p": p}


def load_scores(run: str, system: str) -> dict[tuple[str, str], dict[str, int]]:
    out = {}
    for f in sorted((RUNS_DIR / run / "judge_cache" / system).glob("*.json")):
        ds, qid, _ = f.stem.split("__")
        j = json.loads(f.read_text(encoding="utf-8"))
        out[(ds, qid)] = {ax: int(j[ax]["score"]) for ax in AXES}
    return out


def load_raw(run: str, system: str) -> dict[tuple[str, str], dict]:
    return {(r["dataset"], r["id"]): r for r in json.loads((RUNS_DIR / run / f"{system}_raw.json").read_text(encoding="utf-8"))}


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else float("nan")


def summary_table(scores: dict[str, dict]) -> str:
    head = "| 프로세스 | DB | " + " | ".join(AXIS_KO[a] for a in AXES) + " | Correctness 5점 문항 |"
    lines = [head, "|" + "---|" * (len(AXES) + 3)]
    for p, pname in PROCESSES:
        for d, dname in DBS:
            sc = scores[cell_name(p, d)]
            vals = " | ".join(f"{_mean([v[a] for v in sc.values()]):.3f}" for a in AXES)
            full = sum(v["correctness"] == 5 for v in sc.values())
            lines.append(f"| {pname} | {dname} | {vals} | {full}/{len(sc)} |")
    return "\n".join(lines)


def effect_table(scores: dict[str, dict], axis: str) -> str:
    keys = sorted(next(iter(scores.values())))
    def col(system):
        return [scores[system][k][axis] for k in keys]
    rows = ["| 비교 | 평균 차이 | 올라간/내려간/같음 | p (부호검정) |", "|---|---|---|---|"]
    for p, pname in PROCESSES:
        r = paired_summary(col(cell_name(p, "team_db")), col(cell_name(p, "cur_db")))
        rows.append(f"| DB 효과, {pname}: 팀 DB → 현재 DB | {r['mean_diff']:+.3f} | {r['up']}/{r['down']}/{r['same']} | {r['p']:.3f} |")
    for d, dname in DBS:
        for (pa, na), (pb, nb) in ((PROCESSES[0], PROCESSES[1]), (PROCESSES[1], PROCESSES[2]), (PROCESSES[0], PROCESSES[2])):
            r = paired_summary(col(cell_name(pa, d)), col(cell_name(pb, d)))
            rows.append(f"| 프로세스 효과, {dname}: {na} → {nb} | {r['mean_diff']:+.3f} | {r['up']}/{r['down']}/{r['same']} | {r['p']:.3f} |")
    return "\n".join(rows)


def answers_appendix(run: str, scores: dict[str, dict], raws: dict[str, dict]) -> str:
    items = {}
    for ds, fname in DATASETS.items():
        for q in yaml.safe_load((REPO_ROOT / "eval_resources" / fname).read_text(encoding="utf-8")):
            items[(ds, q["id"])] = q
    out = [f"# {run} 문항별 조합 답변 (심사: Claude 서브에이전트)", "",
           "칸 이름은 `프로세스 × DB`이고, 괄호 안은 Claude 채점의 Correctness(0~5)이다. 답변은 저장된 원문 그대로다.", ""]
    for key in sorted(items, key=lambda k: (k[0], int(k[1][1:]))):
        q = items[key]
        out += [f"## {key[0]} / {key[1]}", f"- 질문: {q['question']}", f"- 기대 답변: {q.get('expected_answer', '')}"]
        for p, pname in PROCESSES:
            for d, dname in DBS:
                s = cell_name(p, d)
                ans = (raws[s].get(key, {}).get("answer") or "").strip().replace("\n", " ")
                out.append(f"- {pname} × {dname} (C={scores[s][key]['correctness']}): {ans}")
        out.append("")
    return "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--summary-out", required=True)
    ap.add_argument("--answers-out", required=True)
    a = ap.parse_args()
    cells = [cell_name(p, d) for p, _ in PROCESSES for d, _ in DBS]
    scores = {c: load_scores(a.run_id, c) for c in cells}
    raws = {c: load_raw(a.run_id, c) for c in cells}
    parts = ["## 칸별 평균 (Claude 채점)", summary_table(scores)]
    for ax in AXES:
        parts += ["", f"## 쌍체 비교: {AXIS_KO[ax]}", effect_table(scores, ax)]
    Path(a.summary_out).write_text("\n".join(parts) + "\n", encoding="utf-8")
    Path(a.answers_out).write_text(answers_appendix(a.run_id, scores, raws) + "\n", encoding="utf-8")
    print(f"요약 {a.summary_out}, 부록 {a.answers_out}")


if __name__ == "__main__":
    main()
