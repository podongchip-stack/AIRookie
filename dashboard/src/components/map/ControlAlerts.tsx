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
  info: { bg: "#FDECEA", bar: "#D93025", text: "#A5251B", label: "새 사건" },
  warn: { bg: "#FFF1E0", bar: "#C75B00", text: "#8F4300", label: "주의" },
  system: { bg: "#F1F3F6", bar: "#5A6676", text: "#2A3441", label: "시스템" },
};
const RANK: Record<AlertLevel, number> = { urgent: 0, info: 1, warn: 2, system: 3 };
const MAX_SHOWN = 3;

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
const NO_HOSPITAL_KINDS = ["noapproval", "allrejected", "rerouting"];
const needsIntervention = (g: Group) => g.keys.some((k) => NO_HOSPITAL_KINDS.some((kind) => k.endsWith(`:${kind}`)));

export function AlertSoundButton({ soundOn, count, onToggle }: { soundOn: boolean; count: number; onToggle: () => void }) {
  return (
    <button
      type="button"
      aria-pressed={soundOn}
      onClick={onToggle}
      title={soundOn ? "긴급 알림이 오면 소리를 냅니다 (누르면 끔)" : "누르면 알림음을 켭니다"}
      style={{
        display: "inline-flex", alignItems: "center", gap: 6, height: 26, padding: "0 12px", border: 0, borderRadius: 13,
        fontFamily: "inherit", fontSize: 12, fontWeight: 500, cursor: "pointer",
        background: soundOn ? C.navy : C.bg, color: soundOn ? "#fff" : C.ink2,
      }}
    >
      {soundOn ? "알림음 켜짐" : "알림음 꺼짐"}
      {count > 0 && (
        <span style={{ fontSize: 10.5, fontWeight: 700, color: "#fff", background: "#D93025", borderRadius: 8, padding: "0 6px", lineHeight: "15px" }}>{count}</span>
      )}
    </button>
  );
}

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

