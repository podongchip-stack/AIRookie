"""통화 텍스트 -> 통화 결과 + 환자 수 + 환자별 14개 항목 (MF_BERT 통화 결과판, 2026-11-04 모델).

KLUE RoBERTa-large 인코더 + 결정 디코더(MF_BERT)가 질문("1번째 환자의 성별은?")마다 점수를 낸다(AI 처리).
환자 수 질문으로 환자 수 n을 먼저 정하고, 환자 1..n마다 다음을 고른다.
    성별·나이대·주증상 대분류·소분류·AVPU   후보 선택지 중 점수가 가장 높은 것
    활력징후 8개                            통화 토큰 위에서 고른 구간의 글자를 숫자로 읽는다(vitals.py, 규칙)
    처치 범주(treat_categories)             28개 범주 중 점수가 0보다 큰(확률 0.5 초과) 것의 키 목록(treatments.py)
소분류는 고른 대분류에 속한 후보 중에서 고르고, 대분류가 판단 보류면 소분류도 판단 보류다. 생성형 모델이 아니라
출력 형식이 깨질 일이 없다. KTAS 등급은 예측하지 않는다(규칙 추정은 pre_ktas.py).

통화 결과(call_outcome)는 같은 인코더 출력을 읽는 두 번째 디코더(outcome_decoder.onnx)가 수용·거절·보류 중 점수가
가장 높은 것을 고른다. 2026-10-29 처치판의 인코더·디코더를 고정한 채 이 디코더만 따로 학습해, 환자 항목은 처치판과 같다.

모델은 환자마다 처치 구절 질문("k번째 환자의 처치는?", catalog의 tag_fields)도 묻지만 그 답은 내보내지 않는다 — 처치를
말한 원문 구절(범주의 근거)이지 처치 자체가 아니고, 테스트셋에서 "오"·"이"처럼 1~2글자 조각으로 끊겨 나오는 일이 잦다.
질문 자체는 빼지 않는다: 디코더 안에서 질문끼리 서로 보므로, 빼면 다른 항목의 답이 원본 모델과 달라질 수 있다.

ONNX 세 개를 onnxruntime CPU로 돌린다 — 인코더는 4비트 양자화(HQQ, 마지막 4층은 fp32), 디코더 둘은 fp32. 추론 흐름은
원본 small-MF_BERT_treat_cat/runtime.py의 MFOnnx를 옮긴 것이다. 긴 통화는 512토큰 조각으로 나눠 인코딩한 뒤
원문 토큰 줄로 다시 이어 붙인다(chunking.py).

가중치(encoder.onnx·decoder.onnx·decoder.onnx.data·outcome_decoder.onnx·catalog.json·tokenizer/, 약 690MB)는 저장소에 없고 첫 실행 때
Hugging Face 캐시(HF_HOME)로 내려받는다. MF_BERT_DIR 환경변수를 주면 그 로컬 폴더를 쓴다(weights.py).
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
import onnxruntime as ort
from transformers import AutoTokenizer

from weights import resolve_mf_bert_dir

from .chunking import chunk_text
from .treatments import CATEGORIES, decode_categories
from .vitals import decode

#: model_used.llm에 싣는 이름. 스키마 필드명은 llm이지만 이 모델은 생성형이 아니다
MODEL_NAME = "mf-bert-treat-cat-outcome-klue-roberta-large-int4-hqq"
#: 통화 결과. outcome_decoder.onnx 출력 3자리의 순서이고 catalog.json의 outcomes와 같다(MfBertExtractor가 대조한다)
OUTCOMES = ("수용", "거절", "보류")


class MfBertExtractor:
    """ONNX 세 개를 메모리에 올려두고 통화 텍스트를 한 건씩 통화 결과 + 환자 목록으로 바꾼다."""

    def __init__(self, run_dir: Path | None = None) -> None:
        if run_dir is None:
            run_dir = resolve_mf_bert_dir()
        encoder = run_dir / "encoder.onnx"
        if not encoder.is_file():
            raise FileNotFoundError(f"MF_BERT 가중치가 없습니다: {encoder} (MF_BERT_DIR 환경변수로 지정)")
        providers = ["CPUExecutionProvider"]
        self.encoder = ort.InferenceSession(str(encoder), providers=providers)
        self.decoder = ort.InferenceSession(str(run_dir / "decoder.onnx"), providers=providers)
        outcome_decoder = run_dir / "outcome_decoder.onnx"
        if not outcome_decoder.is_file():
            raise FileNotFoundError(f"MF_BERT 통화 결과 디코더가 없습니다: {outcome_decoder} "
                                    "(2026-11-04 통화 결과판이 아닌 가중치 — weights.py의 MF_BERT_REVISION 확인)")
        self.outcome_decoder = ort.InferenceSession(str(outcome_decoder), providers=providers)
        self.tokenizer = AutoTokenizer.from_pretrained(run_dir / "tokenizer")
        self.catalog = json.loads((run_dir / "catalog.json").read_text(encoding="utf-8"))
        if self.catalog.get("categories") != list(CATEGORIES):
            raise ValueError(f"MF_BERT 가중치의 처치 범주가 코드와 다릅니다: {run_dir / 'catalog.json'} "
                             "(2026-10-29 처치판이 아닌 가중치 — weights.py의 MF_BERT_REVISION 확인)")
        if self.catalog.get("outcomes") != list(OUTCOMES):
            raise ValueError(f"MF_BERT 가중치의 통화 결과 목록이 코드와 다릅니다: {run_dir / 'catalog.json'} "
                             "(2026-11-04 통화 결과판이 아닌 가중치 — weights.py의 MF_BERT_REVISION 확인)")
        self.fields = self.catalog["fields"]
        self.span_fields = set(self.catalog["span_fields"])
        self.tag_fields = set(self.catalog["tag_fields"])
        self.category_fields = set(self.catalog["category_fields"])

    def _encode(self, item: dict) -> np.ndarray:
        """chunk_text() 결과 -> 통화 토큰 벡터 (1, T, H). 조각은 하나씩 넣는다."""
        parts = []
        for chunk, keep in zip(item["chunks"], item["keep"]):
            ids = np.array([chunk], dtype=np.int64)
            vectors = self.encoder.run(None, {"input_ids": ids, "attention_mask": np.ones_like(ids)})[0]
            parts.append(vectors[0, keep])
        return np.concatenate(parts)[None]

    def _scores(self, token_vectors: np.ndarray,
                question_ids: list[int]) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """-> (선택지 점수 (질문 수, 선택지 수), 구간 시작 점수 (질문 수, T+2), 구간 끝 점수 (질문 수, T+2),
        범주 점수 (질문 수, 28)). 처치 구절 태그 점수(tags)는 쓰지 않아 받지 않는다."""
        ids = np.array([question_ids], dtype=np.int64)
        scores, start, end, categories = self.decoder.run(
            ["scores", "span_start", "span_end", "categories"], {"token_vectors": token_vectors, "question_ids": ids})
        return scores[0], start[0], end[0], categories[0]

    def _question_id(self, patient: int, field: str) -> int:
        """patient는 1부터. 0번 질문은 환자 수다."""
        return 1 + (patient - 1) * len(self.fields) + self.fields.index(field)

    def _answer(self, field: str, option: int) -> str:
        if field == "avpu":
            return self.catalog["avpu_values"][str(option)]
        return self.catalog["options"][option]

    def extract(self, text: str) -> tuple[dict, float]:
        """통화 텍스트 1건 -> ({"call_outcome", "patient_count", "patients": [환자별 14개 항목]}, 소요 초)."""
        started = time.perf_counter()
        catalog = self.catalog
        item = chunk_text(text, self.tokenizer)
        token_vectors = self._encode(item)
        width = token_vectors.shape[1]
        outcome_scores = self.outcome_decoder.run(["outcome_scores"], {"token_vectors": token_vectors})[0]
        call_outcome = OUTCOMES[int(np.argmax(outcome_scores[0]))]
        n = int(np.argmax(self._scores(token_vectors, [0])[0][0, catalog["count"]])) + 1
        question_ids = [0] + [self._question_id(i, field) for i in range(1, n + 1) for field in self.fields]
        scores, start, end, categories = self._scores(token_vectors, question_ids)
        patients = []
        for i in range(n):
            patient = {}
            for f, field in enumerate(self.fields):
                q = 1 + i * len(self.fields) + f
                if field in self.tag_fields:  # 처치 구절(근거) — 묻기만 하고 내보내지 않는다(맨 위 설명)
                    continue
                if field in self.span_fields:
                    patient[field] = decode(field, start[q], end[q], text, item["offsets"], width)
                    continue
                if field in self.category_fields:
                    patient[field] = decode_categories(categories[q])
                    continue
                if field == "cc_minor":
                    if patient["cc_major"] == catalog["undecided"]:
                        patient[field] = catalog["undecided"]
                        continue
                    candidates = catalog["cc_minor"][patient["cc_major"]]
                else:
                    candidates = catalog["candidates"][field]
                patient[field] = self._answer(field, candidates[int(np.argmax(scores[q][candidates]))])
            patients.append(patient)
        return {"call_outcome": call_outcome, "patient_count": n, "patients": patients}, time.perf_counter() - started
