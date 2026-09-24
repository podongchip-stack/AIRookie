"""feature/dashboard의 src/types/dashboard.ts (CallSummaryMessage)와 1:1로 대응하는 출력 스키마.

필드를 추가/변경할 때는 dashboard 쪽 타입 정의와 CLAUDE.md도 함께 갱신할 것.
"""

from typing import Literal, Optional

from pydantic import BaseModel

Severity = Literal["high", "medium", "low"]


class TranscriptTurn(BaseModel):
    speaker: str
    timestamp: str
    text: str
    # dashboard 쪽 TranscriptTurn.excludedFromSummary와 이름을 그대로 맞춤 (camelCase).
    # 필터링에서 제외된 턴에만 True로 채우고, 그 외에는 아예 필드를 내보내지 않는다
    # (원본 로그는 raw_text/turns에 그대로 남기고 "요약 제외" 표시만 하는 CLAUDE.md 원칙).
    excludedFromSummary: Optional[bool] = None


class Transcript(BaseModel):
    raw_text: str
    filtered_text: str
    language: str
    timestamp: str
    duration_sec: float
    turns: list[TranscriptTurn]


class Summary(BaseModel):
    patient: str
    mechanism: str
    symptoms: list[str]
    treatment: list[str]
    severity_tag: Severity
    required_department: Optional[str] = None


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