export function AlertStack({ alerts, incidents, onAck, onAckAll, onOpen, onHandle }: {
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
  return (
    <div role="region" aria-label="관제 알림" style={{ position: "absolute", top: 8, left: SIDEBAR_W + SIDEBAR_GAP, right: 0, zIndex: 250, fontSize: "clamp(12px, 0.7vw, 15px)", display: "flex", flexDirection: "column", alignItems: "stretch", gap: "0.4em", whiteSpace: "normal" }}>
      <style>{"@keyframes alpulse{0%,100%{box-shadow:0 .4em 1.2em rgba(20,30,50,.3)}50%{box-shadow:0 0 0 .35em rgba(217,48,37,.45),0 .4em 1.2em rgba(20,30,50,.3)}}.al-red{animation:alpulse 1.2s ease-in-out infinite}@media (prefers-reduced-motion:reduce){.al-red{animation:none}}"}</style>
      {groups.slice(0, MAX_SHOWN).map((g) => {
        const tone = TONE[g.level];
        const inc = g.caseId ? byId.get(g.caseId) : undefined;
        const stage = inc ? stageOf(inc) : null;
        const c = inc ? counts(inc) : null;
        return (
          <div key={g.id} role={g.level === "urgent" || g.level === "info" ? "alert" : "status"} className={g.level === "urgent" || g.level === "info" ? "al-red" : undefined} style={{ display: "flex", borderRadius: "0.6em", overflow: "hidden", background: "#fff", border: `0.12em solid ${tone.bar}`, boxShadow: "0 .4em 1.2em rgba(20,30,50,.3)" }}>
            <button
              type="button"
              disabled={!g.caseId}
              onClick={() => g.caseId && onOpen(g.caseId)}
              style={{ flex: "1 1 auto", minWidth: 0, padding: 0, border: 0, background: "transparent", textAlign: "left", fontFamily: "inherit", cursor: g.caseId ? "pointer" : "default", display: "flex", alignItems: "stretch", overflow: "hidden" }}
            >
              {/* 한 줄 배치 — 사건(번호·중증도·구급차·증상) | 단계·응답 수 | 알리는 이유 */}
              {inc && stage && c ? (
                <>
                  <div style={{ flex: "1 1 auto", minWidth: 0, overflow: "hidden", display: "flex", alignItems: "center", gap: "0.45em", whiteSpace: "nowrap", padding: "0.4em 0.75em", borderRight: `1px solid ${C.line2}` }}>
                    <span style={{ flex: "none", minWidth: "1.7em", height: "1.7em", padding: "0 0.3em", boxSizing: "border-box", borderRadius: "0.85em", background: C.navy, color: "#fff", fontSize: "0.9em", fontWeight: 700, display: "flex", alignItems: "center", justifyContent: "center" }}>{inc.num}</span>
                    {inc.sev && <span style={{ flex: "none", fontSize: "0.9em", fontWeight: 700, padding: "0 0.6em", borderRadius: "0.8em", lineHeight: "1.6em", ...SEV_STYLE[inc.sev] }}>{inc.sev}</span>}
                    <span style={{ flex: "0 1 auto", minWidth: 0, fontSize: "1.1em", fontWeight: 900, color: C.navy, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{shortAmb(inc.name)}</span>
                    {inc.sym && <span style={{ flex: "1 1 0", minWidth: 0, fontSize: "0.95em", color: C.ink2, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{inc.sym}</span>}
                    {g.fake && <span style={{ flex: "none", fontSize: "0.8em", color: C.muted }}>시연</span>}
                  </div>
                  <div style={{ flex: "0 1 auto", minWidth: 0, overflow: "hidden", display: "flex", alignItems: "center", gap: "0.8em", whiteSpace: "nowrap", padding: "0.4em 0.75em", borderRight: `1px solid ${C.line2}`, fontSize: "0.95em" }}>
                    <span style={{ flex: "0 1 auto", minWidth: 0, fontWeight: 700, color: stage.color, overflow: "hidden", textOverflow: "ellipsis" }}>{stage.text}</span>
                    {inc.matched && (
                      <span style={{ flex: "none", display: "flex", gap: "0.5em", fontVariantNumeric: "tabular-nums", color: C.ink3, whiteSpace: "nowrap" }}>
                        <span>대기 <b>{c.w}</b></span>
                        <span style={{ color: "#D93025" }}>불가 <b>{c.r}</b></span>
                        <span style={{ color: "#4E8B1F" }}>승인 <b>{c.a + c.t}</b></span>
                      </span>
                    )}
                  </div>
                </>
              ) : null}
              {/* 알리는 이유 — 가로로 나열 */}
              <div style={{ flex: "none", display: "flex", flexWrap: "nowrap", alignItems: "center", gap: "0.9em", padding: "0.4em 0.75em", whiteSpace: "nowrap" }}>
                {(inc ? g.items : g.items.slice(0, 1)).map((a) => {
                  const t = TONE[a.level];
                  return (
                    <span key={a.key} style={{ flex: "none", display: "inline-flex", alignItems: "baseline", gap: "0.4em" }}>
                      <span style={{ flex: "none", fontSize: "0.8em", fontWeight: 700, color: "#fff", background: t.bar, borderRadius: "0.5em", padding: "0 0.5em", lineHeight: "1.5em" }}>{t.label}</span>
                      <span style={{ fontSize: "1em", fontWeight: 900, color: t.text }}>{a.title}</span>
                      {a.detail && <span style={{ fontSize: "0.9em", color: C.ink3 }}>{a.detail}</span>}
                    </span>
                  );
                })}
              </div>
            </button>
            <div style={{ flex: "none", display: "flex", borderLeft: `1px solid ${C.line2}` }}>
              {g.caseId && (
                <button type="button" onClick={() => onHandle(g.caseId as string, g.keys)} style={{ border: 0, padding: "0 1.1em", background: tone.bar, fontFamily: "inherit", fontSize: "0.95em", fontWeight: 700, color: "#fff", cursor: "pointer", whiteSpace: "nowrap" }}>
                  {needsIntervention(g) ? "사건 개입" : "사건 보기"}
                </button>
              )}
              <button type="button" aria-label="알림 확인" onClick={() => onAck(g.keys)} style={{ border: 0, borderLeft: g.caseId ? `1px solid ${C.line2}` : 0, padding: "0 1.1em", background: "#fff", fontFamily: "inherit", fontSize: "0.95em", fontWeight: 700, color: tone.text, cursor: "pointer", whiteSpace: "nowrap" }}>
                확인
              </button>
            </div>
          </div>
        );
      })}
      {n > 1 && (
        <button type="button" onClick={onAckAll} style={{ flex: "none", alignSelf: "flex-end", border: 0, borderRadius: "0.6em", padding: "0.3em 0.9em", background: "#fff", boxShadow: "0 2px 8px rgba(20,30,50,.2)", fontFamily: "inherit", fontSize: "0.85em", color: C.ink3, cursor: "pointer" }}>
          {n > MAX_SHOWN ? `외 ${n - MAX_SHOWN}건 · ` : ""}모두 확인
        </button>
      )}
    </div>
  );
}
