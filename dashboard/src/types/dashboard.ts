// feature/hub README.md > "입출력 데이터 포맷"의 출력 스키마 4(feature/hub → feature/dashboard)와
// 입력 스키마 3(feature/dashboard → feature/hub, 승인 액션)에 1:1로 대응한다.
// dashboard는 feature/hub와만 직접 통신하므로(CLAUDE.md), feature/voice·feature/info의
// 원본 스키마(transcript, vitals 등)는 여기서 다루지 않는다. 필드를 추가/변경할 때는
// feature/hub README도 함께 확인할 것 — 출력 스키마 4는 아직 "가안, 팀 리뷰 후 확정 예정" 상태다.

export type Severity = "high" | "medium" | "low";

export interface PatientInfo {
  injuryStatus: string[];
  expectedDiagnosis: string;
  severityTag: Severity;
  // feature/voice의 통화 원문 전체(raw_text)와 실시간 음성 필터링을 거친 텍스트
  // (filtered_text). 예전엔 hub가 summary만 쓰고 버렸는데, 이제 hub의
  // VoiceCallSummaryMessage.transcript를 그대로 받아 여기로 넘겨준다.
  rawTranscript: string;
  filteredTranscript: string;
}

// 예상 병명 ↔ 병원 진료과 임베딩 유사도 매칭 결과. score를 그대로 노출해
// "왜 이 병원 순위인지" 설명 가능하게 유지한다 (hub README "설명 가능성 유지" 참고).
export interface SpecialtyMatch {
  department: string;
  score: number;
}

export type HospitalStatus = "pending" | "approved" | "rejected" | "confirmed";

export type ReliabilityConfidence = "high" | "medium" | "low";

// info-v2(hospital_score)가 심평원(HIRA) 대조로 판정한 신뢰도 — "왜 이 순위인지"의
// 근거를 보여주기 위한 부가 정보다. specialtyMatch/distanceKm(순위 계산에 실제로
// 쓰이는 값)와는 별개이며, 이 필드는 순위에 전혀 영향을 주지 않는다(2026-08-13,
// hub README "hospital_score 연동" 참고 — 반영 범위를 설명용으로만 한정하기로
// 팀에서 확정함). 병원에 assessment 데이터가 없거나(구 feature/info 정보) 예상
// 병명이 매칭된 질환군에 그 병원의 판정이 없으면 필드 자체가 없다.
export interface ReliabilityInfo {
  group: string;
  score: number;
  confidence: ReliabilityConfidence;
  basis: string[];
}

export interface HospitalCandidate {
  hospitalId: string;
  name: string;
  gps: { lat: number; lng: number };
  distanceKm: number;
  specialtyMatch: SpecialtyMatch;
  availableBedCount: number;
  // availableBedCount가 0일 때 그게 "확인된 만실"인지 "미상"인지 구분한다. hub가
  // feature/info의 bedsByType(병상 종류별 키 유무)으로 판정해 내보낸다 (hub README
  // "입출력 데이터 포맷" 참고). true면 화면엔 "0"이 아니라 "미상"으로 표시해야
  // 한다 — 미상을 만실처럼 보여주면 구급대원이 실제로 자리가 있을 수도 있는
  // 병원을 스스로 후보에서 빼게 되어 뺑뺑이 방지 목적과 어긋난다.
  bedCountUnknown: boolean;
  status: HospitalStatus;
  etaMin?: number;
  reliability?: ReliabilityInfo;
}

export interface HubMatchResult {
  // 여러 구급차가 동시에 사건을 진행할 수 있어, hub가 이 결과를 어느 사건
  // 것인지 구분하는 값. dashboard는 이 값을 키로 여러 사건을 동시에 들고
  // 있는다(DashboardState.matchResults 참고) — 구급차 대시보드는 자기
  // caseId로 걸러 하나만 쓰고, 병원 대시보드는 자기 hospitalId가 있는
  // 사건 전부를 카드로 나열한다.
  caseId: string;
  patientInfo: PatientInfo;
  zoneActive: number[];
  hospitals: HospitalCandidate[];
  source: "rule";
  // 아직 hub 스키마에 확정된 필드는 아니다 — 구급차 레지스트리(Supabase
  // ambulances 테이블)가 hub 쪽에 연동되면 이 필드로 실명("구급 1호차")이
  // 오도록 준비만 해둔다. 안 오면 대시보드가 URL의 ?id=만으로 표시를 대신한다.
  ambulanceName?: string;
}

export type ApprovalActionType =
  | "hospital_approve"
  | "hospital_reject"
  | "final_approval";

export type Actor = "hospital" | "paramedic";

