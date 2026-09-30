"""ASR 어댑터·HMM 체크포인트 위치를 정한다.

가중치는 저장소에 없고 Hugging Face Hub(WEIGHTS_REPO_ID)에 있다. 환경변수로 로컬 폴더를 지정하면
그걸 쓰고, 없으면 Hub에서 필요한 하위 폴더만 받아 HF 캐시(HF_HOME)에 둔다 — 한 번 받으면 다시 받지 않는다.
"""

from __future__ import annotations

import os
from pathlib import Path

from huggingface_hub import snapshot_download

WEIGHTS_REPO_ID = "podongchip/goldenlink-voice-models"


def resolve_weights_dir(env_name: str, subdir: str) -> Path:
    """env_name 환경변수가 있으면 그 폴더, 없으면 Hub 저장소의 subdir/를 받아 그 경로를 돌려준다."""
    local = os.environ.get(env_name)
    if local:
        return Path(local)
    root = snapshot_download(WEIGHTS_REPO_ID, allow_patterns=[f"{subdir}/*"])
    return Path(root) / subdir
