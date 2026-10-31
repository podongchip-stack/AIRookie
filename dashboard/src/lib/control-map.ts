import type { CSSProperties } from "react";
import { rejectionReasonLabel, unavailableReasonLabel } from "@/lib/rejection";
import type {
  AmbulancePhase,
  AmbulanceSimState,
  CaseEvent,
  CaseMeta,
  HospitalStatus,
  MapOverview,
  MonitorCase,
  PreAlert,
  Severity,
} from "@/types/dashboard";

// 관제 지도 개편(2026-10-04, 디자인 시안 "골든링크 관제") — hub 메시지(사건 요약·매칭 전 사건 정보·구급차 위치)를
// 화면이 그대로 그릴 수 있는 형태로 바꾼다. 계산만 하고 화면은 그리지 않는다(app/map/page.tsx, ControlMapPanel).
// 전부 규칙 기반 — 거리·존·상태 집계일 뿐 판단은 하지 않는다.

// ── 시안 색 ──────────────────────────────────────────────────────────────────
export const C = {
  navy: "#14213D",
  ink: "#1B2430",
  ink2: "#2A3441",
  ink3: "#4A5565",
  sub: "#5A6676",
  muted: "#7A8594",
  faint: "#9AA3B0",
  bg: "#F1F3F6",
  line: "#DDE2E8",
  line2: "#E6E9EE",
  blue: "#1F6FE5",
  orange: "#F26B1D",
  zone: "#7B4DFF",
} as const;

// 병원 응답 상태 — 짧은 키(시안과 같은 w/r/a/t)
export type St = "w" | "r" | "a" | "t";
export const ST_OF: Record<HospitalStatus, St> = { pending: "w", rejected: "r", approved: "a", confirmed: "t" };
export const ST_LABEL: Record<St, string> = { w: "판단 대기", r: "수용 불가", a: "수용 승인", t: "이송 확정" };
// 요청 병원 한 곳의 상태 문구 — "병상 없음"(E-Gen)·"선택 안 됨"(승인했지만 다른 병원으로 확정)을 상태와 구분해 보인다
export const reqLabel = (h: Pick<IncHospital, "st" | "bedsFull" | "notSelected">) =>
  h.st === "r" && h.bedsFull ? "병상 없음" : h.st === "a" && h.notSelected ? "선택 안 됨" : ST_LABEL[h.st];
export const ST_DOT: Record<St, string> = { w: "#F6C21B", r: "#D93025", a: "#7CB342", t: "#168A55" };
export const ST_PILL: Record<St, string> = { w: "#F2B90F", r: "#D93025", a: "#7CB342", t: "#168A55" };
export const ST_TEXT: Record<St, string> = { w: "#C75B00", r: "#D93025", a: "#4E8B1F", t: "#168A55" };

// 응급의료기관 등급(범례·사건과 무관한 병원 점 색)
export const LEVEL_DOT: Record<string, string> = { 권역응급의료센터: "#B8195F", 지역응급의료센터: "#0F9AA8" };
export const LEVEL_DEFAULT = "#1F4E9C";

export type Sev = "중증" | "중등증" | "경증";
const SEV_OF: Record<string, Sev> = { high: "중증", medium: "중등증", low: "경증" };
export const SEV_STYLE: Record<Sev, { background: string; color: string }> = {
  중증: { background: "#FDECEA", color: "#D93025" },
  중등증: { background: "#FFF1E0", color: "#C75B00" },
  경증: { background: "#E8EEF8", color: "#1F4E9C" },
};
const SEV_RANK: Record<Sev, number> = { 중증: 0, 중등증: 1, 경증: 2 };

export function sevOf(tag: Severity | string | null | undefined): Sev | null {
  return tag ? SEV_OF[tag] ?? null : null;
}