// info-v2(hospital_score)의 거절 로그 수신구(POST /hub/rejection)가 쓰는 4축 어휘
// (CLAUDE.md "거절 로그" 절, 2026-08-12). 구조적(NO_WARD/NO_DEPARTMENT/NO_EQUIPMENT)
// 사유는 병원 역량 벡터 자체를 고치는 신호로, 주기적(ON_CALL_MISMATCH/NIGHT_UNAVAILABLE)
// 은 시간대 패턴으로, 순간적(BEDS_FULL/OR_OCCUPIED/STAFF_BUSY)은 그때그때의 여건으로
// 갱신 대상이 서로 달라 축을 나눠 요청됐다 — 하나로 뭉치면 일시적 사정 때문에 그
// 병원이 영구히 후보에서 밀려나는 문제가 생긴다.
// NO_RESPONSE는 여기 없다 — "병원이 응답 자체를 안 함"을 위한 값이라 이 버튼(응답을
// 눌렀을 때만 발생)과는 안 맞는다. hub/info 쪽 타임아웃 처리가 필요한 별도 사안이다.
export type RejectionReason =
  | "NO_WARD"
  | "NO_DEPARTMENT"
  | "NO_EQUIPMENT"
  | "ON_CALL_MISMATCH"
  | "NIGHT_UNAVAILABLE"
  | "BEDS_FULL"
  | "OR_OCCUPIED"
  | "STAFF_BUSY"
  | "SEVERITY_EXCEEDED"
  | "AGE_LIMIT"
  | "UNSPECIFIED";

// dashboard → feature/hub. 이 스키마만 CLAUDE.md/hub README 모두 snake_case로 확정돼 있다.
export interface ApprovalAction {
  // 여러 사건이 동시에 진행되면 hospital_id만으로는 "어느 사건에 대한
  // 승인인지" 특정할 수 없다 — 자기가 보고 있는 사건의 caseId(hub가 보낸
  // HubMatchResult.caseId)를 그대로 실어 보낸다.
  caseId: string;
  action: ApprovalActionType;
  hospital_id: string;
  actor: Actor;
  timestamp: string;
  // action이 "hospital_reject"일 때만 채워진다 — hub는 지금도 이 필드 없이 오는
  // 액션을 그대로 받아 UNSPECIFIED로 기록하므로, 값이 없어도 기존 연동은 깨지지 않는다.
  reason?: RejectionReason;
}

// 통화 시연 컴포넌트(구급차 대시보드)가 hub에 보내는 통화 시작/종료 신호.
// hub가 이 신호를 받아 그 구급차(apid)의 feature/voice 인스턴스에 시작/종료를
// 중계한다 — sendAudioChunk()로 보내는 브라우저 오디오는 화면 시각화용으로만
// 남고, 실제 STT 입력으로는 쓰지 않는다.
export type CallSignalType = "call_started" | "call_ended";

export interface CallSignal {
  type: "call_signal";
  signal: CallSignalType;
  timestamp: string;
  // 어느 구급차인지 — hub가 중계할 voice 주소를 찾는 키.
  apid: string;
  // 이번 통화의 사건 식별자. 구급차 대시보드가 통화 시작 시 새로 생성해 보낸다.
  caseId: string;
}

export type DashboardRole = "ambulance" | "hospital";

// dashboard → feature/hub. 소켓 연결 직후 보내는 자기소개. hub는 그동안 연결을
// 완전히 익명으로 취급해서, 새 탭이 이미 진행 중인 사건이 있는 상태로 뒤늦게
// 열리면 그 사건의 이전 브로드캐스트를 놓쳐 화면에 아무것도 안 뜨는 문제가
// 있었다(2026-08-11 실제 재현됨). 이걸로 자기가 병원인지 구급차인지, 어느
// hpid/apid인지 알려주면 hub가 관련된 사건들을 연결 시점에 바로 되돌려준다.
export interface DashboardIdentify {
  type: "identify";
  role: DashboardRole;
  // role="hospital"이면 hpid, role="ambulance"면 apid.
  id: string;
}

// feature/hub → dashboard. DashboardIdentify에 대한 첫 번째 응답(2026-08-11
// 신설). hospitals[].name/HubMatchResult.ambulanceName은 둘 다 "사건이 있어야만"
// 이름이 오는 한계가 있었다 — 이건 사건 유무와 무관하게, hub가 이미 아는
// 병원/구급차 레지스트리에서 즉시 이름을 조회해 돌려준다. known이 false면
// hub가 그 hpid/apid를 아예 모른다는 뜻이라 "존재하지 않는 접근 코드"로
// 판단할 수 있다(hub README "출력 스키마 6" 참고).
export interface DashboardIdentityInfo {
  type: "identity_info";
  role: DashboardRole;
  id: string;
  name: string | null;
  known: boolean;
}

// 신원 확인 결과. known=null은 "아직 hub 응답을 못 받음(확인 중)" —
// 접근 불가로 단정하면 안 되고, false와는 구분해서 다뤄야 한다.
export interface IdentityState {
  name: string | null;
  known: boolean | null;
}

export interface DashboardState {
  // caseId를 키로 하는 맵 — 여러 구급차의 사건을 동시에 들고 있을 수 있다.
  // 구급차 대시보드는 자기 caseId 하나만 꺼내 쓰고, 병원 대시보드는 자기
  // hospitalId가 후보로 들어있는 사건을 전부 걸러 카드로 나열한다.
  matchResults: Record<string, HubMatchResult>;
  // hub 메시지 자체엔 타임스탬프가 없어서, "정보 수신 후 경과" 표시를 위해
  // 대시보드가 최초 수신 시각을 로컬에서 기록해 둔다.
  receivedAt: string | null;
  // 이 소켓(=이 apid/hpid)의 신원 확인 결과. matchResults와 분리해서 관리하는
  // 이유는 사건과 무관하게 항상 표시돼야 하기 때문이다.
  identity: IdentityState;
}

export type InboundMessage = HubMatchResult | DashboardIdentityInfo;
