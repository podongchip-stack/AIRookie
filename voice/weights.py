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
# 받을 MF_BERT 버전(태그·브랜치·커밋). "main"을 받으면 Hub에 구조가 바뀐 가중치가 올라올 때 MF_BERT/ 코드와
# state_dict가 안 맞아 서버가 아예 뜨지 않는다(2026-10-03 10-02 가중치로 실제로 겪음). 그래서 MF_BERT/ 코드와 대조를
# 마친 커밋 해시로 고정한다 — 2026-10-02 모델(보기별 어텐션·2층 헤드). 새 가중치를 들여올 때는 MF_BERT/ 코드를 맞춘 뒤
# 이 값(또는 MF_BERT_REVISION 환경변수)을 바꾼다. 이전 모델은 "v1-2026-09-30" 태그로 받는다(이 코드로도 읽힌다).
MF_BERT_REVISION = os.environ.get("MF_BERT_REVISION", "f1d3e1dbd41424e1bb32cf4aded891ed48b39df6")


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
