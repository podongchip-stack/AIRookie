"""실시간 음성 필터링: 발화 턴 단위로 의료 관련 여부를 분류한다 (AI 처리).

CLAUDE.md의 "통화 내용 필터링·구조화 | AI (sLLM + KM-BERT)" 항목에 대응하는
경량 분류기 구현체다. 라벨링된 학습 데이터가 없는 상태라 KM-BERT를 직접
파인튜닝하는 대신, 다국어 문장 임베딩 모델로 의료 관련 예시 문장들과의 코사인
유사도를 계산하는 방식을 택했다 (CLAUDE.md가 "경량 분류기 또는 KM-BERT" 둘 중
하나를 허용). 나중에 실제 라벨 데이터가 쌓이면 이 클래스의 구현만 KM-BERT
분류 헤드로 교체하면 되고, 호출부(transcribe.py)는 바뀌지 않는다.

잡담/인사말/통화 연결 발화는 필터링 대상이지만, 원본은 삭제하지 않고
raw_text와 turns 배열에 그대로 남긴다. "요약 제외"만 표시한다.
"""

from __future__ import annotations

from dataclasses import dataclass

from sentence_transformers import SentenceTransformer, util

# 응급이송 통화에서 의료적으로 유의미한 발화의 예시 문장(anchor).
# 카테고리를 넓게 잡아 실제 통화에서 나올 법한 표현 분포를 대략적으로 커버한다.
MEDICAL_ANCHOR_SENTENCES: list[str] = [
    "환자는 의식이 저하되어 있습니다.",
    "호흡 곤란을 호소하고 있습니다.",
    "혈압과 맥박, 산소포화도를 측정했습니다.",
    "교통사고로 흉부에 충격을 입었습니다.",
    "산소를 공급하고 지혈 처치를 완료했습니다.",
    "환자는 50대 남성이고 낙상으로 인한 골절이 의심됩니다.",
    "심정지 상태로 심폐소생술을 시행 중입니다.",
    "복통을 호소하며 구토 증상이 있습니다.",
    "체온이 높고 오한을 호소합니다.",
    "출혈이 지속되고 있어 압박 지혈 중입니다.",
    "환자 나이와 성별, 사고 경위를 안내드립니다.",
    "기저질환으로 당뇨와 고혈압이 있습니다.",
]

DEFAULT_MODEL_NAME = "paraphrase-multilingual-MiniLM-L12-v2"
DEFAULT_THRESHOLD = 0.4


@dataclass
class ClassifiedTurn:
    text: str
    is_relevant: bool
    score: float


class MedicalRelevanceFilter:
    """발화 턴 텍스트 -> 의료 관련 여부(bool) 분류기."""

    def __init__(
        self,
        model_name: str = DEFAULT_MODEL_NAME,
        threshold: float = DEFAULT_THRESHOLD,
        anchor_sentences: list[str] | None = None,
    ) -> None:
        self.threshold = threshold
        self.model = SentenceTransformer(model_name)
        anchors = anchor_sentences or MEDICAL_ANCHOR_SENTENCES
        anchor_embeddings = self.model.encode(anchors, normalize_embeddings=True)
        self._centroid = anchor_embeddings.mean(axis=0, keepdims=True)

    def score(self, text: str) -> float:
        embedding = self.model.encode([text], normalize_embeddings=True)
        return float(util.cos_sim(embedding, self._centroid)[0][0])

    def is_relevant(self, text: str) -> bool:
        return self.score(text) >= self.threshold

    def classify_turns(self, turn_texts: list[str]) -> list[ClassifiedTurn]:
        if not turn_texts:
            return []
        embeddings = self.model.encode(turn_texts, normalize_embeddings=True)
        scores = util.cos_sim(embeddings, self._centroid).numpy().flatten()
        return [
            ClassifiedTurn(text=text, is_relevant=bool(score >= self.threshold), score=float(score))
            for text, score in zip(turn_texts, scores)
        ]
