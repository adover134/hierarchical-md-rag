"""3x2 비교 보고서(`scripts/grid_report.py`)의 쌍체 비교 계산 테스트."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from grid_report import cell_name, paired_summary  # noqa: E402


def test_paired_summary_counts_and_mean():
    r = paired_summary([3, 4, 5, 5], [4, 4, 3, 5])
    assert (r["up"], r["down"], r["same"]) == (1, 1, 2)
    assert abs(r["mean_diff"] - (-0.25)) < 1e-9
    assert r["p"] == 1.0


def test_paired_summary_sign_test_is_two_sided():
    r = paired_summary([0] * 8, [1] * 8)
    assert r["up"] == 8 and abs(r["p"] - 2 / 256) < 1e-9


def test_paired_summary_all_equal_has_p_one():
    assert paired_summary([2, 2], [2, 2])["p"] == 1.0


def test_cell_name():
    assert cell_name("proc", "cur_db") == "proc_on_cur_db"


def test_mean_and_paired_summary_skip_not_applicable_scores():
    from grid_report import _mean

    assert _mean([5, None, 3]) == 4.0
    r = paired_summary([5, None, 3], [5, 2, 4])
    assert (r["up"], r["down"], r["same"]) == (1, 0, 1)  # None이 낀 쌍은 건너뛴다


def test_summary_table_shows_how_many_refusals_were_excluded_from_faithfulness(monkeypatch):
    import grid_report as gr

    cell = {("new20", "m1"): {"correctness": 5, "answer_coverage": 5, "faithfulness": 4, "context_relevance": 5},
            ("new20", "m2"): {"correctness": 0, "answer_coverage": 0, "faithfulness": None, "context_relevance": 3}}
    scores = {gr.cell_name(p, d): cell for p, _ in gr.PROCESSES for d, _ in gr.DBS}
    table = gr.summary_table(scores)
    assert "4.000 (거부 1건 제외)" in table
    assert "2.500" in table  # 다른 축은 그대로
