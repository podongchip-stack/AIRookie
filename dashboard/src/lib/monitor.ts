import { rejectionReasonLabel, unavailableReasonLabel } from "@/lib/rejection";
import type { AmbulancePhase, HospitalStatus, MonitorCase, Severity } from "@/types/dashboard";

// 관제 지도(2026-10-03) 공용 계산. 지도 마커와 왼쪽 사건 목록이 같은 규칙을 쓰도록 한 곳에 둔다.

// 병원 응답 상태 색(2026-10-03): 판단 대기 노랑 · 수용 승인 연두 · 수용 불가 빨강 · 이송 확정 초록.
// 요청 존 범위는 노랑과 헷갈리지 않게 보라색.
export const MAP_COLORS = {
  hospital: "#1E5FA8",
  ambulance: "#E8590C",
  request: "#F5C518",
  approved: "#8BC34A",
  confirmed: "#0E9F6E",
  rejected: "#D93F35",
  zone: "#7048E8",
  incident: "#D93F35",
} as const;

export const PHASE_SHORT: Record<AmbulancePhase, string> = {
  idle: "기지 대기",
  dispatching: "현장 출동 중",
  on_scene: "현장 도착",
  transporting: "병원 이송 중",
  at_hospital: "병원 도착",
  rerouting: "재선택 대기",
  returning: "기지 복귀 중",
};

export const STATUS_SHORT: Record<HospitalStatus, string> = {
  pending: "판단 대기",
  approved: "수용 승인",
  rejected: "수용 불가",
  confirmed: "이송 확정",
};

export const SEVERITY_SHORT: Record<Severity, string> = { high: "중증", medium: "중등증", low: "경증" };

export interface HospitalRequest {
  caseId: string;
  ambulanceName: string;
  status: HospitalStatus;
  // "병상 없음(E-Gen)" 또는 병원이 고른 거절 사유 — 수용 불가일 때 어떤 불가인지
  note: string | null;
  severity: Severity | null;
  zone: number;
}

// 병원별로 "지금 받은 환자 요청" 목록. 병원 대시보드의 카드 목록과 같은 규칙이다 — 그 사건이 다른 병원으로
// 이미 이송 확정됐으면 이 병원엔 더 이상 의미가 없어 뺀다(본원이 확정 병원이면 남긴다). 여기 들어 있는 병원만
// 지도에서 눌러 병원 대시보드를 열 수 있다.
export function hospitalRequests(cases: Record<string, MonitorCase>): Map<string, HospitalRequest[]> {
  const byHospital = new Map<string, HospitalRequest[]>();
  for (const monitorCase of Object.values(cases)) {
    const confirmedId = monitorCase.hospitals.find((h) => h.status === "confirmed")?.hospitalId ?? null;
    for (const hospital of monitorCase.hospitals) {
      if (confirmedId && confirmedId !== hospital.hospitalId) continue;
      const list = byHospital.get(hospital.hospitalId) ?? [];
      list.push({
        caseId: monitorCase.caseId,
        ambulanceName: monitorCase.ambulanceName ?? monitorCase.apid ?? "구급차",
        status: hospital.status,
        note: unavailableReasonLabel(hospital.unavailableReason) ?? rejectionReasonLabel(hospital.rejectReason),
        severity: monitorCase.severityTag,
        zone: hospital.zone,
      });
      byHospital.set(hospital.hospitalId, list);
    }
  }
  return byHospital;
}

// 요청 표시·마커 색은 그 병원에서 가장 진행된 상태를 따른다: 이송 확정(초록) > 수용 승인(연두) > 판단 대기
// (노랑) > 전부 수용 불가(빨강).
const STATUS_RANK: Record<HospitalStatus, number> = { confirmed: 3, approved: 2, pending: 1, rejected: 0 };
const STATUS_COLOR: Record<HospitalStatus, string> = {
  confirmed: MAP_COLORS.confirmed,
  approved: MAP_COLORS.approved,
  pending: MAP_COLORS.request,
  rejected: MAP_COLORS.rejected,
};

export function topStatus(requests: HospitalRequest[]): HospitalStatus {
  return requests.reduce<HospitalStatus>(
    (best, r) => (STATUS_RANK[r.status] > STATUS_RANK[best] ? r.status : best),
    "rejected",
  );
}

export function requestColor(requests: HospitalRequest[]): string {
  return STATUS_COLOR[topStatus(requests)];
}

// 흰 바탕 위 글자색 — 노랑·연두는 그대로 쓰면 안 읽혀서 같은 계열의 진한 색을 쓴다.
const STATUS_TEXT_COLOR: Record<HospitalStatus, string> = {
  pending: "#A16207",
  approved: "#4D7C0F",
  rejected: MAP_COLORS.rejected,
  confirmed: MAP_COLORS.confirmed,
};

export function statusColor(status: HospitalStatus): string {
  return STATUS_TEXT_COLOR[status];
}

// 색 칩 위 글자색 — 노랑·연두 배경엔 어두운 글자, 빨강·초록엔 흰 글자.
export function statusInk(status: HospitalStatus): string {
  return status === "pending" || status === "approved" ? "#1F2933" : "#FFFFFF";
}

// 상태 기호 — 색만으로 구분하지 않게(색약·흑백 화면) 글자 앞에 붙인다.
export const STATUS_ICON: Record<HospitalStatus, string> = {
  pending: "🚨",
  approved: "✓",
  rejected: "✕",
  confirmed: "🚑",
};
