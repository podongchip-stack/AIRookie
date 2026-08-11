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

    caseId: str
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
    # feature/info는 병상 수가 미상일 때 availableBedCount에 0을 넣되, bedsByType에
    # 해당 코드(ER_ADULT 등) 키를 넣지 않는 것으로 "미상"과 "확인된 만실"을 구분한다
    # (info/Hospital_inform/info/egen/mapper.py의 build_beds_by_type 참고).
    # 여기에 필드가 없으면 pydantic이 모르는 필드로 흘려버려서 그 구분이 사라진다.
    bedsByType: Optional[dict[str, int]] = None


class AmbulanceInfo(BaseModel):
    """feature/info → feature/hub : 구급차 레지스트리(Supabase `ambulances`
    테이블)의 부분 미러. HospitalInfo와 같은 upsert 패턴을 그대로 따른다.

    GPS는 대회 데모 단계라 서울 랜드마크로 고정한 값이고(실시간 전송 아님),
    voicePort는 그 구급차 voice 인스턴스가 뜰 포트(장비마다 미리 정해둔 값이라
    안정적)다. voice의 실제 IP는 여기 없다 — 노트북마다 네트워크가 달라 자주
    바뀔 수 있어서, VoiceRegistration으로 voice가 뜰 때 직접 hub에 등록한다.
    """

    apid: str
    name: str
    gps: GpsPoint
    voicePort: int
    source: Literal["rule"] = "rule"
    updatedAt: str


class VoiceRegistration(BaseModel):
    """feature/voice → feature/hub : voice가 뜰 때 자기 IP를 자동 탐지해서
    hub에 알려주는 자가 등록. 포트는 AmbulanceInfo.voicePort로 이미 알고
    있으므로 IP만 받으면 된다. hub는 이걸 받아 (ip, voicePort)를 합쳐
    apid별 voice 주소로 메모리에 저장해뒀다가, 통화 시작/종료 신호를
    중계할 때(CallSignal) 그 주소로 보낸다.
    """

    apid: str
    ip: str


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
    # availableBedCount가 0일 때 그게 "확인된 만실"인지 "미상"인지 구분한다.
    # availableBedCount 자체를 Optional로 바꾸면 dashboard의 기존 타입이 깨지므로
    # 필드를 덧붙이는 쪽을 택했다 — dashboard는 이 값을 읽기 전까지 그대로 동작한다.
    bedCountUnknown: bool = False
    status: HospitalStatus = "pending"
    etaMin: Optional[int] = None


class HubMatchResult(BaseModel):
    # 여러 사건(구급차)이 동시에 진행될 수 있어, dashboard가 이 결과를 어느
    # 사건 것인지 구분해 자기 화면에 맞는 것만 골라 쓸 수 있게 한다.
    caseId: str
    patientInfo: PatientInfo
    zoneActive: list[int]
    hospitals: list[HospitalMatch]
    source: Literal["rule"] = "rule"


# ── feature/dashboard → feature/hub (입력, 수신 주체 hub로 확정) ────────────

ApprovalActionType = Literal["hospital_approve", "hospital_reject", "final_approval"]
Actor = Literal["hospital", "paramedic"]


class ApprovalAction(BaseModel):
    # 여러 사건이 동시에 진행되면 hospital_id만으로는 "어느 사건에 대한
    # 승인인지" 특정할 수 없다 — dashboard는 자기가 보고 있는 사건의 caseId를
    # 이미 HubMatchResult로 받아 알고 있으므로 그대로 실어 보낸다.
    caseId: str
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
    # apid로 "어느 구급차/voice인지"를, caseId로 "이번 통화가 어느 사건인지"를
    # 구분한다. call_started 시점에 dashboard가 caseId를 새로 만들어 실어
    # 보내고, hub는 이 apid로 등록된 voice 주소(VoiceRegistration 참고)를 찾아
    # 신호를 중계하면서 caseId도 같이 넘긴다 — voice는 나중에 요약을 보낼 때
    # 이 caseId를 그대로 돌려줘야 한다.
    type: Literal["call_signal"] = "call_signal"
    signal: CallSignalType
    timestamp: str
    apid: str
    caseId: str


# ── feature/dashboard → feature/hub (입력, 소켓 연결 시 자기소개) ───────────
# hub는 그동안 dashboard 연결을 완전히 익명으로 취급해서, 연결된 소켓
# 전체에 그냥 브로드캐스트만 했다. 그러면 이미 진행 중인 사건이 있는
# 상태에서 새 대시보드 탭이 뒤늦게 열리면, 그 탭은 연결 전에 이미 끝난
# 브로드캐스트를 놓쳐서 화면에 아무 사건도 안 뜨는 문제가 있었다
# (2026-08-11 실제 재현됨 — 구급1호차·서울대병원 탭이 연결된 상태에서 이미
# 매칭이 끝난 뒤, 한양대병원 탭을 새로 열면 그 사건이 안 보였음). 이
# 메시지로 자기가 병원인지 구급차인지, 어느 hpid/apid인지 알려주면 hub가
# 연결 시점에 관련된 사건들을 즉시 찾아 그 소켓에만 돌려준다(app.py의
# `_send_catchup()` 참고).

DashboardRole = Literal["hospital", "ambulance"]


class DashboardIdentify(BaseModel):
    type: Literal["identify"] = "identify"
    role: DashboardRole
    # role="hospital"이면 hpid, role="ambulance"면 apid.
    id: str


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
