"""채점 2단계: 격리한 Claude가 batch 파일을 채점한다.

채점자는 `claude -p`로 부른다. 지시 파일, memory, hook, git 상태, 도구 없이 빈 폴더에서
system prompt(루브릭 + 채점 지시)와 batch 하나만 받는다. 한 번의 호출이 batch 하나를 채점한다.

사용 예:
    python scripts/judge_grade.py --round-dir eval_resources/claude_judge/<round>
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))

from claude_judge import AXES, validate_results  # noqa: E402

BASE_INSTRUCTION = ("당신은 RAG 답변 채점자다.\n"
                    "입력은 항목의 JSON 목록이다. 모든 항목을 위 루브릭대로 채점한다.\n"
                    "결과는 item_id를 키로, 값은 루브릭의 JSON 형식으로 낸다.")


def system_prompt(round_dir: Path) -> str:
    rubric = (round_dir / "rubric.md").read_text(encoding="utf-8").rstrip("\n")
    return f"{rubric}\n\n## 채점 지시\n{(round_dir / 'instruction.txt').read_text(encoding='utf-8')}"


def batch_schema(item_ids: list[str]) -> dict:
    axis = {"type": "object", "properties": {"score": {"type": "integer", "minimum": 0, "maximum": 5}, "reason": {"type": "string"}},
            "required": ["score", "reason"], "additionalProperties": False}
    item = {"type": "object", "properties": {a: axis for a in AXES}, "required": list(AXES), "additionalProperties": False}
    return {"type": "object", "properties": {i: item for i in item_ids}, "required": list(item_ids), "additionalProperties": False}


def claude_ask(calls: list[dict], model: str = "opus") -> Callable[[str, str, dict], dict]:
    """CLAUDE.md, memory, hook, MCP, 도구 없이 system prompt와 message만 보내는 호출. 호출마다의 사용량을 calls에 더한다."""

    def ask(system: str, message: str, schema: dict) -> dict:
        with tempfile.TemporaryDirectory(prefix="judge_grade_") as empty:
            done = subprocess.run(
                ["claude", "-p", "--safe-mode", "--system-prompt", system, "--tools", "", "--model", model,
                 "--no-session-persistence", "--output-format", "json", "--json-schema", json.dumps(schema)],
                input=message, capture_output=True, text=True, cwd=empty, timeout=600, check=True)
        reply = json.loads(done.stdout)
        if reply.get("is_error") or not reply.get("structured_output"):
            raise RuntimeError(f"채점 호출 실패: {str(reply.get('result'))[:300]}")
        usage = reply.get("modelUsage") or {}
        calls.append({"cost_usd": reply.get("total_cost_usd"), "models": list(usage),
                      "usage": {m: {k: u.get(k) for k in ("inputTokens", "outputTokens", "cacheReadInputTokens", "cacheCreationInputTokens") if k in u} for m, u in usage.items()}})
        return reply["structured_output"]

    return ask


def grade_round(round_dir: Path, ask: Callable[[str, str, dict], dict], workers: int = 4) -> None:
    """결과가 없는 batch만 채점한다. 검증을 통과하지 못한 응답은 쓰지 않고, 끝에 실패한 batch를 알린다."""
    results = round_dir / "results"
    results.mkdir(exist_ok=True)
    system = system_prompt(round_dir)
    todo = [p for p in sorted((round_dir / "batches").glob("batch_*.json")) if not (results / p.name).exists()]
    failed: list[str] = []
    lock = threading.Lock()

    def one(path: Path) -> None:
        message = path.read_text(encoding="utf-8")
        ids = [item["item_id"] for item in json.loads(message)]
        try:
            reply = ask(system, message, batch_schema(ids))
            problems = validate_results(reply, ids)
        except Exception as e:  # 한 batch의 실패가 다른 batch의 결과를 버리지 않게 한다
            problems = [str(e)]
        if problems:
            with lock:
                failed.append(f"{path.stem}: {problems[:3]}")
            return
        (results / path.name).write_text(json.dumps(reply, ensure_ascii=False, indent=1), encoding="utf-8")
        print(path.stem, f"{len(ids)}항목", flush=True)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(one, todo))
    if failed:
        raise RuntimeError("채점 실패:\n  " + "\n  ".join(sorted(failed)))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--round-dir", required=True)
    ap.add_argument("--model", default="opus")
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args()
    round_dir = Path(a.round_dir)
    calls: list[dict] = []
    try:
        grade_round(round_dir, claude_ask(calls, a.model), a.workers)
    finally:
        if calls:
            log = round_dir / "calls.json"
            before = json.loads(log.read_text(encoding="utf-8")) if log.exists() else []
            log.write_text(json.dumps(before + calls, ensure_ascii=False, indent=1), encoding="utf-8")
            models = sorted({m for c in before + calls for m in c["models"]})
            (round_dir / "grader_note.txt").write_text(
                "격리 호출(`scripts/judge_grade.py`)로 채점했다.\n\n"
                f"- 모델: {', '.join(models)}. 호출 {len(before + calls)}회, 호출 하나가 batch 하나를 채점했다.\n"
                "- 채점자가 받은 것: system prompt(rubric.md + instruction.txt)와 batch 파일의 내용.\n"
                "- 지시 파일, memory, git 상태, 도구는 붙지 않는다(`claude -p --safe-mode --tools \"\"`, 빈 폴더).\n"
                "  Claude Code가 붙이는 계정 email과 실행 환경 정보는 남는다.\n"
                "- 호출 기록에 haiku가 함께 남으면 Claude Code가 덧붙인 호출이다. 용도는 확인하지 못했다.\n", encoding="utf-8")


if __name__ == "__main__":
    main()
