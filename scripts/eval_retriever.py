"""검색기만 측정한다(LLM 없음) — 팀 / 현재 / 개선(섹션 확장) 세 버전을 ranx로 비교.

각 버전의 DB 스냅샷에서 `VectorStore.search`(앱과 같은 mode=dynamic, hybrid_alpha=0.6)로 질의마다 상위 청크를 받고,
정답 라벨(scripts/build_qrels.py가 청크 내용으로 만든 qrels)과 ranx로 비교한다.

  team_final       팀 프로젝트의 검색 코드 + 팀 DB
  current_default 이 저장소의 검색 코드 + 현재 DB, 후보 풀을 팀과 같은 40으로 맞춤(같은 조건 비교)
  current_pool150 참고: 현재 코드의 실제 기본 후보 풀 150
  improved        current_default와 같은 DB·같은 검색 결과를 쓰되, 검색된 청크를 그 섹션 전체로 확장
                  (섹션 전체 글자 수가 예산 이하일 때만). 확장된 섹션은 순위 한 칸을 차지하는 하나의 결과다.

지표는 청크(섹션) 단위와 문서 단위 두 가지다. 문서 단위 정답은 DB와 무관해 세 버전을 같은 qrels로 비교할 수 있다.

사용 예:
    python scripts/eval_retriever.py --snapshots ../hmr_db_snapshots --out-dir eval_resources/retrieval/run1
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import unicodedata
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
DATASETS = ("eval_resources/eval_dataset_new20.yaml", "eval_resources/eval_dataset_new20_v2.yaml")
TOP_N = 30  # 확장 후 상위 K개 결과를 채우려면 원시 검색 결과를 넉넉히 받는다
# 후보 풀(하이브리드 재정렬 대상 수). 앱이 top_k=5로 부를 때의 각 프로젝트 기본값이다: 팀 max(5*4,40)=40,
# 현재 min(청크 수, max(5*15,150))=150. 풀은 top_k에 따라 달라지므로 TOP_N과 무관하게 명시해 고정한다.
# 공정 비교를 위해 팀·현재·개선은 모두 40으로 맞추고, 현재의 실제 기본값 150은 참고 행(current_pool150)으로만 둔다.
POOL = {"team_final": 40, "current_default": 40, "current_pool150": 150}


def search_questions(project_root: str, db_path: str, spec_file: str, out_file: str, candidate_k: int) -> None:
    """내부용: 대상 프로젝트 루트에서 실행되어 질의별 검색 결과(uid·섹션·길이)를 JSON으로 쓴다."""
    root = Path(project_root).resolve()
    sys.path.insert(0, str(root))
    os.chdir(root)
    spec = json.loads(Path(spec_file).read_text(encoding="utf-8"))
    from src.retrievers.vectorstore import VectorStore

    store = VectorStore(db_path=db_path)
    result: dict[str, list[dict]] = {}
    for q in spec["questions"]:
        rows = store.search(q["question"], top_k=spec["top_n"], mode="dynamic", hybrid_alpha=0.6, candidate_k=candidate_k)
        result[q["id"]] = [
            {"uid": r["metadata"].get("uid") or r["id"], "source": r["metadata"].get("source", r.get("source", "")),
             "score": r["score"], "chars": len(r["text"])}
            for r in rows
        ]
    Path(out_file).write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")


def source_key(value: Any) -> str:
    return unicodedata.normalize("NFC", str(value or "")).strip().lower()


def section_units(chunks: list[dict], level: str, budget: int) -> dict[str, dict]:
    """청크 uid → {unit: 결과 단위 id, members: 그 단위에 든 청크 uid들}.

    섹션(레벨 `section_uid` 또는 `section_level1`)에 속하고 섹션 전체 글자 수가 예산 이하면 섹션이 하나의 단위,
    아니면 청크 하나가 단위다.
    """
    groups: dict[tuple, list[dict]] = {}
    for c in chunks:
        key_val = c.get("section_uid") if level == "section_uid" else c.get("section_level1")
        if key_val in (None, "", "None", "N/A"):
            continue
        groups.setdefault((c.get("doc_id"), key_val), []).append(c)
    unit_of: dict[str, dict] = {}
    for (doc_id, key_val), members in groups.items():
        if sum(len(m["text"]) for m in members) <= budget:
            uid_list = sorted(m["uid"] for m in members)
            unit = f"sec:{doc_id}:{key_val}"
            for m in members:
                unit_of[m["uid"]] = {"unit": unit, "members": uid_list}
    for c in chunks:
        unit_of.setdefault(c["uid"], {"unit": c["uid"], "members": [c["uid"]]})
    return unit_of


def to_run(rows: list[dict], unit_of: dict[str, dict] | None, k: int, chars: dict[str, int]) -> tuple[dict[str, float], int]:
    """원시 검색 순서를 (필요하면 확장한) 단위 순위로 바꾼다. 같은 단위는 한 번만 센다. (순위점수, 반환 글자 수)."""
    seen: list[str] = []
    total = 0
    for r in rows:
        info = unit_of[r["uid"]] if unit_of and r["uid"] in unit_of else {"unit": r["uid"], "members": [r["uid"]]}
        if info["unit"] in seen:
            continue
        seen.append(info["unit"])
        if len(seen) <= k:
            total += sum(chars.get(u, 0) for u in info["members"])
        if len(seen) >= k:
            break
    return {u: float(k - i) for i, u in enumerate(seen)}, total


def map_qrels(qrels: dict[str, int], unit_of: dict[str, dict] | None) -> dict[str, int]:
    out: dict[str, int] = {}
    for uid, grade in qrels.items():
        unit = unit_of[uid]["unit"] if unit_of and uid in unit_of else uid
        out[unit] = max(out.get(unit, 0), grade)
    return out


def doc_run(rows: list[dict], k: int) -> dict[str, float]:
    seen: list[str] = []
    for r in rows:
        s = source_key(r["source"])
        if s not in seen:
            seen.append(s)
        if len(seen) >= k:
            break
    return {s: float(k - i) for i, s in enumerate(seen)}


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "_search":
        ap = argparse.ArgumentParser()
        ap.add_argument("_cmd")
        ap.add_argument("--project-root", required=True)
        ap.add_argument("--db-path", required=True)
        ap.add_argument("--spec", required=True)
        ap.add_argument("--out", required=True)
        ap.add_argument("--candidate-k", type=int, required=True)
        a = ap.parse_args()
        return search_questions(a.project_root, a.db_path, a.spec, a.out, a.candidate_k)

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--snapshots", required=True, help="DB 스냅샷 폴더(팀·현재 하위 폴더 포함)")
    ap.add_argument("--team-root", default=str(REPO_ROOT.parent / "RAG_project"))
    ap.add_argument("--python", default=sys.executable)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--work-dir", help="스냅샷 작업 복사본 위치(기본: out-dir/work). 스냅샷 원본은 건드리지 않는다")
    ap.add_argument("--budget", type=int, default=1000, help="섹션 확장 글자 수 예산")
    ap.add_argument("--level", choices=["section_uid", "section_level1"], default="section_uid")
    ap.add_argument("--ks", type=int, nargs="*", default=[1, 3, 5, 10])
    a = ap.parse_args()

    from ranx import Qrels, Run, evaluate  # 지연 import: 내부 서브커맨드는 ranx 없이도 돈다

    out_dir = Path(a.out_dir)
    work = Path(a.work_dir) if a.work_dir else out_dir / "work"
    out_dir.mkdir(parents=True, exist_ok=True)
    snaps = Path(a.snapshots)
    questions: list[dict] = []
    for d in DATASETS:
        for q in yaml.safe_load((REPO_ROOT / d).read_text(encoding="utf-8")):
            q["dataset"] = "new20" if "new20_v2" not in d else "new20_v2"
            questions.append(q)
    spec = out_dir / "questions.json"
    spec.write_text(json.dumps({"questions": [{"id": q["id"], "question": q["question"]} for q in questions],
                                "top_n": TOP_N}, ensure_ascii=False), encoding="utf-8")

    raw: dict[str, dict] = {}
    for name, root, snap in (("team_final", a.team_root, "team_final"), ("current_default", str(REPO_ROOT), "current_default"),
                             ("current_pool150", str(REPO_ROOT), "current_default")):
        db_copy = work / snap / "chroma_B"
        if not db_copy.exists():
            shutil.copytree(snaps / snap / "data_index" / "chroma_B", db_copy)
        out_file = out_dir / f"raw_{name}.json"
        subprocess.run([a.python, str(Path(__file__).resolve()), "_search", "--project-root", root,
                        "--db-path", str(db_copy), "--spec", str(spec), "--out", str(out_file),
                        "--candidate-k", str(POOL[name])], cwd=root, check=True)
        raw[name] = json.loads(out_file.read_text(encoding="utf-8"))

    chunks = {n: json.loads((snaps / n / "chunks.json").read_text(encoding="utf-8")) for n in ("team_final", "current_default")}
    chars = {n: {c["uid"]: len(c["text"]) for c in chunks[n]} for n in chunks}
    qrels_all = {n: json.loads((REPO_ROOT / "eval_resources/retrieval" / f"qrels_{n}.json").read_text(encoding="utf-8"))["qrels"]
                 for n in chunks}
    unit_improved = section_units(chunks["current_default"], a.level, a.budget)
    systems = {  # 표시 이름 → (원시 검색 결과, 청크 덤프 이름, 단위 매핑)
        "team_final": ("team_final", "team_final", None),
        "current_default": ("current_default", "current_default", None),
        "current_pool150": ("current_pool150", "current_default", None),
        "improved": ("current_default", "current_default", unit_improved),
    }
    doc_qrels = {q["id"]: {source_key(s): 1 for s in q["ground_truth"]["sources"]} for q in questions}
    metrics = [f"{m}@{k}" for k in a.ks for m in ("hit_rate", "recall", "ndcg")] + [f"mrr@{max(a.ks)}"]
    groups = {"전체": [q["id"] for q in questions],
              "기존(m1~m20)": [q["id"] for q in questions if q["dataset"] == "new20"],
              "일반화(n1~n20)": [q["id"] for q in questions if q["dataset"] == "new20_v2"]}

    result: dict[str, Any] = {"budget": a.budget, "level": a.level, "chunk_level": {}, "doc_level": {}, "cost": {}}
    per_query: dict[str, dict[str, dict[str, float]]] = {}
    kmax = max(a.ks)
    for sysname, (raw_name, chunk_name, unit_of) in systems.items():
        runs, qr, drun, totals = {}, {}, {}, []
        for q in questions:
            rows = raw[raw_name][q["id"]]
            run, total = to_run(rows, unit_of, kmax, chars[chunk_name])
            runs[q["id"]] = run
            qr[q["id"]] = map_qrels(qrels_all[chunk_name][q["id"]], unit_of)
            drun[q["id"]] = doc_run(rows, kmax)
            _, t5 = to_run(rows, unit_of, 5, chars[chunk_name])
            totals.append(t5)
        result["cost"][sysname] = {"avg_chars_top5": round(sum(totals) / len(totals))}
        per_query[sysname] = {}
        for label, level_qrels, level_runs, key in (("chunk_level", qr, runs, "chunk_level"), ("doc_level", doc_qrels, drun, "doc_level")):
            result[key][sysname] = {}
            for gname, ids in groups.items():
                sub_q = Qrels.from_dict({i: level_qrels[i] for i in ids})
                sub_r = Run.from_dict({i: level_runs[i] for i in ids})
                result[key][sysname][gname] = {m: round(float(evaluate(sub_q, sub_r, m)), 4) for m in metrics}
            full_q, full_r = Qrels.from_dict({i: level_qrels[i] for i in groups["전체"]}), Run.from_dict({i: level_runs[i] for i in groups["전체"]})
            per_query[sysname][key] = {m: dict(zip(groups["전체"], map(float, evaluate(full_q, full_r, m, return_mean=False)))) for m in metrics}
    (out_dir / "retriever_results.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    (out_dir / "retriever_per_query.json").write_text(json.dumps(per_query, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
