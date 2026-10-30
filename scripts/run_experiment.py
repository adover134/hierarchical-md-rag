"""3개 시스템(팀 최종 / 현 버전 기본 / 현 버전 멀티에이전트) 성능 비교 실험 실행기.

설정은 `experiments/config.yaml`, 사용법과 결과 표는 `EXPERIMENTS.md`.

단계(서브커맨드):
    prepare   입력 준비 — hwpx를 PDF로 사전 변환(팀용), 엑셀을 각 시스템 형식으로 배치
    build     시스템별 DB 구축(문서만 동일, DB는 각자 방식) + 색인 소요 시간 수집
    query     시스템별로 평가셋 질의 실행(각 프로젝트의 `run_rag_pipeline`을 그대로 호출) → 원시 결과 JSON
    dump      시스템별 Chroma의 청크/메타데이터 덤프(청크 ID로 비교하지 않고 헤더 포함률·표 정합률 계산용)
    evaluate  원시 결과를 이 저장소의 Judge·지표로 동일하게 채점 → summary.json
    report    summary.json → 마크다운 표(EXPERIMENTS.md 결과 절)
    all       위를 순서대로

설계: 질의 실행은 시스템별 별도 프로세스(cwd=해당 프로젝트)에서 하고(두 코드 모두 `src.*` 모듈명이라
한 프로세스에서 같이 못 씀), 채점·지표는 항상 이 저장소의 코드로 한다 — 그래서 세 시스템이 같은 Judge
프롬프트·같은 지표 정의로 평가된다.
"""

from __future__ import annotations

import argparse
import csv
import datetime as _dt
import importlib.util
import json
import os
import shutil
import statistics
import subprocess
import sys
import time
import unicodedata
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG = REPO_ROOT / "experiments" / "config.yaml"
RESULTS_BEGIN = "<!-- RESULTS:BEGIN -->"
RESULTS_END = "<!-- RESULTS:END -->"


# ---------------------------------------------------------------------------
# 설정/경로 공통
# ---------------------------------------------------------------------------

def _path(value: str | Path) -> Path:
    p = Path(value)
    return (p if p.is_absolute() else REPO_ROOT / p).resolve()


