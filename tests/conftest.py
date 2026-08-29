"""`scripts/`가 패키지가 아니라 평범한 스크립트 디렉터리라(다른 스크립트들도 자체적으로
`sys.path.insert`를 쓰는 것과 동일한 이유), `scripts/api.py`를 `import api`로 바로 가져오려면
`scripts/`를 import 경로에 추가해야 한다. 저장소 루트도 추가해야 `from src.graph.nodes import
...`(src는 패키지) 형태의 import가 pytest 실행 방식과 무관하게 항상 동작한다."""

import os
import sys

_REPO_ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(_REPO_ROOT, "scripts"))
sys.path.insert(0, _REPO_ROOT)
