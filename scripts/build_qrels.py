"""평가셋의 정답 문장에서 DB별 정답 청크(qrels)를 만든다 — 청크 ID가 DB마다 다르므로 내용으로 찾는다.

정답 청크 = 정답 문서(ground_truth.sources) 안에서, expected_answer의 핵심 수치·날짜를 담은 청크.
핵심 수치가 모두 있으면 등급 2, 절반 이상이면 등급 1. 수치가 없는 정답 문장은 `no_facts`로 표시해 따로 본다.

사용 예:
    python scripts/build_qrels.py --chunks ../hmr_db_snapshots/current_default/chunks.json --out eval_resources/retrieval/qrels_current_default.json
"""

from __future__ import annotations

import argparse
import json
import re
import unicodedata
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
DATASETS = ("eval_resources/eval_dataset_new20.yaml", "eval_resources/eval_dataset_new20_v2.yaml")
_DATE = re.compile(r"(\d{4})\s*[.\-/]\s*(\d{1,2})\s*[.\-/]\s*(\d{1,2})\.?")
_FACT = re.compile(r"(\d{4}년\d{1,2}월\d{1,2}일|\d{1,2}:\d{2})|(\d[\d,]*(?:\.\d+)?)(%|kW|[년월일점개명건시분초원기대])?")


def norm(text: str) -> str:
    """공백·쉼표를 없애 `1,000 원`과 `1000원`이 같게 한다."""
    text = unicodedata.normalize("NFC", str(text or ""))
    text = _DATE.sub(r"\1년\2월\3일", text)  # 2026. 12. 31. → 2026년12월31일
    return re.sub(r"[\s,]", "", text)


def key_facts(answer: str) -> list[str]:
    """정답 문장의 핵심 수치. 긴 수·퍼센트·시각은 그대로, 짧은 수(`60`)는 단위를 붙여(`60일`) 우연한 일치를 줄인다."""
    facts = []
    for m in _FACT.finditer(norm(answer)):
        if m.group(1):
            fact = m.group(1)
        else:
            num, unit = m.group(2).rstrip(","), m.group(3) or ""
            if unit == "%" or len(re.sub(r"\D", "", num)) >= 5:
                fact = num + ("%" if unit == "%" else "")
            elif unit:
                fact = num + unit
            else:
                continue
        if fact not in facts:
            facts.append(fact)
    if len(facts) > 1:  # 제목에 섞인 연도(`2026년`)만으로는 정답 청크를 가를 수 없다
        facts = [f for f in facts if not re.fullmatch(r"\d{4}년", f)]
    return facts


def source_key(value: str) -> str:
    return unicodedata.normalize("NFC", str(value or "")).strip().lower()


def build(chunks: list[dict], questions: list[dict]) -> dict:
    by_source: dict[str, list[dict]] = {}
    for c in chunks:
        by_source.setdefault(source_key(c.get("source")), []).append(c)
    qrels: dict[str, dict[str, int]] = {}
    report: dict[str, dict] = {}
    for q in questions:
        facts = key_facts(q["expected_answer"])
        sources = [source_key(s) for s in q["ground_truth"]["sources"]]
        rel: dict[str, int] = {}
        for s in sources:
            for c in by_source.get(s, []):
                if not facts:
                    continue
                text = norm(c["text"])
                hit = sum(f in text for f in facts)
                if hit == len(facts):
                    rel[c["uid"]] = 2
                elif hit * 2 >= len(facts):
                    rel[c["uid"]] = 1
        qrels[q["id"]] = rel
        report[q["id"]] = {
            "facts": facts, "sources_found": sum(s in by_source for s in sources), "sources": len(sources),
            "relevant": len(rel), "full": sum(v == 2 for v in rel.values()),
            "status": "no_facts" if not facts else ("none" if not rel else "ok"),
        }
    return {"qrels": qrels, "report": report}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--chunks", required=True, help="청크 덤프 JSON(uid, source, text 포함)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--datasets", nargs="*", default=list(DATASETS))
    a = ap.parse_args()
    chunks = json.loads(Path(a.chunks).read_text(encoding="utf-8"))
    questions = []
    for d in a.datasets:
        questions += yaml.safe_load((REPO_ROOT / d).read_text(encoding="utf-8"))
    result = build(chunks, questions)
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    rep = result["report"]
    status = {s: sum(r["status"] == s for r in rep.values()) for s in ("ok", "none", "no_facts")}
    print(f"{out}: 질의 {len(rep)}개, {status}")


if __name__ == "__main__":
    main()