def load_config(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def llm_env(cfg: dict) -> dict[str, str]:
    """세 시스템이 모두 같은 로컬 모델을 쓰도록 두 코드베이스가 읽는 환경변수를 전부 맞춘다."""
    llm = cfg["llm"]
    return {
        "HWP_RAG_LLM_BASE_URL": llm["base_url"],   # 현 버전
        "OPENAI_BASE_URL": llm["base_url"],        # 팀 버전(ChatOpenAI가 환경변수에서 읽음)
        "OPENAI_API_BASE": llm["base_url"],
        "OPENAI_API_KEY": llm["api_key"],
        "REASONING_MODEL": llm["model"],
        "QUERY_INTENT_MODEL": llm["model"],
        "DEFAULT_MODEL": llm["model"],
        "OPENAI_TIMEOUT_SEC": str(llm.get("timeout_sec", 1200)),
        "HF_HUB_DISABLE_TELEMETRY": "1",
        "LANGSMITH_TRACING": "false",
        "PYTHONIOENCODING": "utf-8",
    }


def system_env(cfg: dict, system: dict) -> dict[str, str]:
    env = os.environ.copy()
    env.update(llm_env(cfg))
    env.update({k: str(v) for k, v in (system.get("env") or {}).items()})
    return env


def run_dir(cfg: dict, run_id: str) -> Path:
    d = _path(cfg["runs_dir"]) / run_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def pick_systems(cfg: dict, names: list[str] | None) -> list[dict]:
    systems = cfg["systems"]
    return [s for s in systems if not names or s["name"] in names]


def corpus_docs(cfg: dict) -> list[Path]:
    return sorted(
        p for p in _path(cfg["corpus_dir"]).iterdir() if p.suffix.lower() in {".hwp", ".hwpx", ".pdf"}
    )


def run(cmd: list[str], *, cwd: Path, env: dict[str, str], log: Path | None = None) -> float:
    """명령을 실행하고 걸린 시간(초)을 돌려준다. 실패하면 예외."""
    print(f"$ (cd {cwd} && {' '.join(cmd)})", flush=True)
    t0 = time.time()
    if log:
        with open(log, "w", encoding="utf-8") as f:
            subprocess.run(cmd, cwd=cwd, env=env, check=True, stdout=f, stderr=subprocess.STDOUT)
    else:
        subprocess.run(cmd, cwd=cwd, env=env, check=True)
    return time.time() - t0


# ---------------------------------------------------------------------------
# prepare
# ---------------------------------------------------------------------------

def cmd_prepare(cfg: dict, args: argparse.Namespace) -> None:
    from src.utils.bid_list_xlsx import bid_list_to_team_csv

    corpus = _path(cfg["corpus_dir"])
    xlsx = _path(cfg["bid_list_xlsx"])
    work = _path(cfg["work_dir"])
    docs = corpus_docs(cfg)
    print(f"문서 {len(docs)}건 (hwp {sum(d.suffix.lower()=='.hwp' for d in docs)}, "
          f"hwpx {sum(d.suffix.lower()=='.hwpx' for d in docs)}, pdf {sum(d.suffix.lower()=='.pdf' for d in docs)})")

    for system in pick_systems(cfg, args.systems):
        root = _path(system["project_root"])
        if system["kind"] == "team":
            # 팀 전처리기는 .hwp만 PDF로 바꾸고 .hwpx는 처리하지 않는다 → 코드를 고치지 않고,
            # hwpx를 팀이 쓰는 것과 같은 LibreOffice로 먼저 PDF로 바꿔 입력 폴더에 넣는다.
            team_input = work / "team_input"
            team_input.mkdir(parents=True, exist_ok=True)
            for doc in docs:
                if doc.suffix.lower() == ".hwpx":
                    target = team_input / f"{unicodedata.normalize('NFC', doc.stem)}.pdf"
                    if not target.exists():
                        tmp = work / "hwpx_convert"
                        tmp.mkdir(parents=True, exist_ok=True)
                        run(["soffice", "--headless", "--convert-to", "pdf", "--outdir", str(tmp), str(doc)],
                            cwd=work, env=os.environ.copy())
                        produced = tmp / f"{doc.stem}.pdf"
                        shutil.move(str(produced), target)
                else:
                    shutil.copy2(doc, team_input / doc.name)
            for data_dir in (root / "data", root / "data_index" / "data"):
                stats = bid_list_to_team_csv(xlsx, corpus, data_dir / "data_list.csv")
            print(f"[{system['name']}] 입력 폴더 {team_input} ({len(list(team_input.iterdir()))}건), "
                  f"data_list.csv {stats}")
        else:
            dest = root / "data_index"
            dest.mkdir(parents=True, exist_ok=True)
            shutil.copy2(xlsx, dest / xlsx.name)
            print(f"[{system['name']}] 엑셀 복사 → {dest / xlsx.name}")


# ---------------------------------------------------------------------------
# build
# ---------------------------------------------------------------------------

def _read_summary_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def cmd_build(cfg: dict, args: argparse.Namespace) -> None:
    rd = run_dir(cfg, args.run_id)
    work = _path(cfg["work_dir"])
    llm = cfg["llm"]
    py = sys.executable
    for system in pick_systems(cfg, args.systems):
        if system.get("db_from"):
            print(f"[{system['name']}] DB는 {system['db_from']}와 공유 — 건너뜀")
            continue
        root = _path(system["project_root"])
        env = system_env(cfg, system)
        info: dict[str, Any] = {"system": system["name"], "started_at": _dt.datetime.now().isoformat()}
        if system["kind"] == "team":
            secs = run([py, "scripts/preprocessor.py", "--input", str(work / "team_input")],
                       cwd=root, env=env, log=rd / f"{system['name']}_build.log")
            rows = _read_summary_csv(root / "output" / "execution_summary.csv")
            info.update(total_seconds=round(secs, 1), per_doc=_per_doc(rows, "file"))
        else:
            secs = run([py, "scripts/build_index_new_parser.py", "--input", str(_path(cfg["corpus_dir"])),
                        "--backend", "openai", "--base-url", llm["base_url"], "--api-key", llm["api_key"],
                        "--model", llm["model"]]
                       + (["--max-candidates-per-call", str(llm["parser_max_candidates_per_call"])]
                          if llm.get("parser_max_candidates_per_call") else []),
                       cwd=root, env=env, log=rd / f"{system['name']}_build_hwp.log")
            secs_pdf = run([py, "scripts/index_pdf_originals.py", "--input", str(_path(cfg["corpus_dir"]))],
                           cwd=root, env=env, log=rd / f"{system['name']}_build_pdf.log")
            rows = (_read_summary_csv(root / "output" / "execution_summary_new_parser.csv")
                    + _read_summary_csv(root / "output" / "execution_summary_pdf_originals.csv"))
            info.update(total_seconds=round(secs + secs_pdf, 1), per_doc=_per_doc(rows, "file"))
        (rd / f"{system['name']}_build.json").write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")
        ok_docs = [d for d in info["per_doc"] if d.get("status") == "success"]
        expected = len(corpus_docs(cfg))
        print(f"[{system['name']}] 색인 소요 {info['total_seconds']}초, 성공 {len(ok_docs)}/{expected}건")
        if len(ok_docs) != expected:
            failed = [d["file"] for d in info["per_doc"] if d.get("status") != "success"]
            raise SystemExit(
                f"[{system['name']}] 색인 실패: 성공 {len(ok_docs)}/{expected}건. 로그를 확인하세요: "
                f"{rd / (system['name'] + '_build*.log')}\n  실패 예: {failed[:3]}"
            )


def _per_doc(rows: list[dict[str, str]], key: str) -> list[dict[str, Any]]:
    out = []
    for r in rows:
        try:
            out.append({"file": r.get(key, ""), "status": r.get("status", ""),
                        "seconds": float(r.get("duration_sec") or 0.0),
                        "chunks": int(float(r.get("chunk_count") or 0))})
        except ValueError:
            continue
    return out


# ---------------------------------------------------------------------------
# query (프로젝트별 프로세스에서 실행되는 _execute)
# ---------------------------------------------------------------------------

def load_eval_items(cfg: dict) -> list[dict]:
    items: list[dict] = []
    for ds in cfg["datasets"]:
        if not ds.get("enabled", True):
            continue
        with open(_path(ds["path"]), encoding="utf-8") as f:
            data = yaml.safe_load(f)
        for it in data:
            items.append({**it, "dataset": ds["name"], "role": ds.get("role", "")})
    return items


def cmd_query(cfg: dict, args: argparse.Namespace) -> None:
    rd = run_dir(cfg, args.run_id)
    items = load_eval_items(cfg)
    if args.limit:
        by_ds: dict[str, list[dict]] = {}
        for it in items:
            by_ds.setdefault(it["dataset"], []).append(it)
        items = [it for group in by_ds.values() for it in group[: args.limit]]
    questions = rd / "questions.json"
    questions.write_text(json.dumps(
        [{"dataset": i["dataset"], "id": i["id"], "question": i["question"]} for i in items],
        ensure_ascii=False, indent=2), encoding="utf-8")
    repeat = args.repeat or cfg.get("repeat", 1)
    for system in pick_systems(cfg, args.systems):
        root = _path(system["project_root"])
        out = rd / f"{system['name']}_raw.json"
        run([sys.executable, str(Path(__file__).resolve()), "_execute",
             "--project-root", str(root), "--questions", str(questions), "--out", str(out),
             "--top-k", str(cfg["top_k"]), "--repeat", str(repeat)],
            cwd=root, env=system_env(cfg, system), log=None)


def _execute(args: argparse.Namespace) -> None:
    """프로젝트 루트를 import 경로 맨 앞에 두고 그 프로젝트의 `run_rag_pipeline`을 그대로 호출한다."""
    root = Path(args.project_root).resolve()
    sys.path = [p for p in sys.path if p and Path(p).resolve() != SCRIPT_DIR]
    sys.path.insert(0, str(root))
    spec = importlib.util.spec_from_file_location("project_eval_retrieval", root / "scripts" / "eval_retrieval.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if hasattr(module, "load_env"):
        module.load_env()  # python-dotenv는 이미 있는 환경변수를 덮어쓰지 않으므로 실험 설정이 우선한다

    questions = json.loads(Path(args.questions).read_text(encoding="utf-8"))
    records: list[dict] = []
    for rep in range(args.repeat):
        for i, q in enumerate(questions, 1):
            print(f"[rep {rep + 1}/{args.repeat}] [{i}/{len(questions)}] {q['dataset']}:{q['id']} {q['question'][:50]}", flush=True)
            t0 = time.time()
            rec: dict[str, Any] = {"dataset": q["dataset"], "id": q["id"], "question": q["question"], "repeat": rep + 1}
            try:
                state = module.run_rag_pipeline(q["question"], None, args.top_k)
                rec.update(
                    answer=state.get("answer", ""), evidence=state.get("evidence", ""),
                    retrieved_docs=state.get("retrieved_docs", []), latencies=state.get("latencies", {}),
                    csv_short_circuit=bool(state.get("csv_short_circuit", False)),
                    source_type=state.get("source_type", ""),
                )
            except Exception as e:  # noqa: BLE001 — 한 문항의 실패가 전체 실험을 멈추면 안 된다
                rec["error"] = f"{type(e).__name__}: {e}"
                print(f"  [ERROR] {rec['error']}", flush=True)
            rec["wall_seconds"] = round(time.time() - t0, 2)
            records.append(rec)
            Path(args.out).write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"원시 결과 저장: {args.out} ({len(records)}건)")


# ---------------------------------------------------------------------------
# dump
# ---------------------------------------------------------------------------

def cmd_dump(cfg: dict, args: argparse.Namespace) -> None:
    rd = run_dir(cfg, args.run_id)
    for system in pick_systems(cfg, args.systems):
        root = _path(_system_db_root(cfg, system))
        out = rd / f"{system['name']}_chunks.json"
        run([sys.executable, str(Path(__file__).resolve()), "_dump_db", "--project-root", str(root), "--out", str(out)],
            cwd=root, env=system_env(cfg, system))


def _system_db_root(cfg: dict, system: dict) -> str:
    base = system
    if system.get("db_from"):
        base = next(s for s in cfg["systems"] if s["name"] == system["db_from"])
    return base["project_root"]


def _dump_db(args: argparse.Namespace) -> None:
    import chromadb

    root = Path(args.project_root).resolve()
    client = chromadb.PersistentClient(path=str(root / "data_index" / "chroma_B"))
    names = [c.name if hasattr(c, "name") else str(c) for c in client.list_collections()]
    name = os.environ.get("CHROMA_COLLECTION", "chunks")
    if name not in names and names:
        name = names[0]
    col = client.get_collection(name)
    chunks: list[dict] = []
    total = col.count()
    for offset in range(0, total, 500):
        batch = col.get(limit=500, offset=offset, include=["documents", "metadatas"])
        for cid, doc, meta in zip(batch["ids"], batch["documents"], batch["metadatas"]):
            chunks.append({"id": cid, "text": doc or "", **{k: v for k, v in (meta or {}).items()}})
    Path(args.out).write_text(json.dumps(chunks, ensure_ascii=False), encoding="utf-8")
    print(f"청크 {len(chunks)}개 덤프 → {args.out}")


# ---------------------------------------------------------------------------
# evaluate
# ---------------------------------------------------------------------------

def _source_key(value: Any) -> str:
    return unicodedata.normalize("NFC", str(value or "")).rsplit(".", 1)[0].strip().lower()


def _chunk_lookup(chunks: list[dict]) -> dict[str, dict]:
    return {c["id"]: c for c in chunks}


def cmd_evaluate(cfg: dict, args: argparse.Namespace) -> None:
    sys.path.insert(0, str(REPO_ROOT))
    from src.evaluation import metrics as M
    from src.evaluation.llm_judge import judge_rag_response

    for k, v in llm_env(cfg).items():
        os.environ[k] = v
    rd = run_dir(cfg, args.run_id)
    k = cfg["top_k"]
    items = {(i["dataset"], i["id"]): i for i in load_eval_items(cfg)}
    tags = cfg.get("tags", {})
    reg = {(ds, i) for ds, ids in (tags.get("regression") or {}).items() for i in ids}
    numeric = {(ds, i): spec for ds, group in (tags.get("numeric_compare") or {}).items() for i, spec in group.items()}
    pass_score = tags.get("regression_pass_score", 4)

    table_samples = []
    ts_path = _path(cfg["table_samples"])
    if ts_path.exists():
        table_samples = yaml.safe_load(ts_path.read_text(encoding="utf-8")) or []

    summary: dict[str, Any] = {"run_id": args.run_id, "top_k": k, "systems": {}}
    for system in pick_systems(cfg, args.systems):
        raw_path = rd / f"{system['name']}_raw.json"
        if not raw_path.exists():
            print(f"[{system['name']}] 원시 결과 없음 — 건너뜀")
            continue
        raw = json.loads(raw_path.read_text(encoding="utf-8"))
        chunks_path = rd / f"{system['name']}_chunks.json"
        chunks = json.loads(chunks_path.read_text(encoding="utf-8")) if chunks_path.exists() else []
        lookup = _chunk_lookup(chunks)

        per_query: list[dict] = []
        for rec in raw:
            item = items.get((rec["dataset"], rec["id"]))
            if item is None or rec.get("error"):
                per_query.append({**{kk: rec.get(kk) for kk in ("dataset", "id", "repeat", "error")}})
                continue
            docs = (rec.get("retrieved_docs") or [])[:k]
            texts = [str(d.get("content", "")) for d in docs]
            gt_sources = item.get("ground_truth", {}).get("sources", [])
            expected = item.get("expected_answer", "")

            judge_cache = rd / "judge_cache" / system["name"]
            judge_cache.mkdir(parents=True, exist_ok=True)
            cache_file = judge_cache / f"{rec['dataset']}__{rec['id']}__{rec.get('repeat', 1)}.json"
            if cache_file.exists():
                judge = json.loads(cache_file.read_text(encoding="utf-8"))
            else:
                context = "\n\n".join(p for p in (rec.get("evidence", ""), "\n\n".join(t for t in texts if t)) if p)
                judge = judge_rag_response(question=item["question"], expected_answer=expected,
                                           generated_answer=rec.get("answer", ""), context=context,
                                           model=cfg["llm"].get("judge_model"))
                cache_file.write_text(json.dumps(judge, ensure_ascii=False), encoding="utf-8")

            key_values = M.extract_key_values(expected)
            kv_pos = M.calculate_key_value_hit_position(texts, key_values) if key_values else None
            retrieved_for_metrics = [{"source": d.get("source"), "page": d.get("page"), "score": d.get("score", 0.0)} for d in docs]
            hit_pos = M.calculate_hit_position(retrieved_for_metrics, gt_sources) if gt_sources else None
            header_meta = [lookup.get(str(d.get("chunk_id")), {}) for d in docs]

            row = {
                "dataset": rec["dataset"], "id": rec["id"], "repeat": rec.get("repeat", 1),
                "role": item.get("role", ""),
                "correctness": judge["correctness"]["score"],
                "answer_coverage": judge["answer_coverage"]["score"],
                "faithfulness": judge["faithfulness"]["score"],
                "context_relevance": judge["context_relevance"]["score"],
                "key_values": key_values,
                "kv_eligible": bool(key_values),
                "kv_hit_position": kv_pos,
                "source_hit_position": hit_pos,
                "header_inclusion": M.calculate_header_inclusion_rate(header_meta, k) if chunks else None,
                "regression": (rec["dataset"], rec["id"]) in reg,
                "latencies": rec.get("latencies", {}),
                "wall_seconds": rec.get("wall_seconds"),
                "csv_short_circuit": rec.get("csv_short_circuit", False),
                "answer": rec.get("answer", ""),
            }
            spec = numeric.get((rec["dataset"], rec["id"]))
            if spec:
                row["numeric_compare_ok"] = M.judge_numeric_comparison(rec.get("answer", ""), spec["values"], spec.get("winner"), spec.get("loser"))
            per_query.append(row)

        summary["systems"][system["name"]] = {
            "title": system["title"],
            "metrics": aggregate(per_query, cfg, table_samples, chunks, rd, system, pass_score, k),
            "per_query": per_query,
        }
        print(f"[{system['name']}] 채점 완료: {len(per_query)}건")

    (rd / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"요약 저장: {rd / 'summary.json'}")


def _mean(values: list[float]) -> float | None:
    values = [v for v in values if v is not None]
    return round(sum(values) / len(values), 4) if values else None


def aggregate(per_query: list[dict], cfg: dict, table_samples: list[dict], chunks: list[dict],
              rd: Path, system: dict, pass_score: int, k: int) -> dict[str, Any]:
    from src.evaluation import metrics as M

    ok = [r for r in per_query if "correctness" in r]
    elig = [r for r in ok if r["kv_eligible"]]
    positions = [r["kv_hit_position"] for r in elig]
    by_role = lambda role: [r["correctness"] for r in ok if r["role"] == role]
    reg = [r for r in ok if r["regression"]]
    num = [r for r in ok if "numeric_compare_ok" in r]

    # 표 정합률: 샘플 문서의 청크에서 정답 `라벨: 값` 쌍이 그대로 존재하는지
    table_acc: float | None = None
    table_n = 0
    if table_samples and chunks:
        results: list[float] = []
        for sample in table_samples:
            key = _source_key(sample["source"])
            doc_texts = [c["text"] for c in chunks
                         if key in _source_key(c.get("source", "")) or key in _source_key(c.get("document_title", ""))]
            pairs = [(p["label"], p["value"]) for p in sample["pairs"]]
            acc = M.calculate_table_pair_accuracy(doc_texts, pairs)
            if acc is not None:
                results.extend([acc] * len(pairs))
                table_n += len(pairs)
        table_acc = round(sum(results) / len(results), 4) if results else None

    # 청킹 통계(DB 전체 기준): 색인된 문서 수, 청크 수/길이, 계층(섹션) 메타데이터가 붙은 청크 비율
    lengths = [len(c["text"]) for c in chunks]
    doc_keys = {_source_key(c.get("source") or c.get("document_title")) for c in chunks}
    section_kept = [
        c for c in chunks
        if M._has_section_label(c.get("section_level1")) or M._has_section_label(c.get("section_level2"))
    ]

    lat = [r["latencies"] for r in ok if r.get("latencies")]
    stage = lambda name: _mean([float(l.get(name, 0.0)) for l in lat if name in l])
    build_file = rd / f"{system.get('db_from') or system['name']}_build.json"
    build = json.loads(build_file.read_text(encoding="utf-8")) if build_file.exists() else {}
    build_secs = [d["seconds"] for d in build.get("per_doc", []) if d.get("status") == "success"]

    return {
        "n_queries": len(per_query), "n_scored": len(ok), "n_errors": len(per_query) - len(ok),
        "context_hit_at_3": M.calculate_context_hit_rate(positions, 3), "context_hit_at_5": M.calculate_context_hit_rate(positions, k),
        "kv_mrr": M.calculate_key_value_mrr(positions), "kv_eligible_n": len(elig),
        "source_mrr": round(M.calculate_mrr([r["source_hit_position"] for r in ok]), 4) if ok else None,
        "header_inclusion": _mean([r["header_inclusion"] for r in ok]),
        "table_pair_accuracy": table_acc, "table_pairs_n": table_n,
        "chunk_docs_indexed": len(doc_keys) if chunks else None, "chunk_count": len(chunks) or None,
        "chunk_len_mean": round(statistics.mean(lengths), 1) if lengths else None,
        "chunk_len_median": round(statistics.median(lengths), 1) if lengths else None,
        "chunk_section_coverage": round(len(section_kept) / len(chunks), 4) if chunks else None,
        "regression_pass_rate": (round(sum(r["correctness"] >= pass_score for r in reg) / len(reg), 4) if reg else None),
        "regression_n": len(reg),
        "correctness_all": _mean([r["correctness"] for r in ok]),
        "correctness_existing": _mean(by_role("existing")), "correctness_generalization": _mean(by_role("generalization")),
        "numeric_compare_accuracy": (round(sum(r["numeric_compare_ok"] for r in num) / len(num), 4) if num else None),
        "numeric_compare_n": len(num),
        "api_cost_usd": 0.0 if _is_local(cfg["llm"]["base_url"]) else None,
        "latency_index_sec_per_doc": _mean(build_secs), "latency_index_total_sec": build.get("total_seconds"),
        "latency_analyze_sec": stage("analyze_query"), "latency_retrieve_sec": stage("retrieve"),
        "latency_evidence_sec": stage("extract_evidence"), "latency_generate_sec": stage("generate"),
        "latency_wall_sec": _mean([r["wall_seconds"] for r in ok]),
    }


def _is_local(url: str) -> bool:
    return any(h in url for h in ("localhost", "127.0.0.1", "0.0.0.0"))


# ---------------------------------------------------------------------------
# report
# ---------------------------------------------------------------------------

def _fmt(value: Any, digits: int = 3, suffix: str = "") -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.{digits}f}{suffix}"
    return f"{value}{suffix}"


