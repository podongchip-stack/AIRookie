"""통화 텍스트 -> summary 6필드(patient·mechanism·symptoms·treatment·severity_tag·required_department).

KLUE RoBERTa-large 다중과제 모델(HMM)이 필드별 점수를 내고(AI 처리), 규칙 조립기가 계약 필드로
맞춘다(규칙 기반 — required_department 도출 포함). 생성형 모델이 아니라 출력 형식이 깨질 일이 없다.

가중치는 저장소에 없다(best.pt 약 1.4GB). HMM_RUN_DIR 폴더에 best.pt와 tokenizer/가 있어야 한다.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import torch
from transformers import AutoTokenizer

from .assemble import load_department_mapping
from .decode import predict
from .model import CallExtractor

HMM_RUN_DIR = Path(os.environ.get("HMM_RUN_DIR", r"C:\Dev\HMM\model_HMM\runs\golden"))

#: model_used.llm에 싣는 이름. 스키마 필드명은 llm이지만 이 모델은 생성형이 아니다
MODEL_NAME = "hmm-klue-roberta-large"


class HmmExtractor:
    """best.pt 하나를 메모리에 올려두고 통화 텍스트를 한 건씩 6필드로 바꾼다."""

    def __init__(self, device: str = "auto", run_dir: Path = HMM_RUN_DIR) -> None:
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
        )
        model.load_state_dict(state["model"])
        self.model = model.to(self.device).eval()
        self.max_tokens = args["max_tokens"]
        self.tokenizer = AutoTokenizer.from_pretrained(run_dir / "tokenizer")
        self.mapping = load_department_mapping()

    def extract(self, text: str) -> tuple[dict, float]:
        """통화 텍스트 1건 -> (summary 6필드, 소요 초)."""
        started = time.perf_counter()
        with torch.autocast(device_type=self.device.type, dtype=torch.bfloat16, enabled=self.device.type == "cuda"):
            result = predict(self.model, self.tokenizer, [text], self.device, self.max_tokens, self.mapping)[0]
        return result["final_output"], time.perf_counter() - started
