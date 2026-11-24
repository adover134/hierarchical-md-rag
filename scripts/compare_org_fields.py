"""DB의 `org`, `project_name`이 파일 이름 쪼개기(예전)와 metadata.csv(지금)에서 어떻게 다른지 보여 준다.

    python scripts/compare_org_fields.py [--csv data_index/metadata.csv] [--out data_index/org_change_report.md]

값이 달라지는 문서만 표로 나온다. 예전 방식에서 같은 `org`를 나눠 쓰던 문서 수도 함께 보여 준다.
"""

from __future__ import annotations

import argparse
import collections
import csv
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.metadata.lookup import DEFAULT_METADATA_CSV, org_fields_for  # noqa: E402

_PREFIXES = ("step2_audited_", "step1_parsed_")


def old_fields(file_name: str) -> tuple[str, str]:
    """예전 방식: 파일 이름(확장자와 PDF 접두사를 뗀 것)을 첫 `_`에서 쪼갠다."""
    stem = unicodedata.normalize("NFC", file_name.rsplit(".", 1)[0])
    for p in _PREFIXES:
        stem = stem.replace(p, "")
    return tuple(stem.split("_", 1)) if "_" in stem else ("N/A", "N/A")  # type: ignore[return-value]


def compare(csv_path: Path) -> tuple[list[dict], dict[str, int]]:
    with open(csv_path, encoding="utf-8-sig", newline="") as f:
        files = [r["파일명"] for r in csv.DictReader(f) if r.get("파일명")]
    old_org_count = collections.Counter(old_fields(fn)[0] for fn in files)
    changed = []
    for fn in files:
        old, new = old_fields(fn), org_fields_for(fn, csv_path)
        if new and new != old:
            changed.append({"file": fn, "old": old, "new": new, "old_org_shared": old_org_count[old[0]]})
    return changed, dict(old_org_count)


def render(changed: list[dict], total: int) -> str:
    lines = [f"# org, project_name 변경 비교 (전체 {total}건 중 {len(changed)}건이 달라진다)", "",
             "| 문서 | 예전 org | 예전 project_name | 지금 org | 지금 project_name | 예전 org를 같이 쓴 문서 수 |", "|---|---|---|---|---|---|"]
    for c in changed:
        lines.append(f"| {c['file']} | {c['old'][0]} | {c['old'][1]} | {c['new'][0]} | {c['new'][1]} | {c['old_org_shared']} |")
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--csv", default=str(DEFAULT_METADATA_CSV))
    ap.add_argument("--out", default=str(DEFAULT_METADATA_CSV.with_name("org_change_report.md")))
    args = ap.parse_args()
    changed, counts = compare(Path(args.csv))
    text = render(changed, sum(counts.values()))
    Path(args.out).write_text(text, encoding="utf-8")
    print(text)
    print(f"저장: {args.out}")


if __name__ == "__main__":
    main()
