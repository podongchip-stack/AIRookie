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
  // hub 2026-10-01~: voice v2(MF_BERT)가 주는 표시용 값. 예전 voice면 비어 있다.
  patient?: string | null;
  treatment?: string[];
  ktasLevel?: number | null;
  vitals?: Vital[];
  consciousness?: string | null;
  onset?: string | null;
  chiefComplaint?: string | null;
  requiredDepartment?: string | null;
  // 추가 통화 덧붙이기(2026-10-05): 몇 번째 통화 요약인지와 앞선 요약들. 1이면 현장 첫 통화(구버전 hub면 없음).
  callRound?: number;
  previousCalls?: PatientUpdate[];
  // 구급대원 확인·수정(Override, 2026-10-13). "ai"면 AI 요약 그대로(구급대원 확인 전), "paramedic"이면 구급대원이
  // 확인한 갱신본. overrides는 고친 칸별 AI 값 → 구급대원 값. 구버전 hub면 없다.
  confirmedBy?: "ai" | "paramedic";
  confirmedAt?: string | null;
  overrides?: OverrideRecord[];
}

export interface OverrideRecord {
  field: "expectedDiagnosis" | "injuryStatus" | "ktasLevel" | "requiredDepartment" | "chiefComplaint";
  ai: string | number | string[] | null;
  value: string | number | string[] | null;
  at: string;
}

// 구급대원의 통화 요약 확인·수정(dashboard → hub, WebSocket). 보낸 칸만 바뀌고, 아무 칸도 없으면 "수정 없이 확인".
export interface PatientOverrideChanges {
  expectedDiagnosis?: string;
  injuryStatus?: string[];
  ktasLevel?: number;
  requiredDepartment?: string | null;
  chiefComplaint?: string | null;
}

export interface PatientOverrideMessage extends PatientOverrideChanges {
  type: "patient_override";
  caseId: string;
  timestamp: string;
}

// 앞선 통화 요약 한 건(hub PatientUpdate) — 환자 상태가 바뀌어 다시 통화하면 최신 요약이 patientInfo가 되고 이전 것은 여기 쌓인다
export interface PatientUpdate {
  callRound: number;
  receivedAt: string;
  expectedDiagnosis: string;
  severityTag: Severity;
  injuryStatus?: string[];
  ktasLevel?: number | null;
  vitals?: Vital[];
  consciousness?: string | null;
}

// 활력징후 1회 측정. 없는 값은 null.
export interface Vital {
  sequence: number;
  sbp: number | null;
  dbp: number | null;
  hr: number | null;
  rr: number | null;
  bt: number | null;
  spo2: number | null;
  glucose: number | null;
}

