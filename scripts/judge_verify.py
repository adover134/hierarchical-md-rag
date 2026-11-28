"""채점 1단계: 검증자가 원본 문서를 직접 찾아 질문의 대상 공고와 답을 확인한다.

검증자는 질문만 받는다(생성 답, 기대 답변, 검색 context는 받지 않는다).
도구 없이 `claude -p`로 부르고, 검증자가 요청한 목록·검색·보기만 이 코드가 대신 실행하므로 평가 set과 점수 파일에 접근할 수 없다.

사용 예:
    python scripts/judge_search.py build          # 원본 문서의 검색 자료. 공고 목록은 실행할 때 엑셀에서 읽는다
    python scripts/judge_verify.py run --out eval_resources/claude_judge/<round>/verification.json
    python scripts/judge_verify.py attach --round-dir eval_resources/claude_judge/<round> --verification <위 파일>
`attach`는 batch의 항목마다 "검증 결과"를 붙이고 지시문에 두 줄을 더한다. 채점(2단계)은 `scripts/judge_grade.py`가 한다.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
import threading
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))

from judge_excel import excel_text, read_notices  # noqa: E402
from judge_grade import BASE_INSTRUCTION  # noqa: E402
from judge_search import CORPUS_PATH, docs_text, load_corpus, search_text, show_text  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent

VERIFY_PROMPT = """당신은 RAG 답 채점을 위한 검증자다. 아래 질문의 답을 원본에서 직접 찾는다. 공고 목록(엑셀)을 먼저 보고, 목록에 없는 내용은 원본 문서에서 찾는다.
- 질문이 가리키는 공고를 먼저 특정한다. 이름이 비슷한 공고가 여럿이면 지역, 차수, 공고번호, 본문을 대조해 하나로 좁히고 이유를 적는다.
- 근거가 된 원문 구절을 그대로 인용한다. 찾지 못하면 "확인 불가"라고 쓴다.
- "answer"에는 목록에서 확인한 값과 문서에서만 확인한 내용을 구분해 적는다.
출력: {"notices": [{"file": "", "notice_no": "", "why": "", "quotes": []}], "answer": "", "unverified": ""}

