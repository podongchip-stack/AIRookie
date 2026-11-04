import { zoneText, type Incident } from "@/lib/control-map";
import type { AmbulancePhase } from "@/types/dashboard";

// 관제 지도 알림 규칙(2026-10-27 초안). 새 데이터 없이 관제가 이미 받는 사건 요약(Incident)에서만 만든다 — 규칙 기반이고 hub는
// 바뀌지 않는다. 기준 시간은 정답 데이터가 없는 초안 값이라 운영하면서 조정한다(여기 한 곳).
export const ALERT_RULES = {
  /** 병원 요청 후 승인 병원이 하나도 없는 채로 이만큼 지나면 주의 */
  noApprovalMin: 3,
  /** 병원이 수용 승인했는데 구급대원이 이송 확정을 이만큼 안 누르면 주의 + 관제 대행 버튼(2026-11-02, 1분 초안) */
  confirmDelayMin: 1,
  /** 출동·병원 도착 결과 대기·재선택 대기에 이만큼 머물면 주의 (이송 중은 길 수 있어 제외) */
  stuckMin: 10,
  /** 상황실 배정 요청(관제 판단 대기)이 이만큼 처리되지 않으면 긴급 — 그동안 구급대 이송 승인이 잠겨 있다(2026-11-04 초안) */
  assignmentWaitMin: 2,
};

/** 새 사건 접수를 알리는 카드가 머무는 시간 — 사건 목록의 NEW 깜빡임도 같은 시간 */
export const NEW_CASE_MS = 10_000;

export type AlertLevel = "urgent" | "info" | "warn" | "system";

export interface ControlAlert {
  /** 같은 상황은 같은 key — 확인(ack)·중복 방지의 기준 */
  key: string;
  level: AlertLevel;
  caseId: string | null;
  title: string;
  detail: string;
  /** 관제 지도 자동 시연이 만든 가짜 사건 — 소리 없이 화면에만 보인다 */
  fake: boolean;
}

/** 지속 시간 계산에 쓰는 관찰 기록 — deriveAlerts가 갱신한다(렌더 밖 1초 틱에서만 부른다) */
export interface AlertTracker {
  seenAt: Map<string, number>;
  matchedAt: Map<string, number>;
  phaseSince: Map<string, number>;
}
export const newTracker = (): AlertTracker => ({ seenAt: new Map(), matchedAt: new Map(), phaseSince: new Map() });

const STUCK_PHASES: Partial<Record<AmbulancePhase, string>> = {
  dispatching: "출동 중",
  at_hospital: "병원 도착 후 수용 결과 대기",
  rerouting: "재선택 대기",
};
const LEVEL_RANK: Record<AlertLevel, number> = { urgent: 0, info: 1, warn: 2, system: 3 };