// 예상 병명 ↔ 병원 진료과 임베딩 유사도 매칭 결과. score를 그대로 노출해
// "왜 이 병원 순위인지" 설명 가능하게 유지한다 (hub README "설명 가능성 유지" 참고).
export interface SpecialtyMatch {
  department: string;
  score: number;
  // hub 2026-10-01~: voice의 필요 진료과와 정확 일치("exact") / 임베딩 유사도("embedding") / 진료과 없음("none")
  basis?: "exact" | "embedding" | "none";
  // 매칭된 진료과의 전문의 수(심평원). 모르면 null.
  doctorCount?: number | null;
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

// infosurv(XGBoost AFT 생존모델)가 계산한 "병상 숫자 자체가 아직 유효할 확률"
// (source: "ai" — 생성형은 아니지만 학습 모델이라 규칙과 시각적으로 구분해야 함).
// reliability(수용 신고를 믿을 만한가)와 다른 축 — 이쪽은 "가용 병상 수 값이
// 낡지 않았는가"다. hub가 매칭 시점에 재계산한 스칼라(authority·rArrive)와,
// 그 사이에도 화면이 초 단위로 감쇠를 그릴 수 있는 곡선 파라미터
// (predictedSurvivalSec·bornAt·sigma — lib/bedReliability.ts 참고)를 같이 준다.
// 순위에는 전혀 관여하지 않는 설명용이다(hub README "병상 정보 신뢰도" 절).
export interface BedReliabilityMatch {
  // 지금 이 병상 숫자를 믿어도 될 확률 (0~1, 매칭 시점 계산값)
  authority: number;
  // 도착 시점(순위에 쓴 이동 시간 horizonSec 뒤)에도 유효할 확률
  rArrive: number;
  horizonSec: number;
  // authority가 0.8 아래로 떨어질 때까지 남은 초
  ttlSec: number;
  modelTag: string;
  source: "ai";
  // 실시간 감쇠용 곡선 파라미터. 구버전 hub면 없을 수 있다 — 그땐 위 스칼라를
  // 정지값으로 그대로 표시한다.
  predictedSurvivalSec?: number | null;
  bornAt?: string | null;
  sigma?: number;
  // 병원이 "현재 정보 확인"을 누른 이력이 현재 claim에 유효하면 그 시점의
  // claim 나이(초). 있으면 확률은 조건부 생존 S(a)/S(u)이고, 로컬 감쇠도
  // 같은 식을 써야 한다(lib/bedReliability.ts). 2026-09-29 신설.
  confirmedAgeSec?: number | null;
}

// 중증질환 수용가능 신고의 질환군별 현재 상태 (hub HospitalSelfInfo가 그대로
// 전달 — 병원 자기 화면용). 정보미제공 그룹은 키가 없다.
export interface SevereGroupDeclaration {
  value: "Y" | "불가능";
  bornAt: string;
  ageIsMin: boolean;
}

export interface SevereDeclarations {
  groups: Record<string, SevereGroupDeclaration>;
  source: "rule";
}

// hub → 병원 대시보드: "귀원 정보 현황"(2026-09-29). identify 직후·info 30분
// 갱신 직후·정보 확인 직후에 그 병원 소켓으로만 온다. 데이터 공급자(병원)가
// 자기 정보의 신선도를 직접 보게 하는 피드백 루프 — bedReliability는 horizon
// 0으로 환산돼 rArrive==authority이고, 곡선 파라미터로 로컬 감쇠를 그린다.
export interface HospitalSelfInfo {
  type: "hospital_self_info";
  hospitalId: string;
  name: string;
  availableBedCount: number;
  bedCountUnknown: boolean;
  updatedAt: string;
  bedReliability?: BedReliabilityMatch | null;
  bedReliabilityByType?: Record<string, BedReliabilityMatch> | null;
  severeDeclarations?: SevereDeclarations | null;
  // hub 2026-10-04~: 본원 지정 등급(권역/지역응급의료센터 등)·수용 분야(진료과)·이송 중 부하 —
  // "지금 얼마나/어떤 분야를 받을 수 있는 병원인가"를 자기 화면에서 바로 보게.
  emergencyLevel?: string | null;
  specialties?: { department: string; doctorCount: number }[];
  inFlightCount?: number;
}

// 병원 대시보드 → hub: "현재 정보가 맞습니다" 확인 신호(2026-09-29). hub가
// 그 병원 병상 신뢰도를 조건부 생존으로 되올리고(구급차 화면 ✓), 의사결정
// 로그에 유효 확인 관측으로 남긴다.
export interface HospitalInfoConfirm {
  type: "info_confirm";
  hospitalId: string;
  timestamp: string;
}

// 매칭된 질환군의 중증질환 수용가능 신고가 언제 적 것인지 (source: "rule" —
// E-Gen 응답에 신고 시각 필드가 없어 info의 스냅샷 추적만이 아는 값).
// ruleRemainingSec은 실측된 통상 만료 규칙(신고 후 약 9시간) 기준 잔여 초 —
// 0인데 신고가 여전히 떠 있으면 병원이 갱신을 지속 중이라는 뜻이지 신고가
// 죽었다는 뜻이 아니다. ageIsMin이면 "최소 X시간 전"으로 표시해야 한다(좌측검열).
export interface SevereFreshness {
  group: string;
  value: "Y" | "불가능";
  ageSec: number;
  ageIsMin: boolean;
  ruleRemainingSec: number;
  source: "rule";
}

export interface HospitalCandidate {
  hospitalId: string;
  name: string;
  gps: { lat: number; lng: number };
  // 직선거리(존 판정·설명용). 화면엔 roadDistanceKm(카카오 내비 도로 거리, 2026-10-03)를 우선 보여준다.
  distanceKm: number;
  // 이 병원이 속한 존(hub 2026-10-04~) — 후보 리스트를 Zone 1·2·3 섹션으로 나눠 그린다.
  // 구버전 hub면 없어서 거리/5km로 추정한다.
  zone?: number;
  roadDistanceKm?: number | null;
  // 병원이 [불가] 때 고른 사유(status=rejected일 때) / 병원이 안 눌렀어도 지금 수용 불가인 이유
  // ("beds_full" = 응급실 병상 0 확인, E-Gen 기준 — E-Gen이 갱신돼 병상이 생기면 사라진다). 2026-10-03.
  rejectReason?: string | null;
  unavailableReason?: string | null;
  specialtyMatch: SpecialtyMatch;
  availableBedCount: number;
  // availableBedCount가 0일 때 그게 "확인된 만실"인지 "미상"인지 구분한다. hub가
  // feature/info의 bedsByType(병상 종류별 키 유무)으로 판정해 내보낸다 (hub README
  // "입출력 데이터 포맷" 참고). true면 화면엔 "0"이 아니라 "미상"으로 표시해야
  // 한다 — 미상을 만실처럼 보여주면 구급대원이 실제로 자리가 있을 수도 있는
  // 병원을 스스로 후보에서 빼게 되어 뺑뺑이 방지 목적과 어긋난다.
  bedCountUnknown: boolean;
  // 병상 값이 오래됐거나(1일 초과) 피드에서 빠짐 — 이 경우 0이어도 "확인된 만실"로 보지 않는다(hub 2026-09-28~).
  bedDataStale?: boolean;
  // 이 사건에서 제외된 병원(2026-10-05, 도착 후 수용 불가·이송 중 수용 철회) — 같은 사건엔 다시 승인·이송 승인 불가
  excluded?: boolean;
  // 수용 승인은 했지만 이송은 다른 병원으로 확정된 병원(hub 2026-10-22). 수용 승낙은 처치 공간 확보·기존 진료
  // 조정 같은 자원 선배정이라, 선택되지 않았음을 알려 그 준비를 풀 수 있게 해야 한다(임상 자문 요구).
  // status는 approved 그대로다 — 승인 자체는 유효하고 이동 중 재선택 대상으로 남는다.
  notSelected?: boolean;
  status: HospitalStatus;
  etaMin?: number;
  reliability?: ReliabilityInfo;
  // 병상 숫자의 유효 확률(AI)·중증신고 신선도(규칙). 둘 다 순위 무관 설명용이고,
  // 구버전 hub·구 feature/info 데이터면 필드 자체가 없다 — 칩을 숨기면 된다.
  bedReliability?: BedReliabilityMatch;
  severeFreshness?: SevereFreshness;
  // 응급실 일반 외 확장 필드(수술실 hvoc·입원실 hvgc·소아 hv28 등)의 유효
  // 확률 — 배후진료 역량(Capacity)의 신뢰도. 키는 E-Gen 필드명이고 라벨
  // 변환은 화면 쪽에서 한다(BED_FIELD_LABEL, HospitalCandidateListPanel).
  bedReliabilityByType?: Record<string, BedReliabilityMatch>;
  // hub 2026-10-01~: 응급의료기관 등급과 전문성·등급 가산(이동시간에서 뺀 분, 이유). 규칙 기반.
  emergencyLevel?: string | null;
  travelBonusMin?: number;
  bonusReasons?: string[];
  // hub 2026-09-28~인데 타입 선언이 빠져 있던 값들(2026-10-04 감사로 추가): 순위 점수(툴팁 설명용),
  // 순위에 쓴 이동 시간(분)과 그 근거(eta=카카오 내비 / estimate=직선 추정), 강등 사유(declared_no 등).
  finalScore?: number;
  travelMin?: number | null;
  travelBasis?: "eta" | "estimate";
  demoteReasons?: string[];
  // hub 2026-10-03~: 이송 중 부하(이 병원으로 확정돼 아직 TTL 안인 환자 수)와 그만큼
  // 이동시간에 더해진 분. 규칙 기반 — 대량사고처럼 확정이 한 병원에 몰릴 때만 0이
  // 아니며, 그때 이 병원이 왜 순위에서 밀렸는지(분산 장치 작동 중)를 설명한다.
  inFlightCount?: number;
  loadPenaltyMin?: number;
  loadReason?: string | null;
  // hub 2026-10-07~: 응급실 일반 정원과 포화도(%, (정원-가용)÷정원, 이송 확정 차감 반영). 규칙 기반. 병상 미상이면 포화도 null.
  erBedCapacity?: number | null;
  erOccupancyPct?: number | null;
  // 포화도 페널티 — 차감 전 E-Gen 포화도에 비례해 이동시간에 더한 분(최대 5분)과 설명 문구. 미상이면 0/null.
  occupancyPenaltyMin?: number;
  occupancyReason?: string | null;
  // hub 2026-10-07~: 병원이 E-Gen에 걸어둔 지금 유효한 수용 제한 메시지(규칙 기반). 이 환자에 해당하는
  // 것(matched)이 앞이다. 사건 질환군의 중증질환 차단이 있으면 demoteReasons에 "severe_blocked"가 붙는다.
  acceptanceMessages?: AcceptanceMessage[] | null;
}

// hub GET /hospital-backup(2026-10-08) — [배후역량] 버튼. 보유(심평원, 월 단위)·정원/운영(E-Gen)·지금 가용(E-Gen 5분,
// 이송 확정 차감 반영)을 나란히. 장비는 지금 남은 대수가 공개 정보에 없어 보유·운영만 온다. 순위와 무관한 열람용(규칙).
export interface BackupBedRow {
  key: string;
  label: string;
  hiraCapacity?: number | null;
  egenCapacity?: number | null;
  available?: number | null;
  authority?: number | null; // 지금 이 가용 숫자를 믿어도 될 확률(AI)
  note?: string | null;
}

export interface BackupEquipmentRow {
  key: string;
  label: string;
  hiraCount?: number | null;
  egenOperating?: "Y" | "N" | "N1" | null;
  note?: string | null;
}

export interface HospitalBackupView {
  hospitalId: string;
  name: string;
  emergencyLevel?: string | null;
  beds: BackupBedRow[];
  equipment: BackupEquipmentRow[];
  specialties: { department: string; doctorCount: number }[];
  nursingGrade?: string | null;
  severeDeclarations?: SevereDeclarations | null;
  acceptanceMessages: Omit<AcceptanceMessage, "matched">[];
  inFlightCount: number;
  egenUpdatedAt?: string | null;
  hiraCollectedAt?: string | null;
  source: "rule";
}

export interface AcceptanceMessage {
  kind: "er" | "severe"; // er = 응급실 메시지(진료과 단위), severe = 중증질환 차단(질환군 있음)
  message: string;
  department?: string | null;
  diseaseName?: string | null;
  diseaseGroup?: string | null;
  startAt?: string | null;
  endAt?: string | null;
  matched: boolean;
}

// 확정 병원 도착 뒤 병원이 기록한 수용 결과(hub 2026-10-01~). 수용만 남는다(수용 불가는 그 병원이 rejected로 바뀜).
export interface ArrivalResult {
  hospitalId: string;
  result: "accepted" | "refused";
  at: string;
  reason?: string | null;
}

export interface HubMatchResult {
  arrival?: ArrivalResult | null;
  // hub가 2026-09-28부터 붙이는 구분자. 그 전 hub는 이 필드 없이 보냈다.
  type?: "match_result";
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
  // 이 사건을 연 구급차의 apid(hub HubMatchResult.apid, 2026-09-24 신설). 구급차
  // 대시보드가 새로고침으로 자기 caseId를 잊었을 때 "내 구급차의 사건"을 되찾는 데 쓴다.
  // hub가 못 찾으면 null, 구버전 hub면 필드 자체가 없다.
  apid?: string | null;
  // 매칭에 쓴 구급차 좌표(hub HubMatchResult.ambulanceGps, 2026-09-24 신설). 지도가 구급차를
  // 임시 위치 대신 실제 위치에 그리는 데 쓴다. 구버전 hub면 없어서 임시 위치로 대체한다.
  ambulanceGps?: { lat: number; lng: number } | null;
  // 시연 일시정지 중(2026-10-05, hub가 실어 보냄) — 대시보드는 이 사건의 조작 버튼을 막는다
  paused?: boolean;
}

export type ApprovalActionType =
  | "hospital_approve"
  | "hospital_reject"
  | "final_approval"
  // 2026-10-01: 구급차가 확정 병원에 도착한 뒤 병원이 기록하는 실제 수용 결과
  | "arrival_accepted"
  | "arrival_refused"
  // 2026-10-05: 이송 확정 뒤 도착 전에 병원이 수용을 철회 — 그 병원은 이 사건에서 제외, 구급차는 재선택
  | "transport_withdraw";

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
  // 휴대폰 통화 화면에서 고른 첫 통화 병원(2026-10-03). hub가 그 병원 대시보드에 "통화 중"을 띄운다.
  hospitalId?: string | null;
  // 어느 기기에서 건 통화인지 — 휴대폰은 통화 전용 화면, 태블릿·PC는 전체 화면.
  device?: CallDevice;
  // 통화 취소(2026-10-05) — call_ended와 함께 true면 이 통화 음성은 처리·전달하지 않는다
  cancelled?: boolean;
}

