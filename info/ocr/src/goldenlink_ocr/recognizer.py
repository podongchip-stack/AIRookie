"""텍스트 인식 — 잘라낸 영역 이미지를 텍스트로 바꾼다. [AI 처리]

PaddleOCR-VL(Apache-2.0)을 transformers로 로드한다. 모델은 로컬 캐시에서만 읽고
런타임에 네트워크에 접근하지 않는다(On-Premise 원칙).
"""

from __future__ import annotations

import gc

import torch
from PIL import Image
from transformers import AutoProcessor, PaddleOCRVLForConditionalGeneration

from .config import RecognizerConfig

_DTYPES = {"bfloat16": torch.bfloat16, "float16": torch.float16, "float32": torch.float32}


class Recognizer:
    """PaddleOCR-VL 래퍼. 영역 이미지 1장을 받아 텍스트를 만든다."""

    def __init__(self, config: RecognizerConfig, device: str = "cuda"):
        self.config = config
        self.device = device
        self.model, self.processor, self.attn_implementation = self._load()

    def _load(self):
        """flash_attention_2 를 먼저 시도하고 미설치면 sdpa 로 폴백한다.

        어느 쪽도 지정하지 않으면 VRAM이 폭증하므로 반드시 명시해야 한다.
        """
        dtype = _DTYPES[self.config.dtype]
        for attn in ("flash_attention_2", "sdpa"):
            try:
                model = PaddleOCRVLForConditionalGeneration.from_pretrained(
                    self.config.repo_id,
                    revision=self.config.revision,
                    dtype=dtype,
                    attn_implementation=attn,
                    local_files_only=True,
                )
            except (ImportError, ValueError):
                if attn == "sdpa":
                    raise
                continue
            processor = AutoProcessor.from_pretrained(
                self.config.repo_id, revision=self.config.revision, local_files_only=True)
            return model.to(self.device).eval(), processor, attn
        raise RuntimeError("인식 모델을 로드하지 못했다")

    def recognize(self, image: Image.Image, task: str) -> dict:
        """영역 이미지 1장을 인식한다.

        반환: {text, generated_tokens, truncated}
        truncated 는 토큰 한도에 걸려 출력이 잘렸다는 뜻으로, 반복 생성의 신호이기도 하다.
        """
        messages = [{
            "role": "user",
            "content": [{"type": "image", "image": image}, {"type": "text", "text": task}],
        }]
        inputs = self.processor.apply_chat_template(
            messages, tokenize=True, add_generation_prompt=True,
            return_dict=True, return_tensors="pt").to(self.model.device)

        with torch.inference_mode():
            output = self.model.generate(
                **inputs,
                max_new_tokens=self.config.max_new_tokens,
                do_sample=False,
                use_cache=True,
                return_dict_in_generate=True,
            )

        generated = output.sequences[:, inputs["input_ids"].shape[1]:]
        text = self.processor.batch_decode(
            generated, skip_special_tokens=True, clean_up_tokenization_spaces=False)[0].strip()
        n_tokens = int(generated.shape[1])
        return {
            "text": text,
            "generated_tokens": n_tokens,
            "truncated": n_tokens >= self.config.max_new_tokens,
        }

    def unload(self) -> None:
        """VRAM을 반환한다. 다른 모델을 올리기 전에 호출한다."""
        del self.model, self.processor
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
