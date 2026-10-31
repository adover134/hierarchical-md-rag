"""새 파서(파서 skill `korean_official_document_parser_skill`의 `run_pipeline.py`)의 출력을 chunker.py 이후 단계에 연결한다.

개선된 버전의 skill은 원래 파이프라인에서 markdown 초안이 확정되기까지의 이전 단계들
(HWP→PDF 변환, PDF→markdown 추출, 정규식 기반 헤더 감지/삽입 — `hwp_converter.py`+
`pdf_loader.py`+`auditor.py`)을 통째로 **대체**한다. skill이 만드는 markdown이 곧
`chunker.py`가 원래 기대하던 "이미 완성된 markdown(헤더 포함)"이므로, 그 앞 단계들은 우리
경로에서 아예 호출되지 않는다.

skill의 출력은 그대로 둔다(재작성/재매핑 없음) — 대체하는 것이지 기존 관례에 끼워맞추는 게
아니다. 대신 소비하는 쪽인 `chunker.py`가 skill의 실제 헤더 레벨(`##`=main_section/
attachment_section, `###`=sub_section)을 직접 인식하도록 `_build_section_map()` 등에
파라미터로 넘긴다(`chunker.py`도 이 목적으로 h1_re/h2_re를 받게 확장해뒀다 — 원래 `#`/`##`
기본값은 그대로 유지되므로 기존 PDF 경로는 영향 없음).

다만 그대로 `chunker.py.process_file()`에 넣을 수는 없다 — `step3_extract_hierarchy()`가 "제N조"
같은 법조문 패턴을, skill이 이미 ##/###로 올바르게 계층화해둔 본문 안에서도 별도로 찾아내 Level 1로
재할당해버리는 버그가 있다(실측 확인: "### 제1조(납품)"처럼 skill이 sub_section으로 정확히
처리해둔 줄을, step3가 "제N조" 정규식으로 독자적으로 찾아 Level 1로 배정하고 step4가 그 자리에
"# 제1조(납품)"를 또 삽입해버림 — 이미 만들어진 계층이 스퓨리어스 H1로 오염된다). 이건 auditor.py가
만든, 헤더가 아직 없는 텍스트를 전제로 설계된 로직이라 헤더가 이미 정확히 배치된 입력에는 안 맞는다.

그래서 이 브리지는 `chunker.py`의 표 평탄화(step2)·텍스트 정리(step2b)·섹션 맵 기반 청킹(step6)은
그대로 재사용하되, 정규식 계층 재추출(step3/step4)만 건너뛴다."""

from __future__ import annotations

import os
import re
import subprocess
import sys
import unicodedata
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.parsers.chunker import parse_frontmatter, step2_flatten_tables, step2b_clean_text, step6_section_split

# skill이 실제로 쓰는 헤더 레벨 — chunker.py의 기본값(#/##)과 다르므로 step6_section_split에
# 명시적으로 넘긴다(chunker.py 쪽 텍스트나 정규식 기본값은 안 바꿈, 이 호출부에서만 사용).
_SKILL_L1_RE = re.compile(r"^## (.+)$", re.MULTILINE)  # main_section / attachment_section
_SKILL_L2_RE = re.compile(r"^### (.+)$", re.MULTILINE)  # sub_section


def skill_dir() -> Path:
    """파서 skill 저장소 위치. 기본은 이 저장소와 같은 폴더의 `korean_official_document_parser_skill`,
    `HWP_SKILL_DIR` 환경변수로 바꿀 수 있다."""
    default = Path(__file__).resolve().parent.parent.parent / "korean_official_document_parser_skill"
    return Path(os.environ.get("HWP_SKILL_DIR") or default)


