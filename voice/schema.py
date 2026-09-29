"""feature/dashboard의 src/types/dashboard.ts (CallSummaryMessage)와 1:1로 대응하는 출력 스키마.

필드를 추가/변경할 때는 dashboard 쪽 타입 정의와 CLAUDE.md도 함께 갱신할 것.
"""

from typing import Literal, Optional

from pydantic import BaseModel


class TranscriptTurn(BaseModel):
    speaker: str
    timestamp: str
    text: str
    # dashboard 쪽 TranscriptTurn.excludedFromSummary와 이름을 그대로 맞춤 (camelCase).
    # 발화 필터링 단계가 없어져 지금은 채우는 곳이 없고 항상 필드가 빠진 채 나간다.
    # dashboard 타입과 1:1 계약이라 필드 자체는 남겨둔다.
    excludedFromSummary: Optional[bool] = None


class Transcript(BaseModel):
    raw_text: str
    filtered_text: str
    language: str
    timestamp: str
    duration_sec: float
    turns: list[TranscriptTurn]


class Summary(BaseModel):
    """HMM v2 출력 그대로 — C:\Dev\HMM\data_v3\필드_설명.md의 v2 스키마 17개 필드 + meta.

    값이 null인 것도 의미가 있다(모델이 안 배운 필드, 통화에 없는 정보). 중첩 구조는 모델 출력을 그대로
    두고 여기서는 검증하지 않는다 — hub 담당자가 필요한 필드부터 타입을 좁힌다.
    """

    call_type: Optional[str] = None
    ktas_level: int
    ktas_evidence: Optional[list[str]] = None
    chief_complaint: dict
    suspected_diagnosis: list[dict]
    vitals: list[dict]
    consciousness: list[dict]
    symptoms: list[dict]
    onset: dict
    incidents: list[dict]
    disease_category: Optional[str] = None
    injuries: list[dict]
    treatments: list[dict]
    age: dict
    sex: Optional[str] = None
    medications: dict
    notes: Optional[str] = None
    meta: dict


class ModelUsed(BaseModel):
    stt: str
    llm: str


class CallSummaryMessage(BaseModel):
    # 여러 사건(구급차)이 동시에 진행될 수 있어 hub가 이 통화를 어느 사건과
    # 짝지을지 구분하는 값. hub가 통화 시작 신호를 중계할 때 함께 보내주고,
    # voice/app.py가 세션에 들고 있다가 그대로 돌려준다 (feature/hub
    # CallSignal.caseId 참고). 실시간 파이프라인과 무관한 CLI 단독 실행
    # (call_capture.py 등)에서는 자동 생성된 값이 들어간다.
    caseId: str
    transcript: Transcript
    summary: Summary
    source: Literal["ai"] = "ai"
    model_used: ModelUsed

    def to_payload(self) -> dict:
        """hub 전송·저장용 dict. v2 필드의 null은 남기고(의미가 있다), 항상 비어 있는
        turns[].excludedFromSummary만 빼서 예전 전송 형태를 유지한다."""
        payload = self.model_dump()
        for turn in payload["transcript"]["turns"]:
            if turn["excludedFromSummary"] is None:
                del turn["excludedFromSummary"]
        return payload