export type CallDevice = "phone" | "tablet";

// hub → 그 구급차 탭·전화 건 병원 탭·관제 지도: 통화 상태(2026-10-03). 통화는 연출이라 실제 음성 연결은 없고,
// 구급차 쪽 음성만 hub를 거쳐 중앙 voice로 간다. 병원 대시보드엔 "📞 ○○ 구급대 통화 중"으로 뜬다.
export interface CallStatus {
  type: "call_status";
  caseId: string;
  apid: string;
  ambulanceName: string | null;
  hospitalId: string | null;
  hospitalName: string | null;
  device: CallDevice | null;
  state: "calling" | "ended";
  startedAt: string;
  endedAt: string | null;
  // 2026-10-05: 같은 사건의 추가 통화인지(환자 상태 변화) · 취소된 통화인지(전달 안 됨)
  followup?: boolean;
  cancelled?: boolean;
}

// hub → 시연 콘솔: 대량사고 [분배 확정] 결과(2026-10-05). reason: confirmed | no_approved_hospital | paused | already_confirmed | no_result
export interface MciAllocationResult {
  caseId: string;
  hospitalId: string | null;
  hospitalName?: string | null;
  loadPenaltyMin?: number | null;
  reason: string;
}
export interface MciAllocated {
  type: "mci_allocated";
  results: MciAllocationResult[];
}
// hub → 시연 콘솔: 대량사고 자동 분배 미리 보기(2026-10-05) — 지금 승인 상태로 [분배 확정]하면 누가 어디로 가는지.
// hub가 확정 때도 같은 계획을 쓴다(중증부터, 승인 병원 중 finalScore 최고, 앞 배정마다 부하 페널티). hospitalId null = 승인 병원 없음
export interface MciPlanItem {
  caseId: string;
  hospitalId: string | null;
  hospitalName?: string | null;
  severityTag?: string | null;
  loadPenaltyMin?: number | null;
}
export interface MciPlan {
  type: "mci_plan";
  caseIds: string[];
  plan: MciPlanItem[];
}