def convert_with_new_parser(
    hwp_path: Path,
    work_dir: Path,
    backend: str = "ollama",
    model: str = "qwen3.5:9b",
    skip_if_exists: bool = True,
    base_url: str | None = None,
    api_key: str | None = None,
    max_candidates_per_call: int | None = None,
) -> Path:
    """파서 skill(`scripts/run_pipeline.py`)로 계층 구조 markdown을 만든다. 결과를 그대로 반환 — 후처리 없음.

    skill의 `--backend/--base-url/--api-key`를 그대로 전달한다. 로컬 Ollama의 gpt-oss:20b처럼
    Ollama 기본 백엔드와 맞지 않는 모델은 `--backend openai --base-url http://localhost:11434/v1`로
    OpenAI 호환 엔드포인트를 쓴다(이때 Ollama 서버를 `OLLAMA_CONTEXT_LENGTH`를 키워 띄워야 한다 —
    EXPERIMENTS.md 참고).

    `skip_if_exists=True`(기본)면 이미 `work_dir`에 이 파일의 변환 결과가 있으면 다시 안 돌린다."""
    work_dir.mkdir(parents=True, exist_ok=True)
    stem = unicodedata.normalize("NFC", hwp_path.stem)
    out_path = work_dir / f"{stem}.md"

    if not (skip_if_exists and out_path.exists()):
        script = skill_dir() / "scripts" / "run_pipeline.py"
        if not script.exists():
            raise FileNotFoundError(
                f"파서 skill을 찾을 수 없습니다: {script} — "
                "git clone https://github.com/adover134/korean_official_document_parser_skill 후 "
                "HWP_SKILL_DIR 환경변수로 위치를 알려주세요."
            )
        cmd = [
            sys.executable, str(script), str(hwp_path),
            "--pipeline-root", str(work_dir / "_pipeline"),
            "--model", model, "--backend", backend, "-o", str(out_path),
        ]
        if base_url:
            cmd += ["--base-url", base_url]
        if api_key:
            cmd += ["--api-key", api_key]
        if max_candidates_per_call:
            # skill 옵션: Pass1b LLM 호출 하나에 넘길 헤더 후보 수. 느린 로컬 환경에서 한 호출이
            # skill의 호출 제한 시간(300초)을 넘지 않게 줄이는 용도.
            cmd += ["--max-candidates-per-call", str(max_candidates_per_call)]
        subprocess.run(cmd, check=True)

    return out_path


def process_file_no_regex_reextraction(file_path: Path) -> list[dict]:
    """`chunker.py`의 `process_file()`과 동일하지만 step3/step4(정규식 계층 재추출)를 건너뛰고,
    step6의 헤더 인식을 skill의 실제 레벨(##/###)에 맞춘다 — 모듈 docstring 참고."""
    document_title = unicodedata.normalize("NFC", file_path.stem)
    text = file_path.read_text(encoding="utf-8")
    doc_meta, body = parse_frontmatter(text)
    doc_meta["document_title"] = document_title

    body = step2_flatten_tables(body)
    body = step2b_clean_text(body)
    # step3_extract_hierarchy / step4_insert_headers 건너뜀 — 헤더는 파서 skill이 이미 정확히 배치함
    split_results = step6_section_split(body, h1_re=_SKILL_L1_RE, h2_re=_SKILL_L2_RE)

    source = doc_meta.get("document_title", "Unknown")
    name = source.rsplit(".", 1)[0] if "." in source else source
    institution, project_name = "N/A", "N/A"
    if "_" in name:
        # `src/parsers/chunker.py::process_file()`와 동일하게 맞춘다 — 자세한 이유는
        # chunker.py 쪽 주석 참고.
        institution, project_name = name.split("_", 1)

    chunks: list[dict] = []
    for item in split_results:
        content = item["page_content"]
        if not content:
            continue
        meta = item["metadata"]
        chunks.append({
            "page_content": content,
            "metadata": {
                "document_title": doc_meta.get("document_title", "Unknown"),
                "source": source,
                "section_level1": meta["section_level1"],
                "section_level2": meta["section_level2"],
                "page_start": meta["page_start"],
                "page_end": meta["page_end"],
                "org": institution,
                "project_name": project_name,
                "chunk_size": len(content),
                "created_at": datetime.now().isoformat(),
            },
        })
    return chunks
