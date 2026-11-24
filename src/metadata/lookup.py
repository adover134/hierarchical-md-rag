"""DB 구축 때 청크의 `org`, `project_name`을 `data_index/metadata.csv`에서 가져온다.

이름은 팀 코드에서 물려받았다: `org`는 검색에 쓰는 식별 라벨인 **공고명**, `project_name`은 **기관명**(수요기관)이다.
이 둘을 뒤바꾸면 검색이 깨진 적이 있어(전체 코퍼스 회귀 검증) 뜻은 그대로 두고 값의 출처만 파일 이름 쪼개기에서 CSV로 바꿨다.
"""

from __future__ import annotations

import csv
import unicodedata
from pathlib import Path

from src.utils.config import PROJECT_ROOT

DEFAULT_METADATA_CSV = PROJECT_ROOT / "data_index" / "metadata.csv"
_ORG_FALLBACK_COLUMNS = ("수요기관", "공고기관", "발주 기관")
_cache: dict[tuple[str, float], dict[str, tuple[str, str]]] = {}


def _load(csv_path: Path) -> dict[str, tuple[str, str]]:
    key = (str(csv_path), csv_path.stat().st_mtime)
    if key not in _cache:
        table: dict[str, tuple[str, str]] = {}
        with open(csv_path, encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                file_name = unicodedata.normalize("NFC", row.get("파일명", ""))
                title = row.get("공고명", "")
                agency = next((row[c] for c in _ORG_FALLBACK_COLUMNS if row.get(c)), "")
                if file_name and title and agency:
                    table[file_name] = (title, agency)
        _cache.clear()
        _cache[key] = table
    return _cache[key]


def org_fields_for(file_name: str, csv_path: Path | str | None = None) -> tuple[str, str] | None:
    """Markdown 파일 이름으로 (org=공고명, project_name=기관명)을 찾는다. CSV가 없거나 행이 없으면 None."""
    path = Path(csv_path) if csv_path else DEFAULT_METADATA_CSV
    if not path.is_file():
        return None
    return _load(path).get(unicodedata.normalize("NFC", file_name))
