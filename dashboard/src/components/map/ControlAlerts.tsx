"use client";

import { useEffect } from "react";
import { C, SEV_STYLE, SIDEBAR_GAP, SIDEBAR_W, counts, shortAmb, stageOf, type Incident } from "@/lib/control-map";
import type { AlertLevel, ControlAlert } from "@/lib/control-alerts";

// 관제 지도 알림 표시 — 헤더의 알림음 버튼과 화면 오른쪽 위에 쌓이는 알림 카드.
// 여러 알림이 쌓여도 한눈에 읽히게 **사건 하나당 카드 하나**로 묶는다: 맨 위에 그 사건이 지금 어떤 상태인지(번호·구급차·중증도·
// 증상·현재 단계·병원 응답 수), 아래에 왜 알리는지(긴급 → 주의 순). 새 사건도 위험 신호라 긴급과 같은 빨강 계열(긴급이 더 진함),
// 주의는 주황, 시스템은 회색. 관제는 큰 화면을 여럿이 멀리서 보므로 크기를 em으로 잡고 화면 너비에 비례해 키운다(clamp).

const TONE: Record<AlertLevel, { bg: string; bar: string; text: string; label: string }> = {
  urgent: { bg: "#FBD9D5", bar: "#B3261E", text: "#8C1B14", label: "긴급" },
  info: { bg: "#FDECEA", bar: "#D93025", text: "#A5251B", label: "NEW" },
  warn: { bg: "#FFF1E0", bar: "#C75B00", text: "#8F4300", label: "주의" },
  system: { bg: "#F1F3F6", bar: "#5A6676", text: "#2A3441", label: "시스템" },
};
const RANK: Record<AlertLevel, number> = { urgent: 0, info: 1, warn: 2, system: 3 };
const MAX_SHOWN = 5;

interface Group {
  id: string;
  caseId: string | null;
  level: AlertLevel;
  items: ControlAlert[];
  keys: string[];
  fake: boolean;
}

/** 사건별로 묶는다. 사건 없는 알림(시스템)은 따로. 카드 순서는 가장 높은 등급 → 들어온 순. */
function groupAlerts(alerts: ControlAlert[]): Group[] {
  const map = new Map<string, Group>();
  for (const a of alerts) {
    const id = a.caseId ?? a.key;
    const g = map.get(id) ?? { id, caseId: a.caseId, level: a.level, items: [], keys: [], fake: a.fake };
    g.items.push(a);
    g.keys.push(a.key);
    if (RANK[a.level] < RANK[g.level]) g.level = a.level;
    map.set(id, g);
  }
  return [...map.values()].sort((a, b) => RANK[a.level] - RANK[b.level]);
}

/** 수용할 병원이 없는 상황(승인 병원 없음·전부 수용 불가·재선택 대기)이면 보기만이 아니라 개입이 필요한 사건이다 */
const NO_HOSPITAL_KINDS = ["noapproval", "allrejected", "rerouting", "confirmwait"];
const needsIntervention = (g: Group) => g.keys.some((k) => NO_HOSPITAL_KINDS.some((kind) => k.endsWith(`:${kind}`)));

/** 다른 탭을 보는 중에도 알림이 있다는 걸 알 수 있게 탭 제목을 바꾼다 */
export function useAlertTabTitle(count: number) {
  useEffect(() => {
    if (count === 0) return;
    const original = document.title;
    let on = false;
    const timer = setInterval(() => {
      on = !on;
      document.title = on && document.hidden ? `(${count}) 관제 알림` : original;
    }, 1000);
    return () => {
      clearInterval(timer);
      document.title = original;
    };
  }, [count]);
}

/** 사건에 걸린 알림 중 가장 높은 등급의 제목(사건 목록 행에 쓴다) */
export function topAlertOf(alerts: ControlAlert[], caseId: string): ControlAlert | null {
  let best: ControlAlert | null = null;
  for (const a of alerts) if (a.caseId === caseId && (!best || RANK[a.level] < RANK[best.level])) best = a;
  return best;
}