원본을 직접 열 수는 없고, 아래 행동을 한 번에 하나씩 JSON으로 요청하면 결과를 받는다.
- {"action": "excel", "query": "낱말 낱말"}: 공고 목록(엑셀)에서 낱말이 든 행. 모든 열(사업 금액 포함)을 보여준다. query가 비면 열 이름
- {"action": "docs"}: 원본 문서 목록
- {"action": "search", "query": "낱말 낱말"}: 원본 본문에서 낱말이 많이 든 부분
- {"action": "show", "doc": 문서번호, "start": 시작줄}: 원본 한 문서의 본문
- {"action": "final", "result": {위 출력 형식}}: 검증을 마치고 결과를 낸다. file에는 문서 이름을 그대로 적는다."""

SCHEMA = {
    "type": "object",
    "properties": {
        "action": {"type": "string", "enum": ["excel", "docs", "search", "show", "final"]},
        "query": {"type": "string"}, "doc": {"type": "integer"}, "start": {"type": "integer"},
        "result": {
            "type": "object",
            "properties": {
                "notices": {"type": "array", "items": {"type": "object", "properties": {
                    "file": {"type": "string"}, "notice_no": {"type": "string"}, "why": {"type": "string"},
                    "quotes": {"type": "array", "items": {"type": "string"}}},
                    "required": ["file", "notice_no", "why", "quotes"]}},
                "answer": {"type": "string"}, "unverified": {"type": "string"}},
            "required": ["notices", "answer", "unverified"]},
    },
    "required": ["action"],
}

INSTRUCTION_LINE = ('항목의 "검증 결과"는 원본에서 따로 확인한 것이다. 채점하기 전에 context의 문서가 검증 결과의 공고와 같은지 대조한다.\n'
                    '생성 답이나 context가 기대 답변과 다르게 표현돼도, 검증 결과의 값이나 원문 구절로 같은 내용임이 확인되면 맞은 것으로 본다.')


def _run_action(corpus: dict, reply: dict) -> str:
    if reply["action"] == "excel":
        return excel_text(corpus.get("notices", []), corpus["documents"], reply.get("query", ""))
    if reply["action"] == "docs":
        return docs_text(corpus)
    if reply["action"] == "search":
        return search_text(corpus, reply.get("query", ""))
    if reply["action"] == "show":
        return show_text(corpus, int(reply.get("doc", 0)), int(reply.get("start", 1)))
    return "final에는 result가 필요합니다."


def verify_question(question: str, corpus: dict, ask: Callable[[str], dict], max_steps: int = 10) -> dict:
    """검증자가 final을 낼 때까지 요청을 실행해 돌려준다. 요청과 결과는 모두 남긴다."""
    steps: list[dict] = []
    for turn in range(1, max_steps + 1):
        history = "\n\n".join(
            f"[{n}] {json.dumps({k: v for k, v in s.items() if k != 'output'}, ensure_ascii=False)}\n{s['output']}"
            for n, s in enumerate(steps, 1))
        message = f"## 질문\n{question}"
        if history:
            message += f"\n\n## 지금까지 요청한 것과 결과\n{history}"
        message += "\n\n마지막 차례입니다. final만 요청할 수 있습니다." if turn == max_steps else "\n\n다음 행동 하나를 JSON으로 요청하세요."
        reply = ask(message)
        if reply["action"] == "final" and reply.get("result") is not None:
            return {"question": question, "result": reply["result"], "steps": steps}
        steps.append({**{k: v for k, v in reply.items() if k != "result"}, "output": _run_action(corpus, reply)})
    return {"question": question, "steps": steps,
            "result": {"notices": [], "answer": "확인 불가", "unverified": "정해진 횟수 안에 결과를 내지 못했다"}}


def claude_ask(calls: list[dict], model: str = "opus") -> Callable[[str], dict]:
    """CLAUDE.md, memory, hook, MCP, 도구 없이 검증 지시문과 message만 보내는 호출. 호출마다의 사용량을 calls에 더한다."""
    empty = tempfile.mkdtemp(prefix="judge_verify_")

    def ask(message: str) -> dict:
        done = subprocess.run(
            ["claude", "-p", "--safe-mode", "--system-prompt", VERIFY_PROMPT, "--tools", "", "--model", model,
             "--no-session-persistence", "--output-format", "json", "--json-schema", json.dumps(SCHEMA)],
            input=message, capture_output=True, text=True, cwd=empty, timeout=300, check=True)
        reply = json.loads(done.stdout)
        if reply.get("is_error") or not reply.get("structured_output"):
            raise RuntimeError(f"검증 호출 실패: {str(reply.get('result'))[:300]}")
        calls.append({"cost_usd": reply.get("total_cost_usd"), "models": list(reply.get("modelUsage") or {})})
        return reply["structured_output"]

    return ask


def _stem(name: str) -> str:
    name = unicodedata.normalize("NFC", str(name)).removeprefix("step2_audited_")
    return re.sub(r"\.(md|pdf|hwpx?|hwp)$", "", name)


def target_matches(result: dict, sources: list[str]) -> bool:
    """검증자가 특정한 문서가 평가 set의 정답 문서와 정확히 같은 묶음인가."""
    found = {_stem(n.get("file", "")) for n in result.get("notices", [])}
    return found == {_stem(s) for s in sources}


def attach(round_dir: Path, verification: dict) -> None:
    """batch의 항목마다 그 문항의 검증 결과를 붙이고, 지시문에 대조하라는 한 줄을 더한다."""
    mapping = json.loads((round_dir / "mapping.json").read_text(encoding="utf-8"))
    for path in sorted((round_dir / "batches").glob("batch_*.json")):
        items = json.loads(path.read_text(encoding="utf-8"))
        for item in items:
            origin = mapping[item["item_id"]]
            item["검증 결과"] = verification[f"{origin['dataset']}/{origin['id']}"]["result"]
        path.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
    instruction = round_dir / "instruction.txt"
    text = instruction.read_text(encoding="utf-8") if instruction.exists() else BASE_INSTRUCTION
    if INSTRUCTION_LINE not in text:
        instruction.write_text(text.rstrip("\n") + "\n" + INSTRUCTION_LINE + "\n", encoding="utf-8")


def cmd_run(a: argparse.Namespace) -> None:
    from claude_judge import _load_dataset_items

    corpus = load_corpus(Path(a.corpus))
    corpus["notices"] = read_notices()  # 실행할 때마다 엑셀 원본을 읽는다
    items = _load_dataset_items()
    out = Path(a.out)
    done = json.loads(out.read_text(encoding="utf-8")) if out.exists() else {}
    todo = {f"{d}/{i}": item for (d, i), item in items.items() if f"{d}/{i}" not in done}
    out.parent.mkdir(parents=True, exist_ok=True)
    lock = threading.Lock()

    def one(key: str) -> None:
        calls: list[dict] = []
        record = verify_question(todo[key]["question"], corpus, claude_ask(calls, a.model), a.max_steps)  # 질문만 넘긴다
        record["calls"] = calls
        with lock:
            done[key] = record
            out.write_text(json.dumps(done, ensure_ascii=False, indent=1), encoding="utf-8")
        print(key, f"호출 {len(calls)}", record["result"]["answer"][:80], flush=True)

    with ThreadPoolExecutor(max_workers=a.workers) as pool:
        list(pool.map(one, todo))
    print(f"검증 {len(done)}문항 → {out}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--out", required=True)
    r.add_argument("--corpus", default=str(CORPUS_PATH))
    r.add_argument("--model", default="opus")
    r.add_argument("--max-steps", type=int, default=10)
    r.add_argument("--workers", type=int, default=4)
    r.set_defaults(fn=cmd_run)
    t = sub.add_parser("attach")
    t.add_argument("--round-dir", required=True)
    t.add_argument("--verification", required=True)
    t.set_defaults(fn=lambda a: attach(Path(a.round_dir), json.loads(Path(a.verification).read_text(encoding="utf-8"))))
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
