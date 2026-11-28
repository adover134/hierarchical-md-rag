"""채점 agent의 지시문을 `.claude/agents/`의 markdown에서 읽는다.

지시문은 이 file에만 둔다. 점수에 영향을 주므로 바꾸기 전과 후의 원문을 보이고 승인받는다.
  rag-judge.md     채점자: 루브릭(팀 rubric + 추가 기준)과 채점 지시
  rag-verifier.md  검증자: 원본에서 대상 공고와 답을 확인하는 지시문
"""

from __future__ import annotations

from pathlib import Path

AGENTS_DIR = Path(__file__).resolve().parent.parent / ".claude" / "agents"
_INSTRUCTION_HEADING = "\n\n## 채점 지시\n"
_VERIFICATION_START = '항목의 "검증 결과"'


def _parts(name: str) -> tuple[str, str]:
    _, head, body = (AGENTS_DIR / f"{name}.md").read_text(encoding="utf-8").split("---\n", 2)
    return head, body


def agent_fields(name: str) -> dict[str, str]:
    return dict(line.split(": ", 1) for line in _parts(name)[0].splitlines() if ": " in line)


def agent_body(name: str) -> str:
    return _parts(name)[1]


def judge_sections() -> tuple[str, str, str]:
    """채점자 본문을 (루브릭, 기본 채점 지시, 검증 결과 지시)로 나눈다."""
    rubric, instruction = agent_body("rag-judge").split(_INSTRUCTION_HEADING)
    lines = instruction.rstrip("\n").split("\n")
    start = next(i for i, line in enumerate(lines) if line.startswith(_VERIFICATION_START))
    return rubric + "\n", "\n".join(lines[:start]), "\n".join(lines[start:])
