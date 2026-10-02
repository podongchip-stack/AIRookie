"""ASR 어댑터·MF_BERT 체크포인트 위치를 정한다.

가중치는 저장소에 없고 Hugging Face Hub에 있다. ASR 어댑터(ASR_ADAPTER_REPO_ID)와 MF_BERT 체크포인트
(MF_BERT_REPO_ID)는 각자 자체 저장소다. 환경변수로 로컬 폴더를 지정하면 그걸 쓰고, 없으면 Hub에서 받아
HF 캐시(HF_HOME)에 둔다 — 한 번 받으면 다시 받지 않는다.
"""

from __future__ import annotations

import os
from pathlib import Path

from huggingface_hub import snapshot_download

ASR_ADAPTER_REPO_ID = "Playedwell03/qwen3-asr-0.6b-119ko-tiny"
MF_BERT_REPO_ID = "podongchip/MF_BERT"
# 받을 MF_BERT 버전(태그·브랜치·커밋). 2026-10-02 Hub에 구조가 바뀐 새 가중치(보기별 어텐션·2층 헤드 등)가 올라왔는데
# 이 저장소의 MF_BERT/ 코드는 아직 09-30 구조라, 최신을 받으면 state_dict가 안 맞아 서버가 아예 뜨지 않았다
# (2026-10-03 실제로 겪음). 코드와 검증된 버전(v1, fold00)을 고정해 두고, 새 구조 코드를 들여오면 이 값(또는
# MF_BERT_REVISION 환경변수)만 바꾼다. 모델 저장소가 이전 모델을 이 태그로 보존해 뒀다.
MF_BERT_REVISION = os.environ.get("MF_BERT_REVISION", "v1-2026-09-30")


def resolve_asr_adapter_dir() -> Path:
    """ASR_ADAPTER_DIR 환경변수가 있으면 그 폴더, 없으면 Hub의 어댑터 저장소 전체를 받아 그 경로를 돌려준다."""
    local = os.environ.get("ASR_ADAPTER_DIR")
    if local:
        return Path(local)
    return Path(snapshot_download(ASR_ADAPTER_REPO_ID))


def resolve_mf_bert_dir() -> Path:
    """MF_BERT_DIR 환경변수가 있으면 그 폴더, 없으면 Hub의 MF_BERT 저장소 전체(best.pt + tokenizer/)를 받아 그 경로를 돌려준다."""
    local = os.environ.get("MF_BERT_DIR")
    if local:
        return Path(local)
    return Path(snapshot_download(MF_BERT_REPO_ID, revision=MF_BERT_REVISION))
