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


class AssessmentConditions(BaseModel):
    """info의 hospital_score.scoring.Conditions를 그대로 옮긴 것. 환자와 무관한
    병원 여건(병상 가동률·과밀·피드 방치 여부)이라 스코어링에는 안 쓰고 그대로
    dashboard에 노출한다(HospitalMatch.reliability가 아니라 여기 남겨두는 이유는
    질환군과 무관해 사건별 매칭 대상이 아니기 때문)."""

    availableBeds: Optional[int] = None
    totalBeds: Optional[int] = None
    bedOccupancy: Optional[float] = None
    overcrowded: bool = False
    bedCountUnknown: bool = False
    feedAgeMinutes: Optional[float] = None
    stale: bool = False
    missingFromFeed: bool = False


class AssessmentGroup(BaseModel):
    """info의 hospital_score.scoring.GroupScore 1건 — 중증질환군 하나에 대한
    신뢰도 계층 판정. tier는 문자열 라벨(declared_yes 등), score/confidence는
    끝까지 곱하지 않는다(hospital_score/README.md "점수 설계" 원칙)."""

    status: str
    tier: str
    score: float
    confidence: str
    basis: list[str] = Field(default_factory=list)
    items: dict = Field(default_factory=dict)


class Assessment(BaseModel):
    """info-v2(hospital_score.scoring.build_payload)가 HospitalInfo에 얹어
    보내는 추가 필드. Optional이라 이 필드 없이 보내는 구 feature/info 데이터도
    그대로 통과한다 — hub는 이 데이터를 finalScore 계산에는 쓰지 않고,
    "왜 이 순위인지" 설명 근거로만 dashboard에 전달한다(HospitalMatch.reliability
    참고, process_voice_summary()가 15개 질환군 중 하나를 골라 채운다)."""

    assessedAt: str
    source: Literal["rule"] = "rule"
    conditions: AssessmentConditions
    evidence: dict = Field(default_factory=dict)
    groups: dict[str, AssessmentGroup] = Field(default_factory=dict)


class BedReliabilityInput(BaseModel):
    """feature/info의 reliability/(infosurv 서빙 모듈)가 HospitalInfo에 얹어
    보내는 병상 정보 신뢰도 예측. XGBoost AFT 생존모델이라 source는 "ai"다.

    hub가 실제로 쓰는 건 predictedSurvivalSec(예측 생존시간)과 bornAt(현재
    claim-version 탄생 시각) 둘이다 — authority는 정보 나이에 따라 계속
    떨어지는 값이라 hub가 매칭 시점마다 bed_reliability.evaluate()로
    재계산한다. authorityAtSend/ttlSec은 info의 전송 시점 스냅샷(로그·대조용).
    """

    predictedSurvivalSec: float
    bornAt: str
    # 생존곡선 척도. raw면 1.0(기본값 — 구 info 데이터 하위호환), info가 잔차
    # 재보정(σR)을 적용해 보내면 그 값 — hub가 같은 곡선을 재계산하는 데 쓴다.
    sigma: float = 1.0
    authorityAtSend: float
    ttlSec: float
    modelTag: str
    source: Literal["ai"] = "ai"


class SevereGroupDeclaration(BaseModel):
    """질환군 하나의 현재 중증질환 수용가능 신고 상태 (feature/info의
    reliability/severe.py — 규칙 기반, 모델 아님)."""

    value: Literal["Y", "불가능"]
    bornAt: str
    # True면 info의 추적 시작부터 이 값이었다 — 실제 신고는 더 오래됐을 수
    # 있어 나이가 하한(좌측검열)이라는 뜻. dashboard는 "최소 X시간 전"으로
    # 표현해야 한다.
    ageIsMin: bool = False


class SevereDeclarations(BaseModel):
    """feature/info가 스냅샷 추적으로 알아낸 중증질환 신고의 탄생 시각.
    E-Gen 응답에는 신고 시각 필드가 없어서 이 값은 info의 추적만이 안다.
    현재 값이 정보미제공인 그룹은 키가 없다."""

    groups: dict[str, SevereGroupDeclaration] = Field(default_factory=dict)
    source: Literal["rule"] = "rule"


