// CLAUDE.md > "데이터 포맷 및 흐름"에 정의된 스키마와 1:1로 대응한다.
// 필드를 추가/변경할 때는 CLAUDE.md도 함께 갱신할 것.

export type Severity = "high" | "medium" | "low";

export interface CallSummaryMessage {
  transcript: {
    raw_text: string;
    filtered_text: string;
    language: string;
    timestamp: string;
    duration_sec: number;
  };
  summary: {
    patient: string;
    mechanism: string;
    symptoms: string[];
    treatment: string[];
    severity_tag: Severity;
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
}

export type InboundMessage =
  | CallSummaryMessage
  | VitalsMessage
  | HospitalMatchMessage;
