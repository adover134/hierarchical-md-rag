"""진단 스크립트의 '주된 값' 판정(`scripts/diagnose_answer.py`) 테스트. 기대 문장은 평가셋의 실제 정답이다."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from diagnose_answer import analyse, primary_facts  # noqa: E402


class TestPrimaryFacts:
    def test_parenthetical_breakdown_is_not_primary(self):
        assert primary_facts("기초금액은 금387,660원(동복 264,660원, 하복 123,000원)입니다.") == ["387660"]

    def test_additional_amounts_in_parentheses_are_dropped(self):
        assert primary_facts("기초금액은 50,000,000원(추정가격 45,454,545원, 부가세 4,545,455원)입니다.") == ["50000000"]

    def test_values_outside_parentheses_are_all_primary(self):
        assert primary_facts("동복은 2027년 2월 22일(월), 하복은 2027년 5월 10일(월)까지입니다.") == ["2027년2월22일", "2027년5월10일"]

    def test_falls_back_to_parenthetical_values_when_nothing_else_remains(self):
        assert primary_facts("(120일)") == ["120일"]


def _rec(answer: str, chunk_id: str = "c1") -> dict:
    return {"answer": answer, "retrieved_docs": [{"chunk_id": chunk_id}], "llm_calls": []}


class TestAnswerOk:
    EXPECTED = "기초금액은 금387,660원(동복 264,660원, 하복 123,000원)입니다."
    CHUNKS = {"c1": "기초금액 387,660원 동복 264,660원 하복 123,000원"}

    def test_main_value_alone_passes(self):
        assert analyse(_rec("기초금액은 387,660원입니다."), self.EXPECTED, self.CHUNKS)["answer_ok"] is True

    def test_wrong_main_value_fails(self):
        assert analyse(_rec("기초금액은 264,660원입니다."), self.EXPECTED, self.CHUNKS)["answer_ok"] is False

    def test_one_of_two_primary_values_fails(self):
        expected = "동복은 2027년 2월 22일(월), 하복은 2027년 5월 10일(월)까지입니다."
        chunks = {"c1": "2027년 2월 22일 2027년 5월 10일"}
        assert analyse(_rec("동복은 2027년 2월 22일까지입니다."), expected, chunks)["answer_ok"] is False