class HospitalInfo(BaseModel):
    hospitalId: str
    name: str
    gps: GpsPoint
    availableBedCount: int
    nightDutyAvailable: bool
    specialties: list[Specialty] = Field(default_factory=list)
    source: Literal["rule"] = "rule"
    updatedAt: str
    # E-Gen 응급의료기관 등급(dutyEmclsName, 2026-10-01): 권역응급의료센터/지역응급의료센터/
    # 지역응급의료기관/응급실운영신고기관. 중증 환자 가산(scoring.LEVEL_BONUS_MIN)에 쓴다.
    emergencyLevel: Optional[str] = None
    # feature/info는 병상 수가 미상일 때 availableBedCount에 0을 넣되, bedsByType에
    # 해당 코드(ER_ADULT 등) 키를 넣지 않는 것으로 "미상"과 "확인된 만실"을 구분한다
    # (info/Hospital_inform/info/egen/mapper.py의 build_beds_by_type 참고).
    # 여기에 필드가 없으면 pydantic이 모르는 필드로 흘려버려서 그 구분이 사라진다.
    bedsByType: Optional[dict[str, int]] = None
    # info-v2(hospital_score)가 보내는 신뢰도 진단 결과. 참고: 이 필드가 없어도
    # (즉 Optional 미지정 값으로 와도) 예전처럼 조용히 무시되지 않는다 — pydantic
    # BaseModel 기본값이 extra="ignore"라 애초에 이 필드가 없어도 검증 자체는
    # 깨지지 않는다. Optional로 명시한 이유는 "받으면 실제로 타입 검증까지
    # 하고 싶어서"이지 "안 받으면 깨져서"가 아니다.
    assessment: Optional[Assessment] = None
    # reliability/(infosurv)의 병상 정보 신뢰도 예측. assessment와 같은 패턴 —
    # 이 필드 없이 오는 구 feature/info 데이터도 그대로 통과한다.
    bedReliability: Optional[BedReliabilityInput] = None
    # 중증질환 신고 신선도(규칙 기반). 같은 Optional 패턴.
    severeDeclarations: Optional[SevereDeclarations] = None
    # 응급실 일반(hvec) 외 확장 필드들의 신뢰도 예측 (2026-09-28 다필드 확장).
    # 키는 E-Gen 필드명(hvoc 수술실·hvgc 입원실·hv28 소아 등), 값 구조는
    # bedReliability와 동일. 같은 Optional 패턴.
    bedReliabilityByType: Optional[dict[str, BedReliabilityInput]] = None


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
    # 어떻게 맞췄나(2026-10-01): voice의 required_department와 정확히 같은 과가 있으면 "exact"
    # (score 1.0), 없으면 예상 병명과 진료과명의 임베딩 유사도("embedding"), 진료과가 없으면 "none".
    basis: Literal["exact", "embedding", "none"] = "embedding"
    # 매칭된 진료과의 전문의 수(심평원). 모르면 None — 가산점 없음.
    doctorCount: Optional[int] = None


class ReliabilityInfo(BaseModel):
    """이 병원의 순위가 왜 이렇게 나왔는지 설명하는 부가 정보(2026-08-13 신설).

    finalScore 계산에는 관여하지 않는다 — 순위는 지금과 똑같이 specialtyMatch
    (진료과 임베딩 유사도)와 distanceKm만으로 정해진다. 이 필드는 그 순위 옆에
    "info-v2가 심평원 대조로 판단한 신뢰도는 이렇다"를 추가로 보여주기 위한
    설명용 데이터일 뿐이다. `group`은 15개 중증질환군 중 예상 병명과 가장 가까운
    하나를 hub가 골라 채운 것(process_voice_summary() 참고). 해당 병원에
    `HospitalInfo.assessment`가 없거나 그 질환군 데이터가 없으면 필드 자체가
    None이다 — 구 feature/info 데이터(심평원 미연동)와 섞여 있어도 안전하다.
    """

    group: str
    score: float
    confidence: str
    basis: list[str] = Field(default_factory=list)


