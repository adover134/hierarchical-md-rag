"""채점 검증용 원본 검색. 프로젝트의 parser와 DB를 거치지 않고 원본 문서(PDF, HWP, HWPX)와 공고 목록 엑셀만 읽는다.

사용 예:
    python scripts/judge_search.py build
    python scripts/judge_search.py list 아산시
    python scripts/judge_search.py search "교통신호기 1지역 기초금액"
    python scripts/judge_search.py show 3 --start 1

`build`는 원본의 글자를 `eval_resources/judge_corpus/corpus.json`에 모은다(원문 전체가 들어 있어 git 제외).
"""

from __future__ import annotations

import argparse
import json
import math
import re
import struct
import sys
import unicodedata
import zipfile
import zlib
from pathlib import Path
from xml.etree import ElementTree as ET

REPO_ROOT = Path(__file__).resolve().parent.parent
SOURCE_DIR = REPO_ROOT / "RAG_프로세스_테스트_데이터_원본"
CORPUS_PATH = REPO_ROOT / "eval_resources" / "judge_corpus" / "corpus.json"
NOTICE_LIST = "입찰공고목록*.xlsx"
NOTICE_COLUMNS = ("입찰공고번호", "공고명", "공고기관", "수요기관")
PASSAGE, STEP = 12, 8  # 검색 단위(줄)
MAX_OUTPUT = 4000      # 한 번에 돌려주는 글자 수


# --- 원본 읽기 -------------------------------------------------------------------------------

def pdf_text(path: Path) -> str:
    import pymupdf

    return "\n".join(f"<<{n}쪽>>\n{page.get_text()}" for n, page in enumerate(pymupdf.open(path), 1))


def hwpx_text(path: Path) -> str:
    out = []
    with zipfile.ZipFile(path) as z:
        sections = [n for n in z.namelist() if re.match(r"Contents/section\d+\.xml$", n)]
        for name in sorted(sections, key=lambda n: int(re.search(r"(\d+)\.xml$", n).group(1))):
            for paragraph in ET.fromstring(z.read(name)).iter():
                if paragraph.tag.endswith("}p"):
                    line = "".join(t.text or "" for run in paragraph if run.tag.endswith("}run")
                                   for t in run if t.tag.endswith("}t"))
                    if line.strip():
                        out.append(line)
    return "\n".join(out)


def hwp_section_text(data: bytes) -> str:
    """HWP 5.0 본문 stream(압축을 푼 것)의 문단 글자."""
    out, pos = [], 0
    while pos + 4 <= len(data):
        header = struct.unpack_from("<I", data, pos)[0]
        tag, size, pos = header & 0x3FF, header >> 20, pos + 4
        if size == 0xFFF:
            size, pos = struct.unpack_from("<I", data, pos)[0], pos + 4
        if tag == 67:  # HWPTAG_PARA_TEXT
            chunk, chars, i = data[pos:pos + size], bytearray(), 0
            while i + 2 <= len(chunk):
                code = struct.unpack_from("<H", chunk, i)[0]
                if code >= 32:
                    chars += chunk[i:i + 2]
                    i += 2
                else:  # 줄바꿈 등은 1글자, 그 밖의 제어 문자는 8글자 자리를 쓴다
                    chars += " ".encode("utf-16-le")
                    i += 2 if code in (0, 10, 13) or 24 <= code <= 31 else 16
            line = chars.decode("utf-16-le", "ignore").strip()
            if line:
                out.append(line)
        pos += size
    return "\n".join(out)


def hwp_text(path: Path) -> str:
    import olefile

    with olefile.OleFileIO(str(path)) as ole:
        compressed = ole.openstream("FileHeader").read()[36] & 1
        sections = sorted((e for e in ole.listdir() if e[0] == "BodyText"), key=lambda e: int(e[1].removeprefix("Section")))
        parts = []
        for entry in sections:
            data = ole.openstream(entry).read()
            parts.append(hwp_section_text(zlib.decompress(data, -15) if compressed else data))
    return "\n".join(parts)


READERS = {".pdf": pdf_text, ".hwpx": hwpx_text, ".hwp": hwp_text}


def build_corpus(source_dir: Path) -> dict:
    sys.path.insert(0, str(REPO_ROOT))
    from src.utils.bid_list_xlsx import read_bid_list_rows  # 엑셀 한 장을 행으로 읽는 일만 한다

    files = sorted((p for p in source_dir.iterdir() if p.suffix.lower() in READERS), key=lambda p: unicodedata.normalize("NFC", p.name))
    documents = []
    for no, path in enumerate(files, 1):
        text = READERS[path.suffix.lower()](path)
        lines = [unicodedata.normalize("NFC", line.rstrip()) for line in text.split("\n") if line.strip()]
        documents.append({"no": no, "file": unicodedata.normalize("NFC", path.stem), "lines": lines})
    notices = [row for xlsx in sorted(source_dir.glob(NOTICE_LIST)) for row in read_bid_list_rows(xlsx)]
    return {"documents": documents, "notices": notices}


