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
}

// 예상 병명 ↔ 병원 진료과 임베딩 유사도 매칭 결과. score를 그대로 노출해
// "왜 이 병원 순위인지" 설명 가능하게 유지한다 (hub README "설명 가능성 유지" 참고).
export interface SpecialtyMatch {
  department: string;
  score: number;
}

export type HospitalStatus = "pending" | "approved" | "rejected" | "confirmed";

export interface HospitalCandidate {
  hospitalId: string;
  name: string;
  gps: { lat: number; lng: number };
  distanceKm: number;
  specialtyMatch: SpecialtyMatch;
  availableBedCount: number;
  status: HospitalStatus;
  etaMin?: number;
}

export interface HubMatchResult {
  patientInfo: PatientInfo;
  zoneActive: number[];
  hospitals: HospitalCandidate[];
  source: "rule";
}

export type ApprovalActionType =
  | "hospital_approve"
  | "hospital_reject"
  | "final_approval";

export type Actor = "hospital" | "paramedic";

// dashboard → feature/hub. 이 스키마만 CLAUDE.md/hub README 모두 snake_case로 확정돼 있다.
export interface ApprovalAction {
  action: ApprovalActionType;
  hospital_id: string;
  actor: Actor;
  timestamp: string;
}

// 통화 시연 컴포넌트(구급차 대시보드)가 hub에 보내는 통화 시작/종료 신호.
// hub README에는 아직 없는 가안 스키마다 — 실제 음성 캡처는 원래 feature/voice
// 담당 영역(Whisper STT)이라, 이 라이브 데모가 hub로 직접 오디오를 보내는 방식으로
// 확정할지는 voice/hub 팀과 별도 협의가 필요하다.
export type CallSignalType = "call_started" | "call_ended";

export interface CallSignal {
  type: "call_signal";
  signal: CallSignalType;
  timestamp: string;
}

export type DashboardRole = "ambulance" | "hospital";

export interface DashboardState {
  matchResult: HubMatchResult | null;
  // hub 메시지 자체엔 타임스탬프가 없어서, "정보 수신 후 경과" 표시를 위해
  // 대시보드가 최초 수신 시각을 로컬에서 기록해 둔다.
  receivedAt: string | null;
}

export type InboundMessage = HubMatchResult;