class BedReliabilityMatch(BaseModel):
    """이 병원의 병상 숫자를 얼마나 믿어도 되는지 — 매칭 시점에 hub가
    재계산해 dashboard로 내보내는 설명용 필드(2026-09-24 신설).

    ReliabilityInfo(assessment 기반, 중증질환군 수용 신고의 신뢰도)와는 다른
    축이다 — 이쪽은 "가용 병상 수 값 자체가 아직 유효한가"를 본다. 순위
    (finalScore)에는 관여하지 않는다. authority는 지금 시점, rArrive는
    도착 시점(horizonSec 뒤)의 유효 확률. horizonSec는 순위에 쓴 이동 시간
    (HospitalMatch.travelMin — 카카오 ETA, 없으면 보정 추정치)과 같다(2026-09-28).
    """

    authority: float
    rArrive: float
    horizonSec: float
    ttlSec: float
    modelTag: str
    source: Literal["ai"] = "ai"
    # ── 실시간 감쇠 파라미터 (2026-09-28 추가) ──
    # dashboard가 다음 브로드캐스트를 기다리지 않고 authority를 초 단위로 직접
    # 감쇠시켜 그릴 수 있게, 곡선의 파라미터 자체를 같이 보낸다:
    #   S(age) = 1 − Φ((ln age − ln predictedSurvivalSec) / sigma)
    predictedSurvivalSec: Optional[float] = None
    bornAt: Optional[str] = None
    sigma: float = 1.0
    # 병원 대시보드가 "현재 정보 확인"을 누른 이력이 현재 claim에 유효하면,
    # 그 확인 시점의 claim 나이(초). 있으면 확률이 조건부 생존 S(a)/S(u)로
    # 계산된 것이고, dashboard의 로컬 감쇠도 같은 식을 써야 한다(2026-09-29).
    confirmedAgeSec: Optional[float] = None


class SevereFreshness(BaseModel):
    """매칭된 질환군의 중증질환 수용가능 신고가 얼마나 신선한지 — hub가 매칭
    시점에 계산해 내보내는 설명용 필드(2026-09-28 신설, 규칙 기반).

    ReliabilityInfo(같은 신고를 심평원 대조로 "믿을 만한가" 판정)와 상보적이다
    — 이쪽은 "그 신고가 언제 적 것인가"를 본다. ruleRemainingSec은 실측된
    통상 만료 규칙(신고 후 약 9시간, Phase 0 실측 60.1%가 9.0h)에 따른 잔여
    초로, 0이면서 여전히 신고가 떠 있으면 병원이 갱신을 지속 중이라는 뜻이지
    신고가 죽었다는 뜻이 아니다. 순위(finalScore)에는 관여하지 않는다.
    """

    group: str
    value: Literal["Y", "불가능"]
    ageSec: float
    ageIsMin: bool = False
    ruleRemainingSec: float
    source: Literal["rule"] = "rule"


# 순위를 맨 뒤쪽으로 내린 이유(2026-09-28 신설). 후보에서 빼지는 않는다 — 뺑뺑이 방지 원칙.
# declared_no: 관련 중증질환군을 병원이 "수용 불가"로 신고 / beds_full: 병상 0이 확인된 만실
# (미상·오래된 값은 해당 안 됨) / rejected: 이 사건에 대해 병원이 명시적으로 거절.
# 병원이 이 사건에 승인(approved)·확정(confirmed) 응답을 했으면 신고·병상 값보다 그 응답이
# 우선이라 declared_no·beds_full로 내리지 않는다.
DemoteReason = Literal["declared_no", "beds_full", "rejected"]
# 순위 계산에 쓴 이동 시간의 출처. eta: 카카오 도로 기준 소요시간 / estimate: 직선거리 ×
# (같은 사건에서 ETA가 있는 병원들로 보정한 분/km, 없으면 기본값)으로 추정.
TravelBasis = Literal["eta", "estimate"]


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
    # 도로 기준 도착 예상 시간(분, 올림). 카카오모빌리티 다중 목적지 길찾기로 채운다(routing.py,
    # 2026-09-24). 키 없음·조회 실패·반경 10km 밖이면 None. 표시용 원값이고, 순위에는 아래
    # travelMin(ETA가 있으면 같은 값의 올림 전 분)이 들어간다.
    etaMin: Optional[int] = None
    reliability: Optional[ReliabilityInfo] = None
    bedReliability: Optional[BedReliabilityMatch] = None
    severeFreshness: Optional[SevereFreshness] = None
    # 수술실·입원실·소아 등 확장 필드의 신뢰도 환산값 (키 = E-Gen 필드명).
    # bedReliability(응급실 일반)와 같은 계산·같은 설명용 원칙.
    bedReliabilityByType: Optional[dict[str, BedReliabilityMatch]] = None
    # ── 순위 설명 필드 (2026-09-28 신설, 모두 source: "rule") ──
    # 정렬에 쓴 가중합 점수(scoring.final_score). 승인 액션 뒤 재정렬에도 이 값을 쓴다.
    finalScore: Optional[float] = None
    # 순위 계산에 쓴 이동 시간(분)과 그 출처. etaMin은 표시용 올림값, 이건 계산용 원값이다.
    travelMin: Optional[float] = None
    travelBasis: Optional[TravelBasis] = None
    # 순위를 뒤로 내린 이유. 비어 있으면 finalScore 순서 그대로다.
    demoteReasons: list[DemoteReason] = Field(default_factory=list)
    # 병상 값이 오래됐거나(마지막 갱신 1일 초과) 실시간 피드에 아예 없는 병원. 이 경우 병상 0이어도
    # "확인된 만실"로 보지 않는다(beds_full로 안 내림). bedCountUnknown과는 별개 축이다.
    bedDataStale: bool = False
    # 전문성·등급 가산(2026-10-01, scoring.expertise_bonus_min). 이동시간에서 뺀 분과 그 이유.
    emergencyLevel: Optional[str] = None
    travelBonusMin: float = 0.0
    bonusReasons: list[str] = Field(default_factory=list)


