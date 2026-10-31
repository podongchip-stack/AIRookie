"use client";

import { C, EVENT_TONE, ST_LABEL, fmtClock, shortHospital, stageOf, type Incident } from "@/lib/control-map";
import type { CaseEvent } from "@/types/dashboard";

// 선택한 사건의 진행 과정 — 최근 일이 위. 맨 위 "지금" 줄은 지금 기다리는 것(대기 병원·경과), 아래는 지난 일(시각 · 접수 후 경과).
// 병원 목록 아래 남는 세로 공간을 채운다("방금 무슨 일이 있었나 · 지금 뭘 기다리나"). 새 데이터 없이 사건 요약에서만 만든다.

const fmtSpan = (ms: number) => {
  const sec = Math.max(0, Math.floor(ms / 1000));
  return sec < 60 ? `${sec}초` : `${Math.floor(sec / 60)}분 ${sec % 60}초`;
};

interface Row extends CaseEvent {
  sub?: string;
}

// hub 사건 기록(events)이 아직 없으면(방금 시작된 사건 등) 사건 시작과 병원 응답으로 같은 흐름을 만든다
function rowsOf(inc: Incident): Row[] {
  const startMs = inc.startedAt;
  const since = (t: string) => `접수 후 ${fmtSpan(Date.parse(t) - startMs)}`;
  if (inc.events.length > 0) return inc.events.map((e) => ({ ...e, sub: since(e.t) }));
  const rows: Row[] = [{ t: new Date(startMs).toISOString(), kind: "p", text: "사건 접수", sub: inc.sym ?? undefined }];
  for (const h of inc.hospitals) {
    if (!h.respondedAt) continue;
    const kind = h.st === "r" ? "x" : h.st === "t" ? "t" : "a";
    rows.push({
      t: h.respondedAt,
      kind,
      text: `${shortHospital(h.name)} ${ST_LABEL[h.st]}${h.reason ? ` · ${h.reason}` : ""}`,
      sub: `${h.km.toFixed(1)}km · ${since(h.respondedAt)}`,
    });
  }
  return rows.sort((a, b) => Date.parse(a.t) - Date.parse(b.t));
}

/** 지금 기다리는 것 — 판단 대기 병원 이름(앞 3곳)과 경과 */
function nowRow(inc: Incident, now: number): Row | null {
  const waiting = inc.hospitals.filter((h) => h.st === "w");
  const lastResp = inc.hospitals.reduce((m, h) => Math.max(m, h.respondedAt ? Date.parse(h.respondedAt) : 0), 0);
  const stage = stageOf(inc);
  if (!inc.matched || waiting.length === 0) return { t: "", kind: "now", text: `지금 · ${stage.text}`, sub: `접수 후 ${fmtSpan(now - inc.startedAt)}` };
  const names = waiting.slice(0, 3).map((h) => shortHospital(h.name)).join(", ");
  const more = waiting.length > 3 ? ` 외 ${waiting.length - 3}곳` : "";
  return {
    t: "",
    kind: "now",
    text: `지금 · ${waiting.length}곳 판단 대기`,
    sub: `${names}${more} · ${lastResp ? `마지막 응답 ${fmtSpan(now - lastResp)} 전` : `접수 후 ${fmtSpan(now - inc.startedAt)}째 응답 없음`}`,
  };
}

export function CaseTimeline({ inc, now }: { inc: Incident; now: number }) {
  const live = nowRow(inc, now);
  const past = [...rowsOf(inc)].reverse();
  const list = live ? [live, ...past] : past;
  return (
    <div style={{ flex: "1 1 0", minHeight: 0, display: "flex", flexDirection: "column", borderTop: `1px solid ${C.line2}`, paddingTop: 6 }}>
      <div style={{ flex: "none", padding: "0 2px 4px", fontSize: 11.5, fontWeight: 700, color: C.sub }}>진행 과정 · {past.length}건</div>
      <div className="ctl-scroll" style={{ flex: "1 1 0", minHeight: 0, display: "flex", flexDirection: "column", paddingRight: 2 }}>
        {list.map((e, i) => {
          const isNow = e.kind === "now";
          const tone = isNow ? "#C75B00" : EVENT_TONE[e.kind] ?? C.navy;
          const last = i === list.length - 1;
          return (
            <div key={`${e.t}-${i}`} style={{ flex: "none", display: "flex", gap: 6, padding: "0 4px", background: isNow ? "#FFF6E8" : undefined, borderRadius: 6 }}>
              <span style={{ flex: "none", width: 44, paddingTop: 5, fontSize: 11.5, color: isNow ? "#C75B00" : C.muted, fontWeight: isNow ? 700 : 400, fontVariantNumeric: "tabular-nums" }}>{isNow ? "지금" : fmtClock(e.t)}</span>
              <span style={{ flex: "none", position: "relative", width: 12 }}>
                <span style={{ position: "absolute", left: 2, top: 8, width: 8, height: 8, borderRadius: "50%", background: tone }} />
                {!last && <span style={{ position: "absolute", left: 5, top: 18, bottom: -2, width: 2, background: "#E1E5EB" }} />}
              </span>
              <span style={{ flex: "1 1 0", minWidth: 0, padding: "3px 0 5px", whiteSpace: "normal" }}>
                <span style={{ display: "block", fontSize: 12.5, lineHeight: 1.3, color: tone, fontWeight: isNow || i === 1 || ["d", "t", "x"].includes(e.kind) ? 700 : 500 }}>{isNow ? e.text.replace(/^지금 · /, "") : e.text}</span>
                {e.sub && <span style={{ display: "block", fontSize: 11, lineHeight: 1.3, color: C.sub }}>{e.sub}</span>}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
