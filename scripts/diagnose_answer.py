"""틀린 답변의 원인을 가른다 — 프로세스 코드는 바꾸지 않고 LLM 호출만 기록한다.

선택한 문항을 (DB 작업 트리 × 단축 경로 켬/끔) 조합으로 현재 프로세스에 돌리면서 `openai` SDK의 `chat.completions.create`를
감싸 요청 메시지와 응답(`content`와 모델의 `reasoning`)을 그대로 남긴다. 답변 프롬프트·출력은 달라지지 않는다.
그 뒤 문항마다 다음을 판정한다.

  facts_in_raw_top5   검색된 상위 5개 청크 원문에 정답 핵심 수치가 있는가
  facts_in_context    생성 호출에 실제로 들어간 컨텍스트(청크당 700자 발췌)에 있는가
  answer_ok           답변에 정답의 '주된 값'(괄호 안 내역 제외)이 모두 있는가(휴리스틱)
  cause               검색 실패 / 컨텍스트에서 잘림 / 컨텍스트에 있는데 모델이 못 찾음 / 정상

실패한 문항은 컨텍스트 블록마다 "이 블록에 답이 있는가"를 모델에 따로 묻는다(사후 진단, 답변 경로와 무관).

사용 예:
    python scripts/diagnose_answer.py --ids m11 m17 n4 n13 --out-dir eval_resources/diagnosis/run1 \\
        --target team_db=/path/worktree_team --target cur_db=/path/worktree_cur
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import subprocess
import sys
import time
import unicodedata
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
DATASETS = ("eval_resources/eval_dataset_new20.yaml", "eval_resources/eval_dataset_new20_v2.yaml")
CONTEXT_SEP = "\n\n---\n\n"


def run_questions(project_root: str, questions_file: str, out_file: str, top_k: int) -> None:
    """내부용: 대상 프로젝트 루트에서 문항을 돌리며 LLM 호출을 기록한다."""
    root = Path(project_root).resolve()
    sys.path = [p for p in sys.path if p and Path(p).resolve() != SCRIPT_DIR]
    sys.path.insert(0, str(root))
    os.chdir(root)
    spec = importlib.util.spec_from_file_location("project_eval_retrieval", root / "scripts" / "eval_retrieval.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if hasattr(module, "load_env"):
        module.load_env()
    if os.environ.get("HWP_RAG_FORCE_RETRIEVAL") == "1":
        from src.graph.workflow import RAGChatbotV17
        RAGChatbotV17._should_bypass_short_circuit_for_query = staticmethod(lambda query: True)
        RAGChatbotV17._can_override_short_circuit_bypass = lambda self, *a, **k: False

    import openai.resources.chat.completions as comp

    calls: list[dict] = []
    original = comp.Completions.create

    def recording_create(self, *args, **kwargs):  # noqa: ANN001 — SDK 시그니처를 그대로 통과시킨다
        result = original(self, *args, **kwargs)
        try:
            # langchain은 with_raw_response로 부르므로 LegacyAPIResponse가 올 수 있다. parse()는 결과를 캐시해 호출자에게 영향이 없다.
            parsed = result.parse() if hasattr(result, "parse") and not hasattr(result, "choices") else result
            msg = parsed.choices[0].message
            extra = getattr(msg, "model_extra", None) or {}
            calls.append({"messages": kwargs.get("messages"), "content": msg.content,
                          "reasoning": extra.get("reasoning") or extra.get("reasoning_content") or ""})
        except Exception as e:  # noqa: BLE001 — 기록 실패가 답변을 막으면 안 된다
            calls.append({"messages": kwargs.get("messages"), "error": f"{type(e).__name__}: {e}"})
        return result

    comp.Completions.create = recording_create

    records = []
    for q in json.loads(Path(questions_file).read_text(encoding="utf-8")):
        calls.clear()
        t0 = time.time()
        rec: dict[str, Any] = {"id": q["id"], "question": q["question"]}
        try:
            state = module.run_rag_pipeline(q["question"], None, top_k)
            rec.update(answer=state.get("answer", ""), retrieved_docs=state.get("retrieved_docs", []),
                       latencies=state.get("latencies", {}), csv_short_circuit=bool(state.get("csv_short_circuit", False)))
        except Exception as e:  # noqa: BLE001
            rec["error"] = f"{type(e).__name__}: {e}"
        rec["llm_calls"] = [dict(c) for c in calls]
        rec["wall_seconds"] = round(time.time() - t0, 1)
        records.append(rec)
        Path(out_file).write_text(json.dumps(records, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"[{q['id']}] {rec['wall_seconds']}s calls={len(calls)}", flush=True)


def prompt_text(call: dict) -> str:
    parts = []
    for m in call.get("messages") or []:
        c = m.get("content") if isinstance(m, dict) else getattr(m, "content", "")
        parts.append(c if isinstance(c, str) else json.dumps(c, ensure_ascii=False))
    return "\n".join(parts)


def generation_call(rec: dict) -> dict | None:
    """생성 호출 = 프롬프트가 가장 긴 호출(컨텍스트 블록이 들어가는 호출)."""
    calls = [c for c in rec.get("llm_calls", []) if c.get("messages")]
    return max(calls, key=lambda c: len(prompt_text(c)), default=None)


_PAREN = re.compile(r"[(（][^)）]*[)）]")


def primary_facts(expected: str) -> list[str]:
    """정답 문장에서 '주된 값'. 괄호 안의 내역·부가 값(추정가격, 동복·하복 금액 등)은 뺀다.

    괄호를 빼면 값이 하나도 남지 않을 때만 괄호 안 값까지 쓴다.
    """
    from build_qrels import key_facts

    return key_facts(_PAREN.sub("", expected)) or key_facts(expected)


def analyse(rec: dict, expected: str, chunk_text: dict[str, str]) -> dict:
    from build_qrels import norm

    facts = primary_facts(expected)
    gen = generation_call(rec)
    prompt = prompt_text(gen) if gen else ""
    top5 = (rec.get("retrieved_docs") or [])[:5]
    raw = norm("".join(chunk_text.get(str(d.get("chunk_id")), "") for d in top5))
    ctx, ans = norm(prompt), norm(rec.get("answer", ""))

    def share(text: str) -> float:
        return round(sum(f in text for f in facts) / len(facts), 2) if facts else 0.0

    rec_out = {"facts": facts, "facts_in_raw_top5": share(raw), "facts_in_context": share(ctx), "answer_ok": share(ans) == 1.0}
    if any(c.get("error") for c in rec.get("llm_calls", [])):
        rec_out["cause"] = "기록 실패(원인 판정 불가)"
    elif rec_out["answer_ok"]:
        rec_out["cause"] = "정상"
    elif share(raw) < 0.5:
        rec_out["cause"] = "검색 실패(상위 5개 원문에 정답 없음)"
    elif share(ctx) < 0.5:
        rec_out["cause"] = "컨텍스트에서 잘림(원문에는 있으나 생성 입력에 없음)"
    else:
        rec_out["cause"] = "컨텍스트에 있는데 모델이 못 찾음"
    rec_out["generation_reasoning"] = (gen or {}).get("reasoning", "")[:2000]
    rec_out["recording_errors"] = sum(1 for c in rec.get("llm_calls", []) if c.get("error"))
    rec_out["calls"] = [{"index": i, "prompt_chars": len(prompt_text(c)), "prompt_head": prompt_text(c)[:160].replace("\n", " "),
                         "content": (c.get("content") or "")[:600], "reasoning": (c.get("reasoning") or "")[:2500]}
                        for i, c in enumerate(rec.get("llm_calls", []))]
    rec_out["context_chars"] = len(prompt)
    return rec_out


def block_judgments(rec: dict, expected: str, llm_url: str, model: str) -> list[dict]:
    """컨텍스트 블록마다 '이 블록만 보고 답할 수 있는가'를 모델에 묻는다(사후 진단)."""
    import requests

    gen = generation_call(rec)
    prompt = prompt_text(gen) if gen else ""
    blocks = [b for b in prompt.split(CONTEXT_SEP) if b.strip()]
    out = []
    for i, block in enumerate(blocks):
        ask = (f"질문: {rec['question']}\n기대 답: {expected}\n\n아래 블록 하나만 보고 판단하세요.\n---\n{block[:2500]}\n---\n"
               '이 블록에 질문의 답(기대 답의 핵심 값)이 들어 있습니까? JSON으로만 답하세요: '
               '{"contains_answer": true|false, "quote": "근거 문장 또는 빈 문자열", "why": "한 줄 이유"}')
        try:
            r = requests.post(f"{llm_url}/chat/completions", json={
                "model": model, "messages": [{"role": "user", "content": ask}], "temperature": 0, "max_tokens": 1500},
                headers={"Authorization": "Bearer ollama-local"}, timeout=600).json()["choices"][0]["message"]
            out.append({"block": i + 1, "preview": block[:90].replace("\n", " "), "answer": (r.get("content") or "")[:400]})
        except Exception as e:  # noqa: BLE001
            out.append({"block": i + 1, "error": str(e)[:200]})
    return out


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "_run":
        ap = argparse.ArgumentParser()
        ap.add_argument("_cmd")
        ap.add_argument("--project-root", required=True)
        ap.add_argument("--questions", required=True)
        ap.add_argument("--out", required=True)
        ap.add_argument("--top-k", type=int, default=5)
        a = ap.parse_args()
        return run_questions(a.project_root, a.questions, a.out, a.top_k)

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ids", nargs="+", required=True)
    ap.add_argument("--target", action="append", required=True, help="이름=작업트리 경로 (DB를 넣은 체크아웃)")
    ap.add_argument("--chunks", action="append", required=True, help="이름=청크 덤프 JSON (target과 같은 이름)")
    ap.add_argument("--conditions", nargs="*", default=["forced", "shortcuts_on"])
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--llm-url", default="http://localhost:11434/v1")
    ap.add_argument("--model", default="gpt-oss:20b")
    ap.add_argument("--no-block-judge", action="store_true")
    ap.add_argument("--reanalyse", action="store_true",
                    help="저장된 `<이름>__<조건>.json`을 다시 판정만 한다(LLM·검색 실행 없음). 결과는 diagnosis_primary.json")
    a = ap.parse_args()

    out_dir = Path(a.out_dir).resolve()  # 작업 트리에서 실행되는 하위 프로세스가 같은 위치를 보도록 절대 경로로
    out_dir.mkdir(parents=True, exist_ok=True)
    items = {q["id"]: q for d in DATASETS for q in yaml.safe_load((REPO_ROOT / d).read_text(encoding="utf-8"))}
    qfile = out_dir / "questions.json"
    qfile.write_text(json.dumps([{"id": i, "question": items[i]["question"]} for i in a.ids], ensure_ascii=False), encoding="utf-8")
    targets = dict(t.split("=", 1) for t in a.target)
    dumps = dict(t.split("=", 1) for t in a.chunks)
    env_base = {**os.environ, "CSV_SHORTCIRCUIT_ENABLED": "false", "HWP_RAG_ANSWER_STRATEGY": "two_stage",
                "HWP_RAG_LLM_BASE_URL": a.llm_url, "OPENAI_BASE_URL": a.llm_url, "OPENAI_API_BASE": a.llm_url,
                "OPENAI_API_KEY": "ollama-local", "REASONING_MODEL": a.model, "QUERY_INTENT_MODEL": a.model,
                "DEFAULT_MODEL": a.model, "OPENAI_TIMEOUT_SEC": "1200", "LANGSMITH_TRACING": "false", "PYTHONIOENCODING": "utf-8"}
    report: dict[str, Any] = {}
    for tname, root in targets.items():
        chunks = {c["uid"]: c["text"] for c in json.loads(Path(dumps[tname]).read_text(encoding="utf-8"))}
        for cond in a.conditions:
            env = dict(env_base)
            if cond == "forced":
                env["HWP_RAG_FORCE_RETRIEVAL"] = "1"
            out = out_dir / f"{tname}__{cond}.json"
            if not a.reanalyse:
                subprocess.run([sys.executable, str(Path(__file__).resolve()), "_run", "--project-root", root,
                                "--questions", str(qfile), "--out", str(out)], cwd=root, env=env, check=True)
            recs = json.loads(out.read_text(encoding="utf-8"))
            for rec in recs:
                expected = items[rec["id"]]["expected_answer"]
                diag = analyse(rec, expected, chunks)
                if not diag["answer_ok"] and not a.no_block_judge and not a.reanalyse:
                    diag["block_judgments"] = block_judgments(rec, expected, a.llm_url, a.model)
                report[f"{tname}__{cond}__{rec['id']}"] = {
                    "answer": rec.get("answer", "")[:200], "expected": expected, "csv_short_circuit": rec.get("csv_short_circuit"),
                    "latencies": rec.get("latencies"), "retrieved": [(d.get("chunk_id"), (d.get("source") or "")[:30]) for d in (rec.get("retrieved_docs") or [])[:5]],
                    **diag}
            (out_dir / ("diagnosis_primary.json" if a.reanalyse else "diagnosis.json")).write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: {x: v[x] for x in ("answer_ok", "cause", "facts_in_raw_top5", "facts_in_context")} for k, v in report.items()},
                     ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