// ── 구급차 상태(시안: 현장 도착·출동 중·이송 중·기지 대기) ─────────────────────────
export type AmbKey = "s" | "d" | "t" | "b";
const AMB_KEY: Record<AmbulancePhase, AmbKey> = {
  on_scene: "s", rerouting: "s", dispatching: "d", transporting: "t", at_hospital: "t", idle: "b", returning: "b",
};
const AMB_TEXT: Record<AmbulancePhase, string> = {
  on_scene: "현장 도착", rerouting: "재선택 대기", dispatching: "출동 중", transporting: "이송 중",
  at_hospital: "병원 도착", idle: "기지 대기", returning: "복귀 중",
};
export const AMB_RANK: Record<AmbKey, number> = { s: 0, t: 1, d: 2, b: 3 };
export const AMB_CHIP: Record<AmbKey, CSSProperties> = {
  s: { background: "#F26B1D", color: "#fff", fontWeight: 700 },
  d: { background: "#FFF0E6", color: "#C7511A", fontWeight: 700, border: "1px solid #F2B48F", lineHeight: "15px" },
  t: { background: "#168A55", color: "#fff", fontWeight: 700 },
  b: { border: "1px solid #C5CCD6", color: "#5A6676", lineHeight: "15px" },
};

export function ambState(sim: AmbulanceSimState | undefined): { key: AmbKey; text: string } {
  const phase: AmbulancePhase = sim?.phase ?? "idle";
  return { key: AMB_KEY[phase], text: AMB_TEXT[phase] };
}

// 관제 지도 왼쪽 패널(사건 목록·선택한 사건) 폭과 지도와의 간격 — 알림 카드가 지도 왼쪽 끝에 맞추는 데도 쓴다
export const SIDEBAR_W = 440;
export const SIDEBAR_GAP = 16;

// ── 사건 ─────────────────────────────────────────────────────────────────────
export interface IncHospital {
  hospitalId: string;
  name: string;
  st: St;
  // "병상 없음"(E-Gen) 또는 병원이 직접 거절 — 표시 문구가 다르다
  bedsFull: boolean;
  // 수용 승인했지만 이송은 다른 병원으로 확정됨(hub notSelected, 2026-10-24) — st는 "a" 그대로, 문구만 "선택 안 됨"
  notSelected?: boolean;
  km: number;
  zone: number;
  respondedAt: string | null;
  // 수용 불가 사유(병원이 고른 것 또는 E-Gen 병상 없음) — 없으면 null
  reason?: string | null;
}

export interface Incident {
  caseId: string;
  num: number;
  sev: Sev | null;
  sym: string | null;
  name: string;
  apid: string | null;
  startedAt: number;
  center: { lat: number; lng: number } | null;
  matched: boolean;
  phase: AmbulancePhase | null;
  hospitals: IncHospital[];
  zone: number;
  zoneStart: number;
  zoneBandKm: number;
  events: CaseEvent[];
  // 다음 자동 존 확장 시각(epoch ms) — 없으면 멈춤
  zoneExpandAt: number | null;
  // [정지] 중 멈춰 있는 남은 시간(초)
  zonePausedLeft: number | null;
  // 관제 지도 [자동 시연]이 화면 안에서만 만든 가짜 사건(2026-10-06) — hub·로그와 무관
  fake?: boolean;
}

// 화면용 짧은 이름(2026-10-04) — 실제 이름이 길어("회현119안전센터 구급 1", "학교법인 고려중앙학원 고려대학교…")
// 좁은 칸에서 잘리던 것을 줄인다. 전체 이름은 title(마우스를 올리면)로 보여준다.
export function shortAmb(name: string): string {
  return name.replace(/\s*119안전센터\s*/, " ").replace(/\s+/g, " ").trim();
}
export function shortHospital(name: string): string {
  return name.replace(/^(학교법인|의료법인|재단법인|사회복지법인|사단법인)\s+\S+\s+(?=\S)/, "").trim();
}

// 존 범위 문구 — 존 1뿐이면 "존 1", 넓혀졌으면 "존 1~N"
export function zoneText(zone: number): string {
  return zone > 1 ? `존 1~${zone}` : "존 1";
}