# --- 검색 ------------------------------------------------------------------------------------

def norm(text) -> str:
    return re.sub(r"[\s,]", "", unicodedata.normalize("NFKC", str(text or "")).lower())


def _clip(text: str) -> str:
    return text if len(text) <= MAX_OUTPUT else text[:MAX_OUTPUT] + "\n... (이하 생략)"


def list_text(corpus: dict, query: str = "") -> str:
    """공고 목록에서 낱말이 든 공고와 문서 번호. 낱말이 없으면 문서 목록."""
    words = [norm(w) for w in query.split() if norm(w)]
    if not words:
        return _clip("\n".join(f"문서 {d['no']}: {d['file']}" for d in corpus["documents"]))
    rows = []
    for row in corpus["notices"]:
        joined = norm(" ".join(str(row.get(c, "")) for c in NOTICE_COLUMNS))
        hits = sum(w in joined for w in words)
        if hits:
            title = norm(row.get("공고명", ""))
            docs = [f"문서 {d['no']}" for d in corpus["documents"] if norm(d["file"]).startswith(title + "_")]
            rows.append((hits, " | ".join(f"{c}={row.get(c, '')}" for c in NOTICE_COLUMNS) + f" | {', '.join(docs) or '문서 없음'}"))
    best = [text for _, text in sorted(rows, key=lambda r: -r[0])]
    return _clip("\n".join(best[:30])) if best else "찾은 것이 없습니다."


def search_text(corpus: dict, query: str, limit: int = 8) -> str:
    """낱말이 많이(드문 낱말일수록 크게) 든 부분을 문서마다 둘까지 돌려준다."""
    words = list(dict.fromkeys(norm(w) for w in query.split() if norm(w)))
    passages = []
    for doc in corpus["documents"]:
        for start in range(0, max(len(doc["lines"]) - (PASSAGE - STEP), 1), STEP):
            lines = doc["lines"][start:start + PASSAGE]
            passages.append((doc, start + 1, lines, norm(doc["file"] + " " + " ".join(lines))))
    weight = {w: math.log(1 + len(passages) / (1 + sum(w in p[3] for p in passages))) for w in words}
    scored = sorted(((sum(weight[w] for w in words if w in p[3]), p) for p in passages), key=lambda s: -s[0])
    out, used = [], {}
    for score, (doc, start, lines, _) in scored:
        if score <= 0 or len(out) >= limit:
            break
        if used.get(doc["no"], 0) >= 2:
            continue
        used[doc["no"]] = used.get(doc["no"], 0) + 1
        out.append(f"[문서 {doc['no']}] {doc['file']} (줄 {start}~{start + len(lines) - 1})\n" + "\n".join(lines)[:400])
    return _clip("\n\n".join(out)) if out else "찾은 것이 없습니다."


def show_text(corpus: dict, no: int, start: int = 1, lines: int = 80) -> str:
    doc = next((d for d in corpus["documents"] if d["no"] == no), None)
    if doc is None:
        return f"문서 {no}가 없습니다."
    start = max(start, 1)
    body = "\n".join(f"{n}: {line}" for n, line in enumerate(doc["lines"][start - 1:start - 1 + lines], start))
    return _clip(f"[문서 {no}] {doc['file']} (전체 {len(doc['lines'])}줄)\n{body}")


def load_corpus(path: Path = CORPUS_PATH) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--corpus", default=str(CORPUS_PATH))
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--source", default=str(SOURCE_DIR))
    sub.add_parser("list").add_argument("query", nargs="*")
    sub.add_parser("search").add_argument("query", nargs="+")
    s = sub.add_parser("show")
    s.add_argument("no", type=int)
    s.add_argument("--start", type=int, default=1)
    s.add_argument("--lines", type=int, default=80)
    a = ap.parse_args()
    path = Path(a.corpus)
    if a.cmd == "build":
        corpus = build_corpus(Path(a.source))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(corpus, ensure_ascii=False), encoding="utf-8")
        empty = [d["file"] for d in corpus["documents"] if sum(map(len, d["lines"])) < 100]
        print(f"문서 {len(corpus['documents'])}개, 공고 {len(corpus['notices'])}건 → {path}")
        if empty:
            print("글자가 거의 없는 문서:", ", ".join(empty))
        return
    corpus = load_corpus(path)
    if a.cmd == "list":
        print(list_text(corpus, " ".join(a.query)))
    elif a.cmd == "search":
        print(search_text(corpus, " ".join(a.query)))
    else:
        print(show_text(corpus, a.no, a.start, a.lines))


if __name__ == "__main__":
    main()