def render_report(summary: dict, cfg: dict) -> str:
    systems = list(summary["systems"].values())
    heads = " | ".join(s["title"] for s in systems)
    sep = "|---|" + "---|" * len(systems)

    def row(label: str, key: str, digits: int = 3, suffix: str = "", note: str = "") -> str:
        cells = " | ".join(_fmt(s["metrics"].get(key), digits, suffix) for s in systems)
        return f"| {label}{note} | {cells} |"

    def n_row(label: str, key: str) -> str:
        cells = " | ".join(_fmt(s["metrics"].get(key), 0) for s in systems)
        return f"| {label} | {cells} |"

    k = summary["top_k"]
    out = [f"실행 ID `{summary['run_id']}` · top_k={k} · LLM {cfg['llm']['model']} (Judge {cfg['llm'].get('judge_model')})", ""]
    out += ["### 1. 검색 품질", f"| 지표 | {heads} |", sep,
            row("Context Hit Rate@3", "context_hit_at_3"), row(f"Context Hit Rate@{k}", "context_hit_at_5"),
            row("핵심값 MRR", "kv_mrr"), row("문서(source) 단위 MRR", "source_mrr"),
            row("Header Context Inclusion", "header_inclusion"), n_row("핵심값 적격 문항 수(N)", "kv_eligible_n"), ""]
    out += ["### 2. 파싱·청킹·전처리", f"| 지표 | {heads} |", sep,
            n_row("색인된 문서 수", "chunk_docs_indexed"), n_row("전체 청크 수", "chunk_count"),
            row("청크 길이 평균(자)", "chunk_len_mean", 0), row("청크 길이 중앙값(자)", "chunk_len_median", 0),
            row("섹션(계층) 메타데이터 보유 청크 비율", "chunk_section_coverage"),
            row("표 데이터 정합률", "table_pair_accuracy"), n_row("표 정답 쌍 수", "table_pairs_n"),
            row("구조 회귀 통과율", "regression_pass_rate"), n_row("회귀 문항 수", "regression_n"), ""]
    out += ["### 3. 답변 정확도", f"| 지표 | {heads} |", sep,
            row("Correctness (전체)", "correctness_all", 2), row("Correctness (기존 문항)", "correctness_existing", 2),
            row("Correctness (신규 문항, 일반화)", "correctness_generalization", 2),
            row("수치 비교 정확도", "numeric_compare_accuracy"), n_row("수치 비교 문항 수", "numeric_compare_n"),
            n_row("채점된 문항 수", "n_scored"), n_row("실행 오류 문항 수", "n_errors"), ""]
    out += ["### 4. 비용·지연", f"| 지표 | {heads} |", sep,
            row("API 비용(USD)", "api_cost_usd", 2), row("색인 시간(초/문서, 평균)", "latency_index_sec_per_doc", 1),
            row("색인 시간(초, 전체)", "latency_index_total_sec", 0), row("질의분석(초/질의)", "latency_analyze_sec", 1),
            row("검색(초/질의)", "latency_retrieve_sec", 1), row("근거 추출(초/질의)", "latency_evidence_sec", 1),
            row("답변 생성(초/질의)", "latency_generate_sec", 1), row("전체(초/질의)", "latency_wall_sec", 1), ""]
    return "\n".join(out)