class HubMatchResult(BaseModel):
    # 메시지 종류 구분자(2026-09-28 신설). dashboard로 나가는 메시지 중 이것만 type이 없어서
    # dashboard가 `"type" in parsed`로 구분하고 있었다. 기존 판별(identity_info인지 먼저 확인)과
    # 충돌하지 않는다.
    type: Literal["match_result"] = "match_result"
    # 여러 사건(구급차)이 동시에 진행될 수 있어, dashboard가 이 결과를 어느
    # 사건 것인지 구분해 자기 화면에 맞는 것만 골라 쓸 수 있게 한다.
    caseId: str
    patientInfo: PatientInfo
    zoneActive: list[int]
    hospitals: list[HospitalMatch]
    source: Literal["rule"] = "rule"
    # 구급차 대시보드 상단바 표시용(2026-08-11 신설). 병원명(hospitals[].name)과
    # 같은 패턴 — case_apid로 이 사건의 apid를 찾아 AmbulanceInfo.name을 채운다.
    # apid를 못 찾으면(register_case 전에 process_voice_summary가 불린 등 예외
    # 상황) None으로 두고, dashboard는 URL의 apid로 대체 표시한다.
    ambulanceName: Optional[str] = None
    # 이 사건을 연 구급차의 apid(2026-09-24 신설). 브로드캐스트는 모든 대시보드에 모든
    # 사건을 보내므로, 구급차 대시보드가 새로고침 등으로 자기 caseId를 잊었을 때 "내
    # 구급차의 사건"을 다시 골라내려면 이 값이 필요하다. ambulanceName과 같은 조회
    # (register_case로 기억해둔 값)라 못 찾으면 None.
    apid: Optional[str] = None
    # 매칭에 쓴 구급차 좌표(2026-09-24 신설). 대시보드 지도가 구급차를 임시 위치가 아니라
    # 실제 위치에 그리고, 도로 경로(GET /route)의 출발점과 맞추는 데 쓴다. 구급차 레지스트리에
    # 없으면 hub의 기본 좌표(FALLBACK_AMBULANCE_GPS)가 들어간다.
    ambulanceGps: Optional[GpsPoint] = None
    # ambulanceGps가 실제 구급차 위치가 아니라 기본 좌표(서울시청)로 대체된 값인지(2026-09-28
    # 신설). True면 거리·존·순위가 전부 엉뚱한 기준일 수 있다 — 예전엔 콘솔 로그에만 남았다.
    ambulanceGpsFallback: bool = False


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
    # dashboard의 "수용 불가" 버튼이 함께 보내는 거절 사유(action == "hospital_reject"일
    # 때만). hub는 이 값을 순위 계산에 쓰지 않고 feature/info의 거절 로그 수신구
    # (POST /hub/rejection, hospital_score/ingest.py)로 그대로 중계한다 — 점수의
    # 진짜 정답("병원이 실제로 받았는가")은 운영 로그가 쌓여야 나오고, 로그는
    # 소급해서 만들 수 없어서다(CLAUDE.md "거절 로그" 절).
    #
    # 여기서 Literal로 막지 않고 Optional[str]로 두는 건 의도적이다 — 수신구가
    # "관대하게 받는다"(모르는 코드도 UNSPECIFIED로 기록, 필드가 없어도 통과)를
    # 원칙으로 하므로, dashboard가 어휘를 늘렸을 때 hub가 액션 전체를 거부해
    # 그 사이 로그가 사라지는 게 더 나쁘다. 기대값은 아래 4축 어휘:
    #   구조적  : NO_WARD | NO_DEPARTMENT | NO_EQUIPMENT
    #   주기적  : ON_CALL_MISMATCH | NIGHT_UNAVAILABLE
    #   순간적  : BEDS_FULL | OR_OCCUPIED | STAFF_BUSY
    #   환자    : SEVERITY_EXCEEDED | AGE_LIMIT
    #   미기재  : UNSPECIFIED
    # (dashboard types/dashboard.ts의 RejectionReason, info hospital_score/rejection.py의
    #  REASON_AXIS와 같은 어휘. 값이 없거나 hospital_reject가 아니면 None.)
    reason: Optional[str] = None


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


