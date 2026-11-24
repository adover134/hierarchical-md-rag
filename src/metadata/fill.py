"""엑셀에 없는 값(사업 금액, 입찰마감일시)을 문서에서 채운다 — 채점(`claude_judge.py`)과 같은 내보내기/가져오기 방식.

코드가 LLM을 부르지 않는다. 내보내기로 빈 칸이 있는 문서 목록을 만들면 Claude 서브에이전트가 문서를 읽고 값과 근거를 적고,
가져오기가 형식을 검증해 CSV에 기록한다. 엑셀에서 온 값은 덮어쓰지 않는다(빈 칸만 채운다).
"""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path

from src.metadata.build import AMOUNT, AMOUNT_EVIDENCE, DEADLINE, DEADLINE_EVIDENCE, FILE_NAME

ID_COLUMN = "입찰공고번호"
NOT_IN_DOCUMENT = "문서에 없음"
_DEADLINE_FORM = re.compile(r"^\d{4}/\d{2}/\d{2} \d{2}:\d{2}$")

RULES = {
    AMOUNT: "① 문서의 기초금액 → ② 없으면 예산·사업금액 중 큰 쪽 → ③ 그것도 없으면 사업금액 표의 `계`. "
            "단가계약이면 문서에 적힌 단가를 그대로 쓰고 수량을 곱하지 않는다. 숫자만(원 단위, 쉼표 없이). 문서에 없으면 빈 값.",
    DEADLINE: "입찰 참가 등록 마감 일시('마감일시'는 이것의 줄임말이다). 따로 정해진 등록 마감이 없는 용역이면 제안서 접수·제출 마감을 쓰되 근거에 그렇다고 적는다. "
               "개찰 시각은 쓰지 않는다. `YYYY/MM/DD HH:MM` 형식. 문서에 없으면 빈 값.",
}
EVIDENCE_COLUMN = {AMOUNT: AMOUNT_EVIDENCE, DEADLINE: DEADLINE_EVIDENCE}


def read_csv(path: Path | str) -> tuple[list[str], list[dict[str, str]]]:
    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        return list(reader.fieldnames or []), list(reader)


def write_csv(path: Path | str, header: list[str], rows: list[dict[str, str]]) -> None:
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=header)
        writer.writeheader()
        writer.writerows(rows)


def find_blanks(rows: list[dict[str, str]]) -> list[dict]:
    """채울 칸이 있는 행. 이미 근거(`문서에 없음` 포함)가 적힌 칸은 다시 묻지 않는다."""
    todo = []
    for row in rows:
        needs = [c for c in (AMOUNT, DEADLINE) if not row.get(c) and not row.get(EVIDENCE_COLUMN[c])]
        if needs and row.get(FILE_NAME):
            todo.append({"id": row[ID_COLUMN], "title": row.get("공고명", ""), "file": row[FILE_NAME], "fill": needs})
    return todo


def export_batches(csv_path: Path | str, markdown_dirs: list[Path | str], out_dir: Path | str, batch_size: int = 6) -> list[Path]:
    _, rows = read_csv(csv_path)
    dirs = [Path(d) for d in markdown_dirs]
    items = []
    for item in find_blanks(rows):
        found = next((d / item["file"] for d in dirs if (d / item["file"]).is_file()), None)
        if found is None:
            raise FileNotFoundError(f"Markdown을 찾지 못했다: {item['file']}")
        items.append({**item, "markdown_path": str(found)})
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths = []
    for n in range(0, len(items), batch_size):
        path = out / f"batch_{n // batch_size + 1:02d}.json"
        path.write_text(json.dumps(
            {"instructions": RULES, "answer_format": {
                "id": "입찰공고번호", "사업 금액": "숫자 문자열 또는 빈 값", "사업 금액 근거": "어디서 가져왔는가(예: 기초금액)",
                "입찰마감일시": "YYYY/MM/DD HH:MM 또는 빈 값", "입찰마감일시 근거": "어디서 가져왔는가"},
             "items": items[n:n + batch_size]}, ensure_ascii=False, indent=2), encoding="utf-8")
        paths.append(path)
    return paths


class FillError(Exception):
    pass


def import_answers(csv_path: Path | str, answer_files: list[Path | str]) -> dict[str, int]:
    header, rows = read_csv(csv_path)
    by_id = {r[ID_COLUMN]: r for r in rows}
    stats = {"filled": 0, "not_in_document": 0, "skipped_existing": 0}
    errors: list[str] = []
    for file in answer_files:
        answers = json.loads(Path(file).read_text(encoding="utf-8"))
        for ans in answers:
            row = by_id.get(ans.get("id", ""))
            if row is None:
                errors.append(f"{file}: 모르는 id {ans.get('id')!r}")
                continue
            for col in (AMOUNT, DEADLINE):
                if col not in ans:
                    continue
                if row.get(col):
                    stats["skipped_existing"] += 1  # 엑셀(또는 앞서 채운) 값은 덮어쓰지 않는다
                    continue
                value = str(ans[col] or "").strip()
                evidence = str(ans.get(EVIDENCE_COLUMN[col]) or "").strip()
                if value:
                    if col == AMOUNT and not value.isdigit():
                        errors.append(f"{row[ID_COLUMN]} 사업 금액이 숫자가 아니다: {value!r}")
                        continue
                    if col == DEADLINE and not _DEADLINE_FORM.match(value):
                        errors.append(f"{row[ID_COLUMN]} 입찰마감일시 형식이 다르다: {value!r}")
                        continue
                    if not evidence:
                        errors.append(f"{row[ID_COLUMN]} {col}에 근거가 없다")
                        continue
                    row[col], row[EVIDENCE_COLUMN[col]] = value, evidence
                    stats["filled"] += 1
                else:
                    row[EVIDENCE_COLUMN[col]] = evidence or NOT_IN_DOCUMENT
                    stats["not_in_document"] += 1
    if errors:
        raise FillError("가져오기를 중단한다(CSV는 바뀌지 않았다):\n  - " + "\n  - ".join(errors))
    write_csv(csv_path, header, rows)
    return stats
