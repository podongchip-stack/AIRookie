"""통화 텍스트 -> v2 스키마 JSON(17개 필드 + meta).

KLUE RoBERTa-large 다중과제 모델(HMM v2)이 필드별 점수를 내고(AI 처리), decode()가 그 점수를 v2 스키마로
푼다. 활력징후·나이·발생 시점의 숫자는 모델이 찾은 구간을 규칙(parse.py)으로 읽는다. 생성형 모델이 아니라
출력 형식이 깨질 일이 없다.

가중치(best.pt 약 1.4GB + tokenizer/)는 저장소에 없고 첫 실행 때 Hugging Face 캐시(HF_HOME)로
내려받는다. HMM_RUN_DIR 환경변수를 주면 그 로컬 폴더를 쓴다(weights.py).
"""

from __future__ import annotations

import time
from pathlib import Path

import torch
from transformers import AutoTokenizer

from weights import resolve_weights_dir

from .decode import decode
from .model import CallExtractor

#: model_used.llm에 싣는 이름. 스키마 필드명은 llm이지만 이 모델은 생성형이 아니다
MODEL_NAME = "hmm-v2-klue-roberta-large"


class HmmExtractor:
    """best.pt 하나를 메모리에 올려두고 통화 텍스트를 한 건씩 v2 스키마로 바꾼다."""

    def __init__(self, device: str = "auto", run_dir: Path | None = None) -> None:
        if run_dir is None:
            run_dir = resolve_weights_dir("HMM_RUN_DIR", "hmm_v2")
        if device == "auto":
            device = "cuda" if torch.cuda.is_available() else "cpu"
        self.device = torch.device(device)

        checkpoint = run_dir / "best.pt"
        if not checkpoint.is_file():
            raise FileNotFoundError(f"HMM 체크포인트가 없습니다: {checkpoint} (HMM_RUN_DIR 환경변수로 지정)")
        # 학습 인자에 Path 객체가 들어 있어 weights_only=True로는 못 읽는다 — 팀이 직접 만든 파일
        state = torch.load(checkpoint, map_location="cpu", weights_only=False)
        args = state["args"]
        model = CallExtractor(
            args["encoder"],
            dropout=args["dropout"],
            last_n_layers=args["last_n_layers"],
            layer_dropout=args["layer_dropout"],
            head_hidden_size=args["head_hidden_size"] or None,
            max_position_embeddings=args["max_tokens"],
            encoder_dropout=args["encoder_dropout"],
        )
        model.load_state_dict(state["model"])
        self.model = model.to(self.device).eval()
        self.max_tokens = args["max_tokens"]
        self.tokenizer = AutoTokenizer.from_pretrained(run_dir / "tokenizer")

    @torch.no_grad()
    def extract(self, text: str) -> tuple[dict, float]:
        """통화 텍스트 1건 -> (v2 스키마 dict, 소요 초)."""
        started = time.perf_counter()
        enc = self.tokenizer(
            text, truncation=True, max_length=self.max_tokens, return_offsets_mapping=True, return_tensors="pt"
        )
        offsets = [tuple(pair) for pair in enc["offset_mapping"][0].tolist()]
        input_ids = enc["input_ids"].to(self.device)
        attention_mask = enc["attention_mask"].to(self.device)
        with torch.autocast(device_type=self.device.type, dtype=torch.bfloat16, enabled=self.device.type == "cuda"):
            logits = self.model(input_ids, attention_mask)
        return decode(text, logits, offsets), time.perf_counter() - started
