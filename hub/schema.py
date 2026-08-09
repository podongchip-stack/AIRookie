"""feature/hub의 입출력 pydantic 스키마.

feature/voice, feature/info의 출력 JSON, feature/dashboard로 보내는 출력 JSON과
필드명이 1:1로 대응해야 develop 브랜치 병합 시 파싱 오류가 나지 않는다. 필드를
바꿀 때는 각 브랜치 README.md와 CLAUDE.md도 함께 갱신할 것.
"""
from typing import Literal, Optional

from pydantic import BaseModel, Field

Severity = Literal["high", "medium", "low"]
HospitalStatus = Literal["pending", "approved", "rejected", "confirmed"]


# ── feature/voice → feature/hub (입력) ──────────────────────────────────────

class VoiceSummary(BaseModel):
    """feature/voice CallSummaryMessage.summary와 동일한 필드만 사용한다."""

    patient: str
    mechanism: str
    symptoms: list[str]
    treatment: list[str]
    severity_tag: Severity
    required_department: Optional[str] = None


class VoiceTranscript(BaseModel):
    """feature/voice CallSummaryMessage.transcript 중 hub가 실제로 쓰는 두
    필드만 가져온다 (turns, duration_sec 등은 dashboard까지 전달할 필요가
    없어 모델링하지 않음 — pydantic이 모르는 필드는 무시하므로 그대로 둬도 됨).
    """

    raw_text: str
    filtered_text: str


class VoiceCallSummaryMessage(BaseModel):
    """feature/voice의 전체 출력. summary/source 외에 transcript(원본·필터링
    전문)도 이제 받아서 dashboard까지 그대로 전달한다 (PatientInfo 참고).
    나머지 필드(model_used 등)는 여전히 모델링하지 않는다.
    """

    transcript: VoiceTranscript
    summary: VoiceSummary
    source: Literal["ai"] = "ai"


# ── feature/info → feature/hub (입력) ───────────────────────────────────────

class GpsPoint(BaseModel):
    lat: float
    lng: float


class Specialty(BaseModel):
    department: str
    doctorCount: int
    recentProcedureTags: list[str] = Field(default_factory=list)


class HospitalInfo(BaseModel):
    hospitalId: str
    name: str
    gps: GpsPoint
    availableBedCount: int
    nightDutyAvailable: bool
    specialties: list[Specialty] = Field(default_factory=list)
    source: Literal["rule"] = "rule"
    updatedAt: str


# ── feature/hub → feature/dashboard (출력) ──────────────────────────────────

class PatientInfo(BaseModel):
    injuryStatus: list[str]
    expectedDiagnosis: str
    severityTag: Severity
    rawTranscript: str
    filteredTranscript: str


class SpecialtyMatch(BaseModel):
    department: Optional[str] = None
    score: float = 0.0


class HospitalMatch(BaseModel):
    hospitalId: str
    name: str
    gps: GpsPoint
    distanceKm: float
    specialtyMatch: SpecialtyMatch
    availableBedCount: int
    status: HospitalStatus = "pending"
    etaMin: Optional[int] = None


class HubMatchResult(BaseModel):
    patientInfo: PatientInfo
    zoneActive: list[int]
    hospitals: list[HospitalMatch]
    source: Literal["rule"] = "rule"


# ── feature/dashboard → feature/hub (입력, 수신 주체 hub로 확정) ────────────

ApprovalActionType = Literal["hospital_approve", "hospital_reject", "final_approval"]
Actor = Literal["hospital", "paramedic"]


class ApprovalAction(BaseModel):
    action: ApprovalActionType
    hospital_id: str
    actor: Actor
    timestamp: str


# ── feature/dashboard → feature/hub (입력, 통화 시작/종료 신호) ─────────────
# dashboard의 "통화 시작"/"통화 종료" 버튼이 WebSocket으로 보내는 신호.
# hub는 이 신호를 feature/voice의 로컬 마이크 서버(voice/app.py)로 그대로
# 중계한다 — hub가 오디오 자체를 다루지는 않는다.

CallSignalType = Literal["call_started", "call_ended"]


class CallSignal(BaseModel):
    type: Literal["call_signal"] = "call_signal"
    signal: CallSignalType
    timestamp: str


# ── feature/hub → feature/info (출력, HospitalInfo 부분 갱신) ───────────────

class HospitalBedUpdate(BaseModel):
    """final_approval로 병상이 실제로 줄었을 때만 보내는 부분 갱신(patch).
    HospitalInfo 전체가 아니라 바뀐 필드만 담는다 (info README "통합 데이터
    모델: HospitalInfo" 표의 "2번" 열 참고).
    """

    hospitalId: str
    availableBedCount: int
    status: Literal["confirmed", "rejected"]
    updatedAt: str
    source: Literal["rule"] = "rule"
