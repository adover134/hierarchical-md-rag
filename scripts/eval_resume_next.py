#!/usr/bin/env python3
"""OpenAI 쿼터가 롤링 윈도우로 조금씩 풀릴 때, 아직 크로스체크 안 된 문항을
하나씩 이어서 돌리는 재개용 스크립트.

eval_retrieval.py의 evaluate_e2e()를 문항 1개짜리 리스트로 호출해 한 번에
하나만 시도하고, 성공하면 결과 JSON(eval_results_new20_openai.json)에
병합 저장한다. 레이트리밋이면 대기 시간을 그대로 반환해 호출자(Claude
loop)가 그만큼 기다렸다가 다시 이 스크립트를 실행하도록 한다 — 스크립트
자체는 재시도 루프를 돌지 않는다(그건 /loop의 ScheduleWakeup 몫).

우선순위: PRIORITY_ORDER 순서대로, 아직 결과 JSON에 정상 기록 안 된 첫 문항
하나만 시도한다.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import scripts.eval_retrieval as er  # noqa: E402

RESULTS_PATH = Path("eval_resources/eval_results_new20_openai.json")
DATASET_PATH = Path("eval_resources/eval_dataset_new20.yaml")

# 사용자가 지정한 순서: m19를 최우선으로, 그다음 아직 크로스체크 안 된 나머지.
PRIORITY_ORDER = [
    "m19", "m9", "m10", "m11", "m12", "m13", "m14", "m15", "m16", "m17", "m18", "m20",
]


def _load_existing() -> dict:
    if RESULTS_PATH.exists():
        return json.loads(RESULTS_PATH.read_text(encoding="utf-8"))
    return {"summary": {}, "per_query": [], "meta": {}}


def _is_done(entry: dict | None) -> bool:
    if not entry:
        return False
    reason = str((entry.get("correctness") or {}).get("reason", ""))
    return "RateLimitError" not in reason and "에러" not in reason


def main() -> None:
    existing = _load_existing()
    by_id = {it["id"]: it for it in existing.get("per_query", [])}

    target_id = None
    for qid in PRIORITY_ORDER:
        if not _is_done(by_id.get(qid)):
            target_id = qid
            break

    if target_id is None:
        print("DONE: 우선순위 목록의 모든 문항이 이미 정상 처리됨.")
        return

    er.load_env()
    all_items = er.load_eval_dataset(DATASET_PATH)
    item = next((it for it in all_items if it.get("id") == target_id), None)
    if item is None:
        print(f"ERROR: 데이터셋에서 {target_id}를 못 찾음")
        return

    print(f"시도: {target_id} — {item['question'][:60]}")
    result = er.evaluate_e2e([item], top_k=5, judge_model="gpt-5.4-mini")
    entry = result["per_query"][0]

    reason = str((entry.get("correctness") or {}).get("reason", ""))
    if "RateLimitError" in reason or "에러" in reason:
        # 레이트리밋 메시지에서 대기 시간을 뽑아 호출자에게 그대로 알려준다.
        wait_match = re.search(r"in (\d+)m(\d+(?:\.\d+)?)s", reason)
        if wait_match:
            wait_min, wait_sec = wait_match.groups()
            print(f"RATE_LIMITED: {target_id} — 약 {wait_min}분 {float(wait_sec):.0f}초 후 재시도 필요")
        else:
            print(f"RATE_LIMITED: {target_id} — {reason[:200]}")
        # 실패한 시도는 저장하지 않는다(다음 실행 때 같은 문항을 다시 시도).
        return

    by_id[target_id] = entry
    existing["per_query"] = list(by_id.values())
    RESULTS_PATH.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")
    c = entry.get("correctness", {}).get("score")
    print(f"SUCCESS: {target_id} — Correctness={c}")


if __name__ == "__main__":
    main()
