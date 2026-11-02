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