// hub → 조작한 탭: 조작이 거부됨(2026-10-05). reason "paused" = 시연 일시정지 중
export interface ActionRefused {
  type: "action_refused";
  caseId: string | null;
  reason: string;
}

// 미선택 통보(hub 2026-10-22) — 이송이 다른 병원으로 확정된 순간, 승인은 했지만 선택되지 않은 병원에 온다.
// 매칭 결과의 `notSelected` 깃발과 같은 사실을 푸시로 한 번 더 받는 것이라, 카드 목록을 다시 훑지 않고
// 바로 안내를 띄울 수 있다. 승인이 풀린 건 아니다(status는 approved 그대로 — 이동 중 재선택 대상으로 남는다).
export interface SelectionReleased {
  type: "selection_released";
  caseId: string;
  hospitalId: string;
  confirmedHospitalId: string;
  confirmedHospitalName: string;
  timestamp: string;
}

export type DashboardRole = "ambulance" | "hospital";
// hub 소켓 접속 역할. monitor(2026-10-03)는 관제 지도 — 승인 같은 행위는 하지 않고 보기만 한다.
export type SocketRole = DashboardRole | "monitor";

// dashboard → feature/hub. 소켓 연결 직후 보내는 자기소개. hub는 그동안 연결을
// 완전히 익명으로 취급해서, 새 탭이 이미 진행 중인 사건이 있는 상태로 뒤늦게
// 열리면 그 사건의 이전 브로드캐스트를 놓쳐 화면에 아무것도 안 뜨는 문제가
// 있었다(2026-08-11 실제 재현됨). 이걸로 자기가 병원인지 구급차인지, 어느
// hpid/apid인지 알려주면 hub가 관련된 사건들을 연결 시점에 바로 되돌려준다.
export interface DashboardIdentify {
  type: "identify";
  role: SocketRole;
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
  role: SocketRole;
  id: string;
  name: string | null;
  known: boolean;
  // hub 2026-10-01~: 출동 시뮬레이션이 켜져 있는지. 구급차 화면의 [이동]·[현장 종료] 버튼 표시 여부.
  simDispatch?: boolean;
  // hub 2026-10-03~: 구급차 대시보드에서도 통화를 시작할 수 있는지(start-all.sh --dashboard-call). 기본 false —
  // 통화는 휴대폰 전화 앱으로만 하고 대시보드엔 통화 현황만. 이 필드가 없는 구버전 hub면 예전처럼 버튼을 둔다.
  dashboardCall?: boolean;
  // hub 2026-10-04~: 자기 위치(병원=E-Gen 좌표, 구급차=기지) — 사건이 없어도 본원 지도를 그린다.
  gps?: { lat: number; lng: number } | null;
}