export function haversineKm(a: { lat: number; lng: number }, b: { lat: number; lng: number }): number {
  const rad = Math.PI / 180;
  const dLat = (b.lat - a.lat) * rad;
  const dLng = (b.lng - a.lng) * rad;
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(a.lat * rad) * Math.cos(b.lat * rad) * Math.sin(dLng / 2) ** 2;
  return 2 * 6371 * Math.asin(Math.sqrt(h));
}

// 진행 중 사건 = 매칭된 사건(case_overview) + 매칭 전 사건(출동~현장 통화 전: 구급차 시뮬레이션 + 사건 정보·예비 고지)
export function buildIncidents(input: {
  monitorCases: Record<string, MonitorCase>;
  caseMeta: Record<string, CaseMeta>;
  preAlerts: Record<string, PreAlert>;
  ambulanceSim: Record<string, AmbulanceSimState>;
  overview: MapOverview | null;
}): Incident[] {
  const { monitorCases, caseMeta, preAlerts, ambulanceSim, overview } = input;
  const nameOf = (apid: string | null | undefined) =>
    (apid && overview?.ambulances.find((a) => a.apid === apid)?.name) || apid || "구급차";
  const simByCase = new Map<string, AmbulanceSimState>();
  for (const sim of Object.values(ambulanceSim)) if (sim.caseId) simByCase.set(sim.caseId, sim);

  const out: Incident[] = [];
  let fallbackNum = 1000;
  for (const mc of Object.values(monitorCases)) {
    const meta = caseMeta[mc.caseId];
    const pre = preAlerts[mc.caseId];
    const sim = simByCase.get(mc.caseId);
    out.push({
      caseId: mc.caseId,
      num: mc.num ?? meta?.num ?? fallbackNum++,
      sev: sevOf(mc.severityTag) ?? sevOf(meta?.severity ?? pre?.reportedSeverity),
      sym: mc.symptom ?? meta?.symptom ?? pre?.reportedSymptom ?? null,
      name: mc.ambulanceName ?? nameOf(mc.apid),
      apid: mc.apid,
      startedAt: Date.parse(mc.startedAt ?? meta?.startedAt ?? pre?.timestamp ?? "") || Date.now(),
      center: mc.ambulanceGps ?? sim?.incident ?? null,
      matched: true,
      phase: sim?.phase ?? null,
      hospitals: mc.hospitals.map((h) => ({
        hospitalId: h.hospitalId,
        name: h.name,
        st: ST_OF[h.status],
        bedsFull: h.status === "rejected" && h.unavailableReason === "beds_full",
        notSelected: h.status === "approved" && !!h.notSelected,
        km: h.distanceKm,
        zone: h.zone,
        respondedAt: h.respondedAt ?? null,
        reason: h.status === "rejected" ? unavailableReasonLabel(h.unavailableReason) ?? rejectionReasonLabel(h.rejectReason) : null,
      })),
      zone: Math.max(1, ...mc.zoneActive),
      zoneStart: Math.min(...(mc.zoneActive.length ? mc.zoneActive : [1])),
      zoneBandKm: mc.zoneBandKm,
      events: mc.events ?? [],
      zoneExpandAt: mc.zoneExpandAt ? Date.parse(mc.zoneExpandAt) : null,
      zonePausedLeft: mc.zonePausedLeftSec ?? null,
    });
  }
  // 매칭 전: 출동한(사건이 배정된) 구급차 중 아직 사건 요약이 없는 것
  for (const sim of Object.values(ambulanceSim)) {
    if (!sim.caseId || monitorCases[sim.caseId] || ["idle", "returning"].includes(sim.phase)) continue;
    const meta = caseMeta[sim.caseId];
    const pre = preAlerts[sim.caseId];
    out.push({
      caseId: sim.caseId,
      num: meta?.num ?? fallbackNum++,
      sev: sevOf(meta?.severity ?? pre?.reportedSeverity),
      sym: meta?.symptom ?? pre?.reportedSymptom ?? null,
      name: meta?.ambulanceName ?? pre?.ambulanceName ?? nameOf(sim.apid),
      apid: sim.apid,
      startedAt: Date.parse(meta?.startedAt ?? pre?.timestamp ?? "") || Date.now(),
      center: sim.incident ?? sim.gps,
      matched: false,
      phase: sim.phase,
      hospitals: [],
      zone: 0,
      zoneStart: 0,
      zoneBandKm: 5,
      events: meta?.events ?? [],
      zoneExpandAt: null,
      zonePausedLeft: null,
    });
  }
  const sevRank = (s: Sev | null) => (s ? SEV_RANK[s] : 3);
  return out.sort((a, b) => sevRank(a.sev) - sevRank(b.sev) || a.startedAt - b.startedAt);
}

