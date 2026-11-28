"""채점기 시험: 저장된 채점 회차에서 시험 묶음을 만들고, 채점 결과가 통과 기준에 맞는지 판정한다.

시험 항목은 답과 context를 일부러 바꾼 것이다. 점수는 답의 점수가 아니며 `claude_judge.py import`로 가져오지 않는다.

  build  원본 회차의 감점 항목 + 사례 file의 항목(context 바꿈, 값 바꿈, 감점 유지)에 검증 결과를 붙여 묶음을 만든다
  check  통과 기준: context 바꿈은 Context relevance 3점 이하, 값 바꿈은 Correctness와 Faithfulness 3점 이하,
         감점 유지는 지정한 축이 5점 미만. 하나라도 어긋나면 종료 code 1

사용 예:
    python scripts/judge_probe.py build --source-round eval_resources/claude_judge/<round> \\
        --verification eval_resources/claude_judge/<verify>/verification.json --out-dir eval_resources/claude_judge/<probe>
    python scripts/judge_grade.py --round-dir eval_resources/claude_judge/<probe>
    python scripts/judge_probe.py check --round-dir eval_resources/claude_judge/<probe>
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))

from claude_judge import AXES, RUBRIC_VERSION, rubric_text, split_batches  # noqa: E402
from judge_verify import attach  # noqa: E402

CASES_PATH = Path(__file__).resolve().parent.parent / "eval_resources" / "grader_probe_cases.yaml"
ORIGIN_KEYS = ("run", "system", "dataset", "id", "repeat")
RULES = {
    "context 바꿈": lambda scores, origin: scores["context_relevance"]["score"] <= 3,
    "값 바꿈": lambda scores, origin: max(scores["correctness"]["score"], scores["faithfulness"]["score"]) <= 3,
    "감점 유지": lambda scores, origin: all(scores[axis]["score"] < 5 for axis in origin["keep"]),
}


def _read_round(round_dir: Path, folder: str) -> list:
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted((round_dir / folder).glob("batch_*.json"))]


def build_probe(source: Path, verification: dict, cases: dict, out: Path, seed: int = 20261129, batch_size: int = 10) -> None:
    mapping = json.loads((source / "mapping.json").read_text(encoding="utf-8"))
    results = {i: s for batch in _read_round(source, "results") for i, s in batch.items()}
    by_key = {}
    for item in (item for batch in _read_round(source, "batches") for item in batch):
        origin = {k: mapping[item["item_id"]][k] for k in ORIGIN_KEYS}
        body = {k: v for k, v in item.items() if k not in ("item_id", "검증 결과")}
        deducted = any(results[item["item_id"]][a]["score"] < 5 for a in AXES)
        by_key[(origin["id"], origin["system"])] = (body, origin, deducted)

    def find(case: dict) -> tuple[dict, dict]:
        body, origin, _ = by_key[(case["id"], case["system"])]
        return dict(body), dict(origin)

    kept = {(c["id"], c["system"]): c["axes"] for c in cases.get("keep_deducted", [])}
    chosen: list[tuple[dict, dict]] = []
    for key, (body, origin, deducted) in by_key.items():
        if key in kept:
            chosen.append((dict(body), {**origin, "kind": "감점 유지", "keep": kept[key]}))
        elif deducted:
            chosen.append((dict(body), {**origin, "kind": "감점 항목"}))
    for case in cases.get("context_swaps", []):
        body, origin = find(case)
        body["context"] = case["context"] if "context" in case else find(case["context_from"])[0]["context"]
        chosen.append((body, {**origin, "kind": "context 바꿈", "note": case.get("kind", ""), "context_from": case.get("context_from")}))
    for case in cases.get("altered_answers", []):
        body, origin = find(case)
        for old, new in case["replace"]:
            if old not in body["generated_answer"] or new in body["context"]:
                raise ValueError(f"{case['id']}: 답에 '{old}'가 없거나 '{new}'가 context에 있다")
            body["generated_answer"] = body["generated_answer"].replace(old, new)
        chosen.append((body, {**origin, "kind": "값 바꿈", "replace": case["replace"]}))

    random.Random(seed).shuffle(chosen)
    (out / "batches").mkdir(parents=True)
    (out / "results").mkdir()
    items = [{"item_id": f"p{n:04d}", **body} for n, (body, _) in enumerate(chosen, 1)]
    new_mapping = {item["item_id"]: origin for item, (_, origin) in zip(items, chosen)}
    for n, batch in enumerate(split_batches(items, batch_size), 1):
        (out / "batches" / f"batch_{n:02d}.json").write_text(json.dumps(batch, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "mapping.json").write_text(json.dumps(new_mapping, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "rubric.md").write_text(rubric_text(), encoding="utf-8")
    (out / "rubric_version.txt").write_text(RUBRIC_VERSION + "\n", encoding="utf-8")
    attach(out, verification)


def check_probe(round_dir: Path) -> list[dict]:
    mapping = json.loads((round_dir / "mapping.json").read_text(encoding="utf-8"))
    results = {i: s for batch in _read_round(round_dir, "results") for i, s in batch.items()}
    missing = sorted(set(mapping) - set(results))
    if missing:
        raise ValueError(f"빠진 결과: {missing}")
    report = []
    for kind, rule in RULES.items():
        ids = [i for i, origin in mapping.items() if origin["kind"] == kind]
        if ids:
            failures = sorted(f"{mapping[i]['system']} {mapping[i]['id']}" for i in ids if not rule(results[i], mapping[i]))
            report.append({"name": kind, "passed": len(ids) - len(failures), "total": len(ids), "failures": failures})
    return report


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--source-round", required=True)
    b.add_argument("--verification", required=True)
    b.add_argument("--out-dir", required=True)
    b.add_argument("--cases", default=str(CASES_PATH))
    c = sub.add_parser("check")
    c.add_argument("--round-dir", required=True)
    a = ap.parse_args()
    if a.cmd == "build":
        build_probe(Path(a.source_round), json.loads(Path(a.verification).read_text(encoding="utf-8")),
                    yaml.safe_load(Path(a.cases).read_text(encoding="utf-8")), Path(a.out_dir))
        print(f"시험 묶음 → {a.out_dir}")
        return
    report = check_probe(Path(a.round_dir))
    for r in report:
        print(f"{'통과' if r['passed'] == r['total'] else '실패'}  {r['name']}: {r['passed']} / {r['total']}"
              + (f"  어긋난 항목 {r['failures']}" if r["failures"] else ""))
    if any(r["passed"] < r["total"] for r in report):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
