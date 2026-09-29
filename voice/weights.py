"""ASR 어댑터·HMM 체크포인트 위치를 정한다.

가중치는 저장소에 없고 Hugging Face Hub에 있다. ASR 어댑터는 자체 저장소(ASR_ADAPTER_REPO_ID),
HMM 체크포인트는 WEIGHTS_REPO_ID의 하위 폴더다. 환경변수로 로컬 폴더를 지정하면 그걸 쓰고, 없으면
Hub에서 받아 HF 캐시(HF_HOME)에 둔다 — 한 번 받으면 다시 받지 않는다.
"""

from __future__ import annotations

import os
from pathlib import Path

from huggingface_hub import snapshot_download

WEIGHTS_REPO_ID = "podongchip/goldenlink-voice-models"
ASR_ADAPTER_REPO_ID = "Playedwell03/qwen3-asr-0.6b-119ko-tiny"


def resolve_asr_adapter_dir() -> Path:
    """ASR_ADAPTER_DIR 환경변수가 있으면 그 폴더, 없으면 Hub의 어댑터 저장소 전체를 받아 그 경로를 돌려준다."""
    local = os.environ.get("ASR_ADAPTER_DIR")
    if local:
        return Path(local)
    return Path(snapshot_download(ASR_ADAPTER_REPO_ID))


def resolve_weights_dir(env_name: str, subdir: str) -> Path:
    """env_name 환경변수가 있으면 그 폴더, 없으면 Hub 저장소의 subdir/를 받아 그 경로를 돌려준다."""
    local = os.environ.get(env_name)
    if local:
        return Path(local)
    root = snapshot_download(WEIGHTS_REPO_ID, allow_patterns=[f"{subdir}/*"])
    return Path(root) / subdir