// 신원 확인 결과. known=null은 "아직 hub 응답을 못 받음(확인 중)" —
// 접근 불가로 단정하면 안 되고, false와는 구분해서 다뤄야 한다.
export interface IdentityState {
  name: string | null;
  known: boolean | null;
  simDispatch?: boolean;
  dashboardCall?: boolean;
  gps?: { lat: number; lng: number } | null;
}

export interface DashboardState {
  // caseId를 키로 하는 맵 — 여러 구급차의 사건을 동시에 들고 있을 수 있다.
  // 구급차 대시보드는 자기 caseId 하나만 꺼내 쓰고, 병원 대시보드는 자기
  // hospitalId가 후보로 들어있는 사건을 전부 걸러 카드로 나열한다.
  matchResults: Record<string, HubMatchResult>;
  // caseId -> 매칭 전 현장 후보(구급차 탭만 받는다).
  sceneCandidates: Record<string, SceneCandidates>;
  // apid -> 출동 시뮬레이션 상태. 위치 메시지엔 경로가 없어서 직전 경로를 이어 쓴다.
  ambulanceSim: Record<string, AmbulanceSimState>;
  // hub 메시지 자체엔 타임스탬프가 없어서, "정보 수신 후 경과" 표시를 위해
  // 대시보드가 최초 수신 시각을 로컬에서 기록해 둔다.
  receivedAt: string | null;
  // 이 소켓(=이 apid/hpid)의 신원 확인 결과. matchResults와 분리해서 관리하는
  // 이유는 사건과 무관하게 항상 표시돼야 하기 때문이다.
  identity: IdentityState;
  // 병원 대시보드 전용 — hub가 보내주는 "귀원 정보 현황". 구급차 화면·mock
  // 모드·구버전 hub에서는 null로 남는다.
  selfInfo: HospitalSelfInfo | null;
  // 관제 지도 전용(2026-10-03) — 전체 병원·구급차 목록과 사건 요약(caseId -> 요약).
  mapOverview: MapOverview | null;
  monitorCases: Record<string, MonitorCase>;
  // caseId -> 통화 중 voice가 인식한 발화(2026-10-03, 구급차 탭만 받는다). 통화 시연 패널의 실시간 자막.
  callTranscripts: Record<string, CallTranscriptLine[]>;
  // caseId -> 통화 상태(2026-10-03). 휴대폰으로 건 통화를 태블릿·병원·관제 화면이 알 수 있게.
  callStatus: Record<string, CallStatus>;
  // 관제 지도의 "병원 응답" 기록(2026-10-03) — 사건 요약이 바뀔 때 병원 상태가 달라진 것을 쌓는다(최근 것이 앞).
  monitorEvents: MonitorEvent[];
  // caseId -> 이송 중 활력징후 판정 이력(2026-10-04, 시간순). 구급차 탭은 전부 받고,
  // 병원 탭은 자기 확정 사건의 notify 이상만 받는다(hub가 역할별로 거른다).
  transportAssessments: Record<string, TransportAssessment[]>;
  // caseId -> 예비 고지(2026-10-04). 실제 요청이 오면(matchResults에 그 사건이 생기면) 지운다.
  preAlerts: Record<string, PreAlert>;
  // 관제 지도 전용(2026-10-04): 매칭 전 사건의 번호·시작 시각·증상, 오늘 종료된 사건 목록
  caseMeta: Record<string, CaseMeta>;
  caseHistory: CaseHistoryItem[];
  // 마지막으로 hub가 거부한 조작(2026-10-05) — 화면이 "현재 시연 일시정지 중입니다." 같은 안내를 잠깐 띄운다
  actionRefused: { at: number; reason: string; caseId: string | null } | null;
  // 미선택 통보(2026-10-22) — 병원 화면이 안내를 띄우는 데 쓴다. at은 받은 시각(같은 사건이 또 와도 다시 띄우게).
  selectionReleased: { at: number; caseId: string; confirmedHospitalName: string } | null;
  // 마지막 대량사고 분배 확정 결과(시연 콘솔)
  mciAllocated: { at: number; results: MciAllocationResult[] } | null;
  // 마지막 대량사고 자동 분배 미리 보기(시연 콘솔 ③)
  mciPlan: { at: number; caseIds: string[]; plan: MciPlanItem[] } | null;
  // caseId -> 시연 콘솔 ② 현장 확인 방식(2026-10-06, 구급차 탭만 받는다). "template"이면 휴대폰 앱은 현장 통화를 못 한다
  sceneInputMode: Record<string, SceneInputMode>;
}

export type SceneInputMode = "voice" | "template";

