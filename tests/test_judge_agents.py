"""채점 agent 정의 file(`.claude/agents/`)과 그것을 읽는 code의 테스트."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

from judge_agents import AGENTS_DIR, agent_body, agent_fields  # noqa: E402


def test_each_agent_file_has_the_required_fields_and_skips_the_instruction_files():
    for name in ("rag-judge", "rag-verifier"):
        fields = agent_fields(name)
        assert fields["name"] == name and fields["description"] and fields["model"] == "opus"
        assert fields["omitClaudeMd"] == "true" and AGENTS_DIR == ROOT / ".claude" / "agents"


def test_the_judge_body_is_the_team_rubric_with_criteria_and_the_grading_instruction():
    from claude_judge import rubric_text
    from judge_grade import BASE_INSTRUCTION
    from judge_verify import INSTRUCTION_LINE
    from src.evaluation.llm_judge import JUDGE_SYSTEM_PROMPT

    body = agent_body("rag-judge")
    assert body.startswith(JUDGE_SYSTEM_PROMPT)  # 팀 rubric이 바뀌면 이 file도 고쳐야 한다
    assert body == f"{rubric_text().rstrip(chr(10))}\n\n## 채점 지시\n{BASE_INSTRUCTION}\n{INSTRUCTION_LINE}\n"


def test_the_verifier_body_is_the_prompt_the_code_sends():
    from judge_verify import VERIFY_PROMPT

    assert agent_body("rag-verifier").rstrip("\n") == VERIFY_PROMPT