# ── feature/dashboard(병원) → feature/hub (입력, 현재 정보 확인) ─────────────
# 병원 대시보드의 "현재 정보가 맞습니다" 버튼(2026-09-29). E-Gen 자기 신고
# 밖에서 처음 생기는 유효 확인 관측으로, hub가 그 병원 병상 신뢰도를 조건부
# 생존(S(a)/S(u))으로 되올리는 데 쓴다 — 값이 그대로여도 "방금 사람이 확인한
# 정확한 값"임을 시스템이 알게 되는 유일한 경로다. 확인 이력은 의사결정
# 로그에도 남아, 나중에 infosurv의 유효 확인(G1+) 라벨 재료가 된다.

class HospitalInfoConfirm(BaseModel):
    type: Literal["info_confirm"] = "info_confirm"
    hospitalId: str
    timestamp: str


# ── feature/hub → feature/dashboard(병원) (출력, 자기 정보 현황) ─────────────
# 병원 대시보드에 보내는 "귀원 정보 현황"(2026-09-29). identify 직후,
# feature/info의 30분 주기 upsert 직후, 정보 확인 직후에 그 병원 소켓으로만
# 보낸다. 데이터 공급자(병원)가 자기 정보의 신선도를 직접 보게 하는 피드백
# 루프다 — E-Gen 포털엔 이런 피드백이 없어서 수년 묵은 값이 방치된다
# (실측: 전국 가용병상 1위가 2,457일 묵은 값). bedReliability는 horizon 0
# (자기 화면엔 이송 개념이 없으므로 rArrive==authority)으로 환산한 값이고,
# 곡선 파라미터가 실려 있어 화면이 감쇠를 직접 그린다.

class HospitalSelfInfo(BaseModel):
    type: Literal["hospital_self_info"] = "hospital_self_info"
    hospitalId: str
    name: str
    availableBedCount: int
    bedCountUnknown: bool
    updatedAt: str
    bedReliability: Optional[BedReliabilityMatch] = None
    bedReliabilityByType: Optional[dict[str, BedReliabilityMatch]] = None
    severeDeclarations: Optional[SevereDeclarations] = None


# ── feature/hub → feature/dashboard (출력, 자기소개에 대한 즉시 응답) ───────
# DashboardIdentify에 대한 응답. _send_catchup()(사건 기반)과는 별개로, hub가
# 이미 인메모리로 갖고 있는 병원/구급차 레지스트리(update_hospital_info()/
# update_ambulance_info())에서 이름을 즉시 찾아 돌려준다 — 사건이 하나도
# 없어도(통화 전이라도) 상단바에 실명이 뜨게 하기 위해서다. `known`이
# false면 hub가 그 hpid/apid를 아예 모른다는 뜻이라, dashboard는 이걸
# "접근 불가"(존재하지 않는 코드) 판단 근거로 쓴다.
class DashboardIdentityInfo(BaseModel):
    type: Literal["identity_info"] = "identity_info"
    role: DashboardRole
    id: str
    name: Optional[str] = None
    known: bool
