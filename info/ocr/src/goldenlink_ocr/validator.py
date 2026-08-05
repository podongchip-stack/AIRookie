"""인식 결과 검증 — 사람이 확인해야 할 결과를 골라낸다. [규칙 기반]

confidence 만으로는 실패를 못 잡는다는 것이 실측으로 확인됐다. 모델이 같은 토큰을
무한 반복하는 동안에도 confidence 가 0.99로 나왔다. 그래서 반복 생성과 토큰 한도 도달을
별도 신호로 검사한다.
"""

from __future__ import annotations

# 이 길이 미만이면 반복 판정을 하지 않는다 (짧은 표·라벨은 원래 중복 토큰이 많다)
MIN_TOKENS_FOR_REPETITION = 40
# 고유 토큰 비율이 이 값 미만이면 반복 생성으로 본다
UNIQUE_RATIO_THRESHOLD = 0.15


def repetition_ratio(text: str) -> float:
    """공백 기준 토큰의 고유 비율. 낮을수록 같은 토큰이 반복된다는 뜻이다."""
    tokens = text.split()
    if not tokens:
        return 1.0
    return len(set(tokens)) / len(tokens)


def looks_repetitive(text: str) -> bool:
    """반복 생성(루프)으로 보이는지 판정한다."""
    tokens = text.split()
    if len(tokens) < MIN_TOKENS_FOR_REPETITION:
        return False
    return repetition_ratio(text) < UNIQUE_RATIO_THRESHOLD


def review_reasons(recognition: dict) -> list[str]:
    """검토가 필요한 이유 목록을 반환한다. 비어 있으면 정상이다.

    recognition 은 Recognizer.recognize() 의 반환값이다.
    """
    reasons = []
    if recognition["truncated"]:
        reasons.append("토큰 한도 도달 — 출력이 잘렸다")
    if looks_repetitive(recognition["text"]):
        reasons.append(
            f"반복 생성 의심 — 고유 토큰 비율 {repetition_ratio(recognition['text']):.2f}")
    return reasons