def cmd_report(cfg: dict, args: argparse.Namespace) -> None:
    rd = run_dir(cfg, args.run_id)
    summary = json.loads((rd / "summary.json").read_text(encoding="utf-8"))
    text = render_report(summary, cfg)
    print(text)
    target = REPO_ROOT / "EXPERIMENTS.md"
    if args.write and target.exists():
        body = target.read_text(encoding="utf-8")
        if RESULTS_BEGIN in body and RESULTS_END in body:
            head, rest = body.split(RESULTS_BEGIN, 1)
            _, tail = rest.split(RESULTS_END, 1)
            target.write_text(f"{head}{RESULTS_BEGIN}\n{text}\n{RESULTS_END}{tail}", encoding="utf-8")
            print(f"\n{target}의 결과 절을 갱신했습니다.")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["prepare", "build", "query", "dump", "evaluate", "report", "all",
                                        "_execute", "_dump_db"])
    ap.add_argument("--config", default=str(DEFAULT_CONFIG))
    ap.add_argument("--run-id", default=None, help="결과 폴더 이름(기본: 오늘 날짜시간). 이어서 실행/채점할 때 지정")
    ap.add_argument("--systems", nargs="*", help="특정 시스템만(예: team_final current_default)")
    ap.add_argument("--limit", type=int, help="데이터셋별 앞 N문항만(드라이런용)")
    ap.add_argument("--repeat", type=int, help="config의 repeat를 덮어씀")
    ap.add_argument("--write", action="store_true", help="report: EXPERIMENTS.md 결과 절에 기록")
    # 내부용
    ap.add_argument("--project-root"); ap.add_argument("--questions"); ap.add_argument("--out")
    ap.add_argument("--top-k", type=int)
    args = ap.parse_args()

    if args.command == "_execute":
        return _execute(args)
    if args.command == "_dump_db":
        return _dump_db(args)

    sys.path.insert(0, str(REPO_ROOT))
    cfg = load_config(Path(args.config))
    args.run_id = args.run_id or _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    print(f"run_id={args.run_id}")
    steps = {
        "prepare": [cmd_prepare], "build": [cmd_build], "query": [cmd_query], "dump": [cmd_dump],
        "evaluate": [cmd_evaluate], "report": [cmd_report],
        "all": [cmd_prepare, cmd_build, cmd_dump, cmd_query, cmd_evaluate, cmd_report],
    }[args.command]
    for step in steps:
        step(cfg, args)


if __name__ == "__main__":
    main()