export interface SceneInputModeMessage {
  type: "scene_input_mode";
  caseId: string;
  apid: string | null;
  mode: SceneInputMode;
  // 어느 단계의 방식인지(2026-10-06) — scene: ② 현장 확인, transport: ④ 이송 중(휴대폰 앱 [목적지 병원과 통화]). 없으면 scene
  stage?: "scene" | "transport";
}

// 시연 영상 모드(2026-10-06) — hub가 연결된 모든 화면에 같은 값을 알린다. video면 화면마다 정해진 영상을 덮어 띄운다
// (components/ui/DemoVideoOverlay가 자기 연결로 받는다)
export type DemoMode = "live" | "video";

export interface DemoModeMessage {
  type: "demo_mode";
  mode: DemoMode;
}

// ── 이송 중 활력징후 모니터링 (2.5단계, 2026-10-04) ─────────────────────────
// 입력 구멍: 출처(음성·수기·모니터·데모)가 무엇이든 같은 형식으로 hub에 보낸다.
// 판정은 hub의 규칙 엔진(NEWS2 + 규칙표, hub/transport_triage.py — source: "rule").

export type VitalSource = "voice" | "manual" | "monitor" | "demo";

export interface VitalObservationIn {
  measuredAt: string;
  source: VitalSource;
  rr?: number | null;
  spo2?: number | null;
  sbp?: number | null;
  dbp?: number | null;
  hr?: number | null;
  bt?: number | null;
  avpu?: "A" | "V" | "P" | "U" | null;
}

// dashboard → hub (WS). 데모 시나리오·수기 입력이 쓴다. demo=true면 hub 로그에도 가상 표시가 남는다.
export interface TransportVitalsMessage {
  type: "transport_vitals";
  caseId: string;
  apid?: string;
  demo?: boolean;
  scenario?: string | null;
  observation: VitalObservationIn;
}

// record=기록만 · hold=초과 1회째(오경보 필터) · notify=확정 병원에 전달 ·
// review=대체 병원 제안(결정은 사람) · heli_advisory=헬기 대기 권고(결정은 관제)
export type TransportTier = "record" | "hold" | "notify" | "review" | "heli_advisory";

export interface TransportAlternative {
  hospitalId: string;
  name: string;
  status: string;
  travelMin?: number | null;
  availableBedCount: number;
  bedCountUnknown: boolean;
  rArrive?: number | null;
}

export interface TransportAssessment {
  type: "transport_assessment";
  caseId: string;
  tier: TransportTier;
  news2: number;
  news2Missing: string[];
  si?: number | null;
  reasons: string[];
  observation: VitalObservationIn;
  demo: boolean;
  scenario?: string | null;
  alternatives: TransportAlternative[];
  source: "rule";
  timestamp: string;
}

// hub → dashboard: 연결(재연결) 직후 따라잡기 끝에 오는 "지금 진행 중인 사건 목록"(2026-10-03). 탭은 hub가
// 꺼졌다 켜져도 자동 재연결하며 화면 상태를 들고 있어서, 그 사이 끝난 사건이 계속 남았다 — 목록에 없는 사건은 지운다.
export interface CaseSync {
  type: "case_sync";
  caseIds: string[];
}

// hub → 구급차 탭: 통화 중 voice(Qwen3-ASR)가 발화 하나를 인식할 때마다(2026-10-03). AI 처리 결과.
export interface CallTranscriptLine {
  type: "call_transcript";
  apid: string;
  caseId: string | null;
  start: number;
  end: number;
  text: string;
  source: "ai";
}

export interface MonitorEvent {
  at: string;
  caseId: string;
  ambulanceName: string;
  hospitalId: string;
  hospitalName: string;
  status: HospitalStatus;
}

// ── hub → 관제 지도(role=monitor, 2026-10-03) ───────────────────────────────
// 병원 대시보드는 직접 접속하지 않고, 관제 지도에서 환자 요청이 온 병원을 눌러 연다.

export interface MapHospital {
  hospitalId: string;
  name: string;
  gps: { lat: number; lng: number };
  emergencyLevel?: string | null;
  // 이송 중 부하(TTL 오버레이 건수, hub 2026-10-03~) — 관제 지도에서 환자가 몰리는
  // 병원을 표시해 분산 장치가 작동 중임을 보여준다. 구버전 hub면 필드 자체가 없다.
  inFlightCount?: number;
  // 응급실 가용 병상(오버레이 차감 후)·미상 여부(hub 2026-10-04~). 관제는 모든 병원의
  // 상태를 봐야 하므로 만실(0 확인)은 마커·라벨에서 구분한다. 미상 ≠ 만실 원칙 그대로.
  availableBedCount?: number;
  bedCountUnknown?: boolean;
}

export interface MapAmbulance {
  apid: string;
  name: string;
  // 출동 시뮬레이션 위치가 있으면 그것, 없으면 기지 좌표. 움직이는 동안은 ambulanceSim이 더 새 값이다.
  gps: { lat: number; lng: number };
  base: { lat: number; lng: number };
}

export interface MapOverview {
  type: "map_overview";
  hospitals: MapHospital[];
  ambulances: MapAmbulance[];
  simDispatch: boolean;
  source: "rule";
}

