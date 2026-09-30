"""통화 텍스트 -> v2 스키마 JSON(17개 필드 + meta).

KLUE RoBERTa-large 다중과제 모델(MF_BERT)이 필드별 점수를 내고(AI 처리), decode()가 그 점수를 v2 스키마로
푼다. 활력징후·나이·발생 시점의 숫자는 모델이 찾은 구간을 규칙(parse.py)으로 읽는다. 생성형 모델이 아니라
출력 형식이 깨질 일이 없다.

긴 통화는 512토큰 조각으로 나눠 인코딩한 뒤 원문 토큰 줄로 다시 이어 붙인다(chunking.py). 추론 흐름은
원본 mf_bert/infer.py의 predict()를 한 건 단위로 옮긴 것이다.

가중치(best.pt 약 1.4GB + tokenizer/)는 저장소에 없고 첫 실행 때 Hugging Face 캐시(HF_HOME)로
내려받는다. MF_BERT_DIR 환경변수를 주면 그 로컬 폴더를 쓴다(weights.py).
"""

from __future__ import annotations

import time
from pathlib import Path

import torch
from transformers import AutoTokenizer

from weights import resolve_mf_bert_dir

from .chunking import chunk_text, collate
from .decode import decode
from .model import CallExtractor

#: model_used.llm에 싣는 이름. 스키마 필드명은 llm이지만 이 모델은 생성형이 아니다
MODEL_NAME = "mf-bert-klue-roberta-large"


class MfBertExtractor:
    """best.pt 하나를 메모리에 올려두고 통화 텍스트를 한 건씩 v2 스키마로 바꾼다."""

    def __init__(self, device: str = "auto", run_dir: Path | None = None) -> None:
        if run_dir is None:
            run_dir = resolve_mf_bert_dir()
        if device == "auto":
            device = "cuda" if torch.cuda.is_available() else "cpu"
        self.device = torch.device(device)

        checkpoint = run_dir / "best.pt"
        if not checkpoint.is_file():
            raise FileNotFoundError(f"MF_BERT 체크포인트가 없습니다: {checkpoint} (MF_BERT_DIR 환경변수로 지정)")
        # 학습 인자가 문자열·숫자뿐이라 weights_only=True로 읽힌다 — 공개 저장소에서 받는 파일이라 pickle 실행을 막는다
        state = torch.load(checkpoint, map_location="cpu", weights_only=True)
        args = state["args"]
        # 인코더 가중치는 체크포인트에 다 들어 있어 사전학습 가중치는 받지 않고 구조(config)만 만든다
        model = CallExtractor(
            args["encoder"],
            dropout=args["dropout"],
            last_n_layers=args["last_n_layers"],
            layer_dropout=args["layer_dropout"],
            pretrained=False,
        )
        model.load_state_dict(state["model"])
        self.model = model.to(self.device).eval()
        self.tokenizer = AutoTokenizer.from_pretrained(run_dir / "tokenizer")

    @torch.no_grad()
    def extract(self, text: str) -> tuple[dict, float]:
        """통화 텍스트 1건 -> (v2 스키마 dict, 소요 초)."""
        started = time.perf_counter()
        item = chunk_text(text, self.tokenizer)
        batch = {k: v.to(self.device) for k, v in collate([item], self.tokenizer.pad_token_id).items()}
        with torch.autocast(device_type=self.device.type, dtype=torch.bfloat16, enabled=self.device.type == "cuda"):
            logits = self.model(**batch)
        return decode(text, logits, item["offsets"]), time.perf_counter() - started
