// CLAUDE.md > "데이터 포맷 및 흐름"에 정의된 스키마와 1:1로 대응한다.
// 필드를 추가/변경할 때는 CLAUDE.md도 함께 갱신할 것.

export type Severity = "high" | "medium" | "low";

// 발화 턴 단위 원본 로그. CLAUDE.md는 transcript.raw_text를 전문 string으로만
// 정의하지만, "필터링된 문장도 원본 로그에는 남겨두고 요약 제외 표시만 한다"는
// 원칙을 화면에 실제로 보여주려면 턴 단위 구조가 필요하다.
// voice 담당자와 정식 스키마 반영 여부를 협의하기 전까지는 optional 확장 필드로 둔다.
export interface TranscriptTurn {
  speaker: string;
  timestamp: string;
  text: string;
  excludedFromSummary?: boolean;
}

export interface CallSummaryMessage {
  transcript: {
    raw_text: string;
    filtered_text: string;
    language: string;
    timestamp: string;
    duration_sec: number;
    turns?: TranscriptTurn[];
  };
  summary: {
    patient: string;
    mechanism: string;
    symptoms: string[];
    treatment: string[];
    severity_tag: Severity;
    // 병원 대시보드 시안 반영용 확장 필드 (아직 CLAUDE.md 미정 스키마)
    required_department?: string;
  };
  source: "ai";
  model_used: {
    stt: string;
    llm: string;
  };
}

export interface VitalsMessage {
  vitals: {
    bp_systolic: number;
    bp_diastolic: number;
    pulse: number;
    spo2: number;
    gcs: number;
    temperature: number;
    resp_rate: number;
  };
  timestamp: string;
  source: "rule";
  // 추세 판단은 이력 데이터가 필요해 현재 규칙 엔진 스펙에 없다. 백엔드가
  // 계산해 내려줄 때만 표시하고, 프론트에서 추세를 추정하지 않는다.
  trend_note?: string;
}

// CLAUDE.md가 언급하는 hv1(전문의)/hvec(병상)/hv2(중증질환) API 대조 결과의
// JSON 스키마는 아직 확정되지 않았다. vital 담당자와 협의 후 정식 반영할 것.
export interface HospitalCapacitySnapshot {
  specialist_on_call: boolean;
  beds_available: number;
  or_available: boolean;
  or_available_in_min?: number;
}

export type HospitalStatus = "pending" | "approved" | "rejected" | "confirmed";

export interface HospitalCandidate {
  hospital_id: string;
  name: string;
  distance_km: number;
  status: HospitalStatus;
  eta_min?: number;
}

export interface HospitalMatchMessage {
  zone_active: number[];
  hospitals: HospitalCandidate[];
  source: "rule";
}

export type ApprovalActionType =
  | "hospital_approve"
  | "hospital_reject"
  | "final_approval";

export type Actor = "hospital" | "paramedic";

export interface ApprovalAction {
  action: ApprovalActionType;
  hospital_id: string;
  actor: Actor;
  timestamp: string;
}

export type DashboardRole = "ambulance" | "hospital";

export interface DashboardState {
  callSummary: CallSummaryMessage | null;
  vitals: VitalsMessage | null;
  hospitalMatch: HospitalMatchMessage | null;
  hospitalCapacity: HospitalCapacitySnapshot | null;
}

export type InboundMessage =
  | CallSummaryMessage
  | VitalsMessage
  | HospitalMatchMessage
  | HospitalCapacitySnapshot;