export function deriveAlerts(incidents: Incident[], now: number, tr: AlertTracker, assignOpened: Record<string, string> = {}): ControlAlert[] {
  const out: ControlAlert[] = [];
  const liveIds = new Set(incidents.map((i) => i.caseId));
  for (const id of tr.matchedAt.keys()) if (!liveIds.has(id)) tr.matchedAt.delete(id);
  for (const id of tr.seenAt.keys()) if (!liveIds.has(id)) tr.seenAt.delete(id);
  for (const k of tr.phaseSince.keys()) if (!liveIds.has(k.split("|")[0])) tr.phaseSince.delete(k);

  for (const inc of incidents) {
    const fake = !!inc.fake;
    const push = (kind: string, level: AlertLevel, title: string, detail: string) =>
      out.push({ key: `${inc.caseId}:${kind}`, level, caseId: inc.caseId, title, detail, fake });

    if (!tr.seenAt.has(inc.caseId)) tr.seenAt.set(inc.caseId, now);
    if (now - (tr.seenAt.get(inc.caseId) ?? now) < NEW_CASE_MS) {
      push("new", "info", "새 사건 접수", "");
    }
    if (inc.sev === "중증") push("severe", "urgent", "중증 사건", "");
    // 상황실 배정 대기(2026-11-04) — 자동 확정은 하지 않는다(결정은 사람). 오래 두면 긴급으로 올려 알린다.
    const opened = assignOpened[inc.caseId];
    if (opened) {
      const min = Math.max(0, (now - Date.parse(opened)) / 60_000);
      const late = min >= ALERT_RULES.assignmentWaitMin;
      push(late ? "assignlate" : "assign", late ? "urgent" : "warn", late ? "상황실 배정 지연" : "상황실 배정 요청",
        `${Math.floor(min)}분째 관제 판단 대기 · 구급대 이송 승인 잠김`);
    }

    if (inc.matched && !tr.matchedAt.has(inc.caseId)) tr.matchedAt.set(inc.caseId, now);
    const requestedAt = Date.parse(inc.events.find((e) => e.kind === "s")?.t ?? "") || tr.matchedAt.get(inc.caseId) || now;
    const hasApproval = inc.hospitals.some((h) => h.st === "a" || h.st === "t");
    const allRejected = inc.matched && inc.hospitals.length > 0 && inc.hospitals.every((h) => h.st === "r");

    if (allRejected) push("allrejected", "urgent", "요청 병원 전부 수용 불가", `${inc.hospitals.length}곳 모두 불가 (${zoneText(inc.zone)})`);
    if (inc.phase === "rerouting") push("rerouting", "urgent", "수용 철회 · 재선택 대기", "이송 병원을 다시 정해야 합니다");

    const waitMin = (now - requestedAt) / 60_000;
    if (inc.matched && !hasApproval && !allRejected && inc.phase !== "rerouting" && waitMin >= ALERT_RULES.noApprovalMin) {
      push("noapproval", "warn", "승인 병원 없음", `요청 후 ${Math.floor(waitMin)}분째 · 판단 대기 ${inc.hospitals.filter((h) => h.st === "w").length}곳`);
    }
    if (isConfirmDelayed(inc, now)) {
      push("confirmwait", "warn", "승인 후 이송 확정 지연", `수용 승인 ${inc.hospitals.filter((h) => h.st === "a").length}곳 · ${Math.floor((confirmWaitMs(inc, now) ?? 0) / 60_000)}분째 확정 없음`);
    }
    if (inc.matched && inc.zone >= 2) push(`zone${inc.zone}`, "warn", "요청 범위 확장", `${zoneText(inc.zone)}까지 넓힘`);

    const stuckText = inc.phase ? STUCK_PHASES[inc.phase] : undefined;
    if (inc.phase && stuckText) {
      const sk = `${inc.caseId}|${inc.phase}`;
      if (!tr.phaseSince.has(sk)) tr.phaseSince.set(sk, now);
      const min = (now - (tr.phaseSince.get(sk) ?? now)) / 60_000;
      if (min >= ALERT_RULES.stuckMin) push(`stuck:${inc.phase}`, "warn", "같은 단계에 오래 머묾", `${stuckText} ${Math.floor(min)}분째`);
    }
  }
  return out.sort((a, b) => LEVEL_RANK[a.level] - LEVEL_RANK[b.level]);
}

/** 수용 승인 병원은 있는데 이송 확정이 없는 채로 흐른 시간(ms). 첫 승인 응답 시각 기준 — 해당 없으면 null */
export function confirmWaitMs(inc: Incident, now: number): number | null {
  if (!inc.matched || inc.hospitals.some((h) => h.st === "t")) return null;
  const times = inc.hospitals
    .filter((h) => h.st === "a" && !h.notSelected)
    .map((h) => Date.parse(h.respondedAt ?? ""))
    .filter((t) => !Number.isNaN(t));
  return times.length ? Math.max(0, now - Math.min(...times)) : null;
}
/** 승인 후 이송 확정이 confirmDelayMin분 넘게 안 눌렸는가 — 관제 대행 버튼을 여는 기준 */
export function isConfirmDelayed(inc: Incident, now: number): boolean {
  const w = confirmWaitMs(inc, now);
  return w != null && w >= ALERT_RULES.confirmDelayMin * 60_000;
}

/**
 * 병원 문제로 이송이 막힌 사건 — 이송 확정 전인데 수용할 병원이 없다(전부 수용 불가 / 요청 후 noApprovalMin분 넘게 승인 없음 / 재선택 대기).
 * 알림과 달리 확인(ack)해도 사라지지 않는 사건 상태라, 관제 '처리 조치' 패널을 띄우는 기준으로 쓴다(사건 상세 안, 2026-11-04).
 */
export function isTransportStalled(inc: Incident, now: number): boolean {
  if (!inc.matched || inc.hospitals.some((h) => h.st === "t")) return false;
  if (inc.phase === "rerouting") return true;
  if (inc.hospitals.some((h) => h.st === "a")) return false;
  if (inc.hospitals.length > 0 && inc.hospitals.every((h) => h.st === "r")) return true;
  const requestedAt = Date.parse(inc.events.find((e) => e.kind === "s")?.t ?? "") || inc.startedAt;
  return (now - requestedAt) / 60_000 >= ALERT_RULES.noApprovalMin;
}

export const HUB_DOWN_ALERT: ControlAlert = {
  key: "system:hub",
  level: "system",
  caseId: null,
  title: "hub 연결 끊김",
  detail: "자동으로 다시 연결하는 중입니다 — 그동안 화면 정보는 최신이 아닙니다",
  fake: false,
};