export function counts(inc: Incident): Record<St, number> {
  const c: Record<St, number> = { w: 0, r: 0, a: 0, t: 0 };
  for (const h of inc.hospitals) c[h.st]++;
  return c;
}

// 사건 목록 둘째 줄 — 지금 어느 단계인지
export function stageOf(inc: Incident): { text: string; color: string } {
  if (!inc.matched) {
    if (inc.phase === "dispatching") return { text: "현장 출동 중", color: "#C7511A" };
    return { text: "현장 확인 중 · 병원 요청 전", color: "#C7511A" };
  }
  const t = inc.hospitals.find((h) => h.st === "t");
  if (t) {
    const arrived = inc.phase === "at_hospital";
    return { text: `${arrived ? "병원 도착" : "이송 중"} · ${shortHospital(t.name)}`, color: "#168A55" };
  }
  const a = inc.hospitals.find((h) => h.st === "a");
  if (a) return { text: `수용 승인 · ${shortHospital(a.name)}`, color: "#4E8B1F" };
  if (inc.phase === "rerouting") return { text: "도착 후 수용 불가 · 재선택 대기", color: "#D93025" };
  return { text: "병원 판단 중", color: "#C75B00" };
}

export const two = (n: number) => String(n).padStart(2, "0");
export function fmtElapsed(ms: number): string {
  const s = Math.max(0, Math.floor(ms / 1000));
  return `${two(Math.floor(s / 60))}:${two(s % 60)}`;
}
export function fmtClock(ts: string | number): string {
  const d = new Date(ts);
  return `${two(d.getHours())}:${two(d.getMinutes())}:${two(d.getSeconds())}`;
}
export function fmtHm(ts: string | number): string {
  const d = new Date(ts);
  return `${two(d.getHours())}:${two(d.getMinutes())}`;
}
export function fmtMd(ts: string | number): string {
  const d = new Date(ts);
  return `${two(d.getMonth() + 1)}/${two(d.getDate())}`;
}

// 진행 과정 이벤트 색(시안)
export const EVENT_TONE: Record<string, string> = {
  p: "#4A5565", s: "#14213D", r: "#D93025", x: "#C75B00", a: "#4E8B1F", t: "#168A55", d: "#14213D", c: "#7A8594",
};

// 지난 사건의 결과 문구
const CANCEL_TEXT: Record<string, string> = {
  scene_ended: "상황 취소",
  sim_reset: "시연 초기화",
  unresolved_timeout: "자동 종료(방치)",
  retention_expired: "정리됨(도착 결과 없음)",
  hub_restart_sim_reset: "hub 재시작",
};
export function pastResult(item: { result: string; reason: string; hospital?: string | null }): {
  text: string;
  style: CSSProperties;
} {
  if (item.result === "done") {
    return { text: `이송 완료 · ${item.hospital ? shortHospital(item.hospital) : "병원"}`, style: { background: "#E3F5EC", color: "#168A55" } };
  }
  return { text: CANCEL_TEXT[item.reason] ?? "종료", style: { background: "#F1F3F6", color: "#5A6676" } };
}