export interface MonitorCaseHospital {
  hospitalId: string;
  name: string;
  status: HospitalStatus;
  distanceKm: number;
  roadDistanceKm?: number | null;
  // 병원이 고른 거절 사유 / 병원이 안 눌렀어도 지금 수용 불가인 이유("beds_full" — 이때 status는 rejected로 온다)
  rejectReason?: string | null;
  unavailableReason?: string | null;
  // 이 병원이 든 존(1부터, zoneBandKm 간격). 거절 비율로 존이 넓혀지면 바깥 존 병원이 새로 들어온다.
  zone: number;
  // 이 병원이 이 사건에 응답(승인·불가·확정)한 시각(2026-10-04, hub case_history)
  respondedAt?: string | null;
}

// 사건 진행 과정 한 줄(2026-10-04, hub case_history — 규칙 기반 기록). kind: p 출동·통화 / s 요청 시작 /
// r 수용 불가 / x 범위 확장 / a 수용 승인 / t 이송 확정 / c 취소·해제 / d 이송 완료
export interface CaseEvent {
  t: string;
  kind: "p" | "s" | "r" | "x" | "a" | "t" | "c" | "d" | string;
  text: string;
}

// hub → 관제: 매칭 전 사건의 번호·시작 시각·증상(2026-10-04). 매칭되면 case_overview가 이어받는다.
export interface CaseMeta {
  type: "case_meta";
  caseId: string;
  num: number;
  startedAt: string;
  symptom?: string | null;
  severity?: Severity | string | null;
  apid?: string | null;
  ambulanceName?: string | null;
  events?: CaseEvent[];
}

// 오늘 종료된 사건 하나(관제 '지난 사건')
export interface CaseHistoryItem {
  caseId: string;
  num: number;
  startedAt: string;
  endedAt: string;
  symptom?: string | null;
  severity?: Severity | string | null;
  apid?: string | null;
  ambulanceName?: string | null;
  requested: number;
  rejected: number;
  zone: number;
  hospital?: string | null;
  result: "done" | "cancel";
  reason: string;
  events: CaseEvent[];
}

export interface CaseHistory {
  type: "case_history";
  cases: CaseHistoryItem[];
}

// 사건 요약 — 통화 전문·활력징후 등 환자 상세는 없다(그건 요청을 받은 병원 대시보드만 본다).
export interface MonitorCase {
  type: "case_overview";
  caseId: string;
  apid: string | null;
  ambulanceName: string | null;
  ambulanceGps: { lat: number; lng: number } | null;
  severityTag: Severity | null;
  zoneActive: number[];
  zoneBandKm: number;
  hospitals: MonitorCaseHospital[];
  // 관제 지도 개편(2026-10-04): 오늘의 사건 번호·시작 시각·증상 한 줄·진행 과정(구버전 hub면 없음)
  num?: number | null;
  startedAt?: string | null;
  symptom?: string | null;
  events?: CaseEvent[];
  // 시간 기반 존 확장(2026-10-04): 다음 자동 확장 예정 시각. 승인·확정 병원이 있거나 더 넓힐 수 없으면 null
  zoneExpandAt?: string | null;
  // [정지] 중이면 멈춰 있는 남은 시간(초) — 이때 zoneExpandAt은 null(시간이 흐르지 않는다)
  zonePausedLeftSec?: number | null;
  // 시연 일시정지 중(2026-10-05) — 콘솔이 조작 버튼을 막는다
  paused?: boolean | null;
  source: "rule";
}

// hub → 병원·관제: 예비 고지(2026-10-04, 출동 시뮬레이션 모드) — 구급대가 출동한 순간,
// 현장 존 안 후보 병원에 "인근 사고 발생 — 수용 요청이 올 수 있음"을 먼저 알린다(v2 계획
// '예비 고지'의 경량판). 병원엔 자기까지의 거리(distanceKm)만, 관제·콘솔엔 발송 병원 수
// (hospitalCount)만 온다 — 현장 좌표는 보내지 않는다. 실제 요청(match_result)이 오거나
// 사건이 닫히면 지운다.
export interface PreAlert {
  type: "pre_alert";
  caseId: string;
  apid: string;
  ambulanceName?: string | null;
  distanceKm?: number | null;
  hospitalCount?: number | null;
  // 신고 접수 때 파악한 1차 증상(2026-10-04) — '신고 내용'일 뿐 확정 정보가 아니다
  reportedSymptom?: string | null;
  reportedSeverity?: Severity | null;
  source: "rule";
  timestamp: string;
}

// hub → dashboard: 확정 없이 끝난 사건(방치 정리·현장 종료, 2026-10-01). 받으면 그 사건을
// 화면에서 지운다 — 예전엔 취소·중단된 사건 카드가 병원 대시보드에 계속 남았다.
export interface CaseClosed {
  type: "case_closed";
  caseId: string;
  reason: "unresolved_timeout" | "scene_ended" | string;
}

