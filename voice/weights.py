"""ASR 어댑터·MF_BERT 가중치 위치를 정한다.

가중치는 저장소에 없고 Hugging Face Hub에 있다. ASR 어댑터(ASR_ADAPTER_REPO_ID)와 MF_BERT(MF_BERT_REPO_ID)는
각자 자체 저장소다. 환경변수로 로컬 폴더를 지정하면 그걸 쓰고, 없으면 Hub에서 받아 HF_HOME 아래에 둔다
(ASR은 HF 캐시, MF_BERT는 HF_HOME/local/) — 한 번 받으면 다시 받지 않는다.
"""

from __future__ import annotations

import os
from pathlib import Path

from huggingface_hub import constants, snapshot_download

ASR_ADAPTER_REPO_ID = "Playedwell03/qwen3-asr-0.6b-119ko-tiny"
MF_BERT_REPO_ID = "podongchip/MF_BERT"
# 받을 MF_BERT 버전(태그·브랜치·커밋). "main"을 받으면 Hub에 구조가 바뀐 가중치가 올라올 때 MF_BERT/ 코드와
# 안 맞아 서버가 아예 뜨지 않는다(2026-10-03 10-02 가중치로 실제로 겪음). 그래서 MF_BERT/ 코드와 대조를 마친 커밋
# 해시로 고정한다 — 2026-11-04 통화 결과판 4비트 ONNX(HQQ, 태그 v5-2026-11-04-outcome과 같은 커밋).
# 새 가중치를 들여올 때는 MF_BERT/ 코드를 맞춘 뒤 이 값(또는 MF_BERT_REVISION 환경변수)을 바꾼다. 이전 모델은 이 코드로
# 읽지 못한다 — v4-2026-10-29-hqq는 outcome_decoder.onnx가 없고, v3-2026-10-20-rtn 이하는 처치 출력도 없다
# (MfBertExtractor가 파일과 catalog를 대조해 멈춘다).
MF_BERT_REVISION = os.environ.get("MF_BERT_REVISION", "41bbb84f939fa75ce7767ad66b6c343a24a1ae5b")


def resolve_asr_adapter_dir() -> Path:
    """ASR_ADAPTER_DIR 환경변수가 있으면 그 폴더, 없으면 Hub의 어댑터 저장소 전체를 받아 그 경로를 돌려준다."""
    local = os.environ.get("ASR_ADAPTER_DIR")
    if local:
        return Path(local)
    return Path(snapshot_download(ASR_ADAPTER_REPO_ID))


def resolve_mf_bert_dir() -> Path:
    """MF_BERT_DIR 환경변수가 있으면 그 폴더, 없으면 Hub의 MF_BERT 저장소 전체(ONNX 세 개 + catalog.json + tokenizer/)를 받아 그 경로를 돌려준다.

    HF 캐시의 스냅샷 파일은 서로 다른 blob을 가리키는 심볼릭 링크라, onnxruntime이 decoder.onnx의 외부 데이터
    (decoder.onnx.data)를 찾을 때 링크를 따라가 "모델 폴더 밖 경로"로 거부한다. 그래서 MF_BERT만 링크 없이 실제
    파일로 받는 폴더(local_dir)를 HF_HOME 아래에 리비전별로 둔다. 이미 받았으면 다시 받지 않는다."""
    local = os.environ.get("MF_BERT_DIR")
    if local:
        return Path(local)
    target = Path(constants.HF_HOME) / "local" / f"MF_BERT-{MF_BERT_REVISION[:12]}"
    return Path(snapshot_download(MF_BERT_REPO_ID, revision=MF_BERT_REVISION, local_dir=target))
