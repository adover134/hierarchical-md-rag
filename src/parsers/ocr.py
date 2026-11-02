"""스캔 PDF OCR.

텍스트 층이 없는 쪽(이미지만 있는 쪽)을 easyocr로 읽어 텍스트로 바꾼다. 텍스트 층이 있는 쪽은 건드리지 않는다.
OCR 결과는 줄 단위로 묶고, 가로로 멀리 떨어진 칸은 ` | `로 이어 표 행 모양을 남긴다.

환경 변수:
    PDF_OCR_ENABLED  기본 true. false면 OCR을 건너뛴다.
easyocr가 설치돼 있지 않으면 경고만 하고 빈 문자열을 돌려준다(PDF 로딩은 이전과 같이 동작한다).
"""

from __future__ import annotations

import os
import statistics
import sys
from typing import Any, Sequence

MIN_TEXT_CHARS = 30  # 이보다 글자가 적고 이미지가 있으면 스캔 쪽으로 본다
MIN_CONFIDENCE = 0.05  # 이보다 낮은 인식 결과는 잡음으로 버린다
LINE_TOLERANCE = 0.6  # 같은 줄로 묶는 세로 중심 차이(글자 높이 중앙값 대비)
CELL_GAP = 1.5  # 칸 경계로 보는 가로 간격(글자 높이 중앙값 대비)
DPI = 200

_reader: Any = None


def ocr_enabled() -> bool:
    return os.environ.get("PDF_OCR_ENABLED", "true").strip().lower() != "false"


def needs_ocr(page_text: str, image_count: int) -> bool:
    return len((page_text or "").strip()) < MIN_TEXT_CHARS and image_count > 0


def _geometry(box: Sequence[Sequence[float]]) -> tuple[float, float, float, float]:
    xs = [p[0] for p in box]
    ys = [p[1] for p in box]
    return min(xs), max(xs), (min(ys) + max(ys)) / 2, max(ys) - min(ys)


def boxes_to_text(results: Sequence[tuple[Any, str, float]]) -> str:
    """easyocr `readtext` 결과(상자, 글자, 신뢰도)를 줄 단위 텍스트로 만든다."""
    items = []
    for box, text, conf in results:
        text = (text or "").strip()
        if not text or conf < MIN_CONFIDENCE:
            continue
        left, right, cy, height = _geometry(box)
        items.append((cy, left, right, height, text))
    if not items:
        return ""
    unit = statistics.median(h for *_, h, _ in items) or 1.0
    items.sort(key=lambda it: it[0])
    lines: list[list[tuple[float, float, float, float, str]]] = []
    for it in items:
        if lines and abs(it[0] - statistics.mean(x[0] for x in lines[-1])) <= unit * LINE_TOLERANCE:
            lines[-1].append(it)
        else:
            lines.append([it])
    out = []
    for line in lines:
        line.sort(key=lambda it: it[1])
        parts = [line[0][4]]
        for prev, cur in zip(line, line[1:]):
            parts.append(" | " if cur[1] - prev[2] > unit * CELL_GAP else " ")
            parts.append(cur[4])
        out.append("".join(parts))
    return "\n".join(out)


def _get_reader() -> Any:
    global _reader
    if _reader is None:
        import easyocr
        import torch

        _reader = easyocr.Reader(["ko", "en"], gpu=torch.cuda.is_available(), verbose=False)
    return _reader


def ocr_page(fitz_page: Any, dpi: int = DPI) -> str:
    """PyMuPDF 쪽 하나를 그림으로 그려 OCR한 텍스트를 돌려준다. easyocr가 없으면 빈 문자열."""
    import numpy as np

    try:
        reader = _get_reader()
    except ImportError:
        print("경고: easyocr가 없어 스캔 PDF OCR을 건너뜁니다 (pip install easyocr).", file=sys.stderr)
        return ""
    pix = fitz_page.get_pixmap(dpi=dpi)
    image = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.h, pix.w, pix.n)
    return boxes_to_text(reader.readtext(image))