// hub → 구급차 탭만: 환자 정보가 오기 전 구급차 위치 기준 거리순 후보(규칙 기반, 2026-10-01).
// 통화 시작 때(출동 시뮬레이션이면 현장 도착 때) 온다. 매칭 결과가 오면 그것으로 대체한다.
export interface SceneCandidate {
  hospitalId: string;
  name: string;
  distanceKm: number;
  // 카카오 내비 기준(2026-10-03). 현장 후보는 도착 시간순으로 온다. 못 받은 병원은 null(직선 추정).
  roadDistanceKm?: number | null;
  etaMin?: number | null;
  gps: { lat: number; lng: number };
  availableBedCount: number;
  bedCountUnknown: boolean;
  // 병상 신뢰도(AI) — 매칭 결과의 bedReliability와 같은 형태(2026-10-03). 신뢰도
  // 모델 미연동 병원·구버전 hub면 없다(그 병원 칩만 안 그리면 된다, Optional 패턴).
  bedReliability?: BedReliabilityMatch | null;
  // 첫 연락 추천(2026-10-03): 빈 병상이 확인되고 도착 시점 유효 확률(rArrive)이 가장
  // 높은 한 곳에만 true. 순위(거리순)는 바꾸지 않는다 — 첫 통화 상대 제안일 뿐,
  // 틀려도 통화 뒤 존 전체 동시 전달이 뒤를 받친다.
  firstCallRecommended?: boolean;
  // hub 2026-10-04~: 구급대가 전화 상대를 고를 때 바로 보는 정보 — 등급·진료과(전문의 수)
  emergencyLevel?: string | null;
  specialties?: { department: string; doctorCount: number }[];
}

export interface SceneCandidates {
  type: "scene_candidates";
  caseId: string;
  apid: string;
  ambulanceGps: { lat: number; lng: number };
  ambulanceGpsFallback: boolean;
  zoneActive: number[];
  hospitals: SceneCandidate[];
  // hub 2026-10-04~: 신고 접수 1차 증상 — 전화 앱 머리에 "신고: 흉통(중증)" 표시용.
  // 있으면 순위에도 중증도 가산(권역/지역센터 분)이 반영돼 있다.
  reportedSymptom?: string | null;
  reportedSeverity?: Severity | null;
  source: "rule";
}

// hub → dashboard: 구급차 출동 시뮬레이션(시연용 가짜 위치, 2026-10-01). ambulance_phase는 상태가
// 바뀔 때(경로 포함), ambulance_position은 움직이는 동안 1초마다(경로 없음) 온다. 구급차 탭은 전부,
// 병원 탭은 자기가 확정 병원일 때 이송 중에만 받는다. 항상 simulated=true.
export type AmbulancePhase =
  | "idle"
  | "dispatching"
  | "on_scene"
  | "transporting"
  | "at_hospital"
  | "rerouting"
  | "returning";

export interface AmbulanceSimState {
  type: "ambulance_phase" | "ambulance_position";
  apid: string;
  caseId: string | null;
  phase: AmbulancePhase;
  gps: { lat: number; lng: number } | null;
  heading: number;
  etaSec: number | null;
  // 이 구간의 배속(2026-10-01). 화면 이동 시간이 5초 고정(2026-10-03)이라 먼 곳일수록 hub가 배속을 올린다.
  speedup?: number | null;
  path?: [number, number][] | null;
  base: { lat: number; lng: number };
  incident: { lat: number; lng: number } | null;
  hospitalId: string | null;
  // [정지] 중(2026-10-03). 위치·남은 시간이 그대로 멈춰 있다. 구버전 hub면 없음.
  paused?: boolean;
  // 왜 멈췄나(2026-10-05): "manual" 시연 일시정지(조작 잠금) | "call" 이송 중 추가 통화 동안만 이동 멈춤(잠금 없음)
  pauseReason?: "manual" | "call" | string | null;
  simulated: true;
}

// dashboard → hub: [이동] · [현장 종료] · [정지] · [상황 재개](2026-10-03)
export interface DispatchCommand {
  // sim_reset(2026-10-04): [시연 초기화] — 모든 사건 종료 + 전 구급차 기지 복귀(apid는 "*")
  // sim_fast_forward(2026-10-04): [빨리감기] — 병원으로 이송 중이면 남은 이동을 3초 안에 마친다
  type: "dispatch" | "scene_end" | "sim_pause" | "sim_resume" | "sim_reset" | "sim_fast_forward";
  apid: string;
  caseId: string;
  timestamp: string;
  // 주소 검색·지도 클릭으로 고른 출동 위치(2026-10-01). 없으면 기지 근처 무작위. 주소 글자는 보내지 않는다.
  target?: { lat: number; lng: number };
  targetMode?: "address" | "map";
  // 신고 접수 때 파악한 1차 증상(2026-10-04) — 상황실이 신고 전화에서 들은 수준의 개요.
  // hub가 예비 고지에 실어 병원이 "무슨 환자가 올 수 있는지"까지 미리 안다. 현장 평가와
  // 다를 수 있어 어디서나 '신고 내용'으로만 표기한다.
  reportedSymptom?: string;
  reportedSeverity?: Severity;
}

// 출동 위치 선택(구급차 화면 상태). label은 화면 표시용으로만 이 탭에 남는다.
export interface DispatchTarget {
  lat: number;
  lng: number;
  label: string;
  mode: "address" | "map";
  etaMin?: number | null;
}

// hub GET /geocode 결과 1건
export interface GeocodeResult {
  name: string;
  address: string;
  lat: number;
  lng: number;
  etaMin?: number;
  etaBasis?: "eta" | "estimate";
}

export type InboundMessage =
  | HubMatchResult
  | DashboardIdentityInfo
  | HospitalSelfInfo
  | CaseClosed
  | SceneCandidates
  | AmbulanceSimState
  | MapOverview
  | MonitorCase
  | CallTranscriptLine
  | CallStatus
  | CaseSync
  | TransportAssessment
  | PreAlert
  | CaseMeta
  | CaseHistory
  | ActionRefused
  | SelectionReleased
  | MciAllocated
  | MciPlan
  | SceneInputModeMessage;