export function AlertStack({ dark = false, alerts, incidents, onAck, onAckAll, onOpen, onHandle }: {
  dark?: boolean;
  alerts: ControlAlert[];
  incidents: Incident[];
  onAck: (keys: string[]) => void;
  onAckAll: () => void;
  onOpen: (caseId: string) => void;
  onHandle: (caseId: string, keys: string[]) => void;
}) {
  const groups = groupAlerts(alerts);
  const n = groups.length;
  if (n === 0) return null;
  const byId = new Map(incidents.map((i) => [i.caseId, i]));
  const urgentAny = groups.some((g) => g.level === "urgent");
  // 로그형: 한 줄에 알림 한 건. 왼쪽 세로선 = 등급, 그 오른쪽에 사건 · 단계 · 사유 · 조치. 평평한 반투명 패널 하나.
  return (
    <div role="region" aria-label="관제 알림" style={{ position: "absolute", top: 8, left: SIDEBAR_W + SIDEBAR_GAP, right: SIDEBAR_W + SIDEBAR_GAP, zIndex: 250, fontSize: "clamp(12px, 0.7vw, 14px)", display: "flex", justifyContent: "center", whiteSpace: "normal", pointerEvents: "none" }}>
      <div style={{ pointerEvents: "auto", width: "100%", maxWidth: 980, boxSizing: "border-box", borderRadius: 4, overflow: "hidden", border: dark ? "1px solid rgba(130,150,210,.30)" : "1px solid rgba(20,33,61,.14)", background: dark ? "rgba(11,17,38,.86)" : "rgba(255,255,255,.88)", backdropFilter: "blur(16px) saturate(1.2)", WebkitBackdropFilter: "blur(16px) saturate(1.2)", boxShadow: "0 1px 3px rgba(20,33,61,.18)" }}>
        <div style={{ filter: dark ? "invert(1) hue-rotate(180deg) brightness(1.25) saturate(1.15)" : undefined }}>
          <div style={{ display: "flex", alignItems: "center", gap: "0.8em", padding: "0.35em 0.8em", borderBottom: `1px solid ${C.line2}`, background: C.bg, fontSize: "0.9em", color: C.sub }}>
            <b style={{ color: urgentAny ? "#B3261E" : C.ink2 }}>관제 알림 {n}건</b>
            <span style={{ flex: "1 1 auto" }} />
            {n > MAX_SHOWN && <span>외 {n - MAX_SHOWN}건</span>}
            <button type="button" onClick={onAckAll} style={{ border: 0, background: "transparent", padding: 0, fontFamily: "inherit", fontSize: "1em", fontWeight: 700, color: C.ink2, cursor: "pointer", textDecoration: "underline" }}>모두 확인</button>
          </div>
          {groups.slice(0, MAX_SHOWN).map((g) => {
            const tone = TONE[g.level];
            const inc = g.caseId ? byId.get(g.caseId) : undefined;
            const stage = inc ? stageOf(inc) : null;
            const c = inc ? counts(inc) : null;
            return (
              <div key={g.id} role={g.level === "urgent" || g.level === "info" ? "alert" : "status"} style={{ display: "flex", alignItems: "stretch", borderBottom: `1px solid ${C.line2}`, borderLeft: `3px solid ${tone.bar}`, background: g.level === "urgent" ? "#FDF1EF" : undefined }}>
                <button
                  type="button"
                  disabled={!g.caseId}
                  onClick={() => g.caseId && onOpen(g.caseId)}
                  style={{ flex: "1 1 auto", minWidth: 0, padding: "0.4em 0.8em", border: 0, background: "transparent", textAlign: "left", fontFamily: "inherit", cursor: g.caseId ? "pointer" : "default", display: "flex", alignItems: "center", gap: "0.9em", whiteSpace: "nowrap", overflow: "hidden", fontVariantNumeric: "tabular-nums" }}
                >
                  <span style={{ flex: "none", width: "3.2em", fontSize: "0.85em", fontWeight: 700, color: tone.text }}>{tone.label}</span>
                  {inc && stage && c && (
                    <>
                      <span style={{ flex: "none", display: "flex", alignItems: "center", gap: "0.5em", minWidth: 0, maxWidth: "34%", overflow: "hidden" }}>
                        <span style={{ flex: "none", fontWeight: 700, color: C.ink3 }}>#{inc.num}</span>
                        {inc.sev && <span style={{ flex: "none", fontSize: "0.9em", fontWeight: 700, padding: "0 0.45em", borderRadius: 2, lineHeight: "1.5em", ...SEV_STYLE[inc.sev] }}>{inc.sev}</span>}
                        <span style={{ flex: "0 1 auto", minWidth: 0, fontWeight: 700, color: C.navy, overflow: "hidden", textOverflow: "ellipsis" }}>{shortAmb(inc.name)}</span>
                        {inc.sym && <span style={{ flex: "0 1 auto", minWidth: 0, color: C.ink3, overflow: "hidden", textOverflow: "ellipsis" }}>{inc.sym}</span>}
                      </span>
                      <span style={{ flex: "none", display: "flex", gap: "0.7em", color: C.ink3 }}>
                        <span style={{ color: stage.color, fontWeight: 700 }}>{stage.text}</span>
                        {inc.matched && <span>대기 {c.w} · <span style={{ color: "#D93025" }}>불가 {c.r}</span> · <span style={{ color: "#4E8B1F" }}>승인 {c.a + c.t}</span></span>}
                      </span>
                    </>
                  )}
                  <span style={{ flex: "1 1 0", minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", color: tone.text }}>
                    {(inc ? g.items : g.items.slice(0, 1)).map((a) => (
                      <span key={a.key} style={{ marginRight: "1em" }}>
                        <b>{a.title}</b>{a.detail && <span style={{ color: C.ink3 }}> {a.detail}</span>}
                      </span>
                    ))}
                    {g.fake && <span style={{ color: C.muted }}>시연</span>}
                  </span>
                </button>
                <div style={{ flex: "none", display: "flex", alignItems: "center", gap: "0.4em", padding: "0 0.6em" }}>
                  {g.caseId && (
                    <button type="button" onClick={() => onHandle(g.caseId as string, g.keys)} style={{ border: 0, borderRadius: 3, padding: "0.25em 0.8em", background: tone.bar, fontFamily: "inherit", fontSize: "0.95em", fontWeight: 700, color: "#fff", cursor: "pointer" }}>
                      {needsIntervention(g) ? "개입" : "보기"}
                    </button>
                  )}
                  <button type="button" aria-label="알림 확인" onClick={() => onAck(g.keys)} style={{ border: `1px solid ${C.line}`, borderRadius: 3, padding: "0.25em 0.8em", background: "#fff", fontFamily: "inherit", fontSize: "0.95em", fontWeight: 700, color: C.ink2, cursor: "pointer" }}>
                    확인
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
