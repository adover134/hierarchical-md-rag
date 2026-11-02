"""스캔 PDF OCR 보조 함수 단위 테스트 — OCR 엔진 없이 좌표·텍스트만 쓴다."""

from src.parsers.ocr import boxes_to_text, needs_ocr


def _box(x, y, w=100, h=30):
    return [[x, y], [x + w, y], [x + w, y + h], [x, y + h]]


def test_needs_ocr_only_for_pages_with_images_and_no_text():
    assert needs_ocr("", 1)
    assert needs_ocr("  \n ", 2)
    assert not needs_ocr("", 0)  # 이미지도 글자도 없는 빈 쪽은 읽을 것이 없다
    assert not needs_ocr("사업명: 테스트 사업의 입찰 공고문입니다. 아래와 같이 공고합니다.", 3)


def test_boxes_are_grouped_into_lines_top_to_bottom_and_left_to_right():
    results = [
        (_box(300, 200), "둘째줄", 0.9),
        (_box(100, 100), "첫째줄", 0.9),
        (_box(220, 102), "이어서", 0.9),  # 같은 줄, 세로 위치가 살짝 다르다
    ]
    assert boxes_to_text(results) == "첫째줄 이어서\n둘째줄"


def test_wide_horizontal_gap_becomes_a_table_cell_separator():
    results = [
        (_box(100, 100, w=80), "단가(원)", 0.9),
        (_box(600, 100, w=120), "금액(원)", 0.9),
    ]
    assert boxes_to_text(results) == "단가(원) | 금액(원)"


def test_low_confidence_and_blank_boxes_are_dropped():
    results = [
        (_box(100, 100), "남는 글자", 0.9),
        (_box(250, 100), "잡음", 0.01),
        (_box(400, 100), "   ", 0.9),
    ]
    assert boxes_to_text(results) == "남는 글자"


def test_empty_results_give_empty_text():
    assert boxes_to_text([]) == ""
