"use client";

import { C, counts, stageOf, type Incident } from "@/lib/control-map";

// 선택한 사건의 막힘 요약 — 관제가 "지금 구급차가 무엇을 기다리나 · 얼마나 지났나 · 다음에 자동으로 뭐가 되나"를 한눈에 보게 한다.
// 새 데이터 없이 사건 요약(Incident)에서만 만든다(규칙 기반).

const fmtSpan = (ms: number) => {
  const sec = Math.max(0, Math.floor(ms / 1000));
  return sec < 60 ? `${sec}초` : `${Math.floor(sec / 60)}분 ${sec % 60}초`;
};

/** 지금 상황 한 줄 — 문구와 색 */
function verdictOf(inc: Incident): { text: string; color: string } {
  const c = counts(inc);
  const stage = stageOf(inc);
  if (c.t > 0) return { text: `이송 확정 · ${stage.text}`, color: stage.color };
  if (!inc.matched || inc.phase === "rerouting") return stage;
  if (c.a > 0) return { text: `수용 승인 ${c.a}곳 · 이송 승인 대기`, color: "#4E8B1F" };
  if (inc.hospitals.length > 0 && c.r === inc.hospitals.length) return { text: "요청 병원 전부 수용 불가", color: "#D93025" };
  return { text: `승인 병원 없음 · ${c.w}곳 판단 대기`, color: "#C75B00" };
}

export function CaseStatusSummary({ inc, now }: { inc: Incident; now: number }) {
  const c = counts(inc);
  const total = inc.hospitals.length;
  const verdict = verdictOf(inc);
  const requestedAt = Date.parse(inc.events.find((e) => e.kind === "s")?.t ?? "") || inc.startedAt;
  const lastResp = inc.hospitals.reduce((m, h) => Math.max(m, h.respondedAt ? Date.parse(h.respondedAt) : 0), 0);
  const confirmedAt = Date.parse(inc.events.find((e) => e.kind === "t")?.t ?? "") || 0;
  const segs: [number, string, string][] = [
    [c.t + c.a, "#7CB342", "승인"],
    [c.r, "#D93025", "불가"],
    [c.w, "#F2B90F", "대기"],
  ];

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 5, padding: "7px 10px", border: `1px solid ${C.line2}`, borderRadius: 10, background: "#FAFBFC" }}>
      <div style={{ fontSize: 13.5, fontWeight: 900, color: verdict.color, whiteSpace: "normal" }}>{verdict.text}</div>
      {c.t > 0 ? (
        // 이송이 확정되면 병원 응답 대기 정보(요청 후 경과·판단 대기 수·자동 확장)는 더 이상 의미가 없다 — 확정 이후 상황만 보여준다
        <div style={{ display: "flex", flexWrap: "wrap", gap: "2px 10px", fontSize: 11.5, color: C.sub, whiteSpace: "normal" }}>
          {confirmedAt > 0 && <span>확정 후 <b style={{ color: C.ink2 }}>{fmtSpan(now - confirmedAt)}</b></span>}
          <span>요청 {total}곳 중 수용 승인 <b style={{ color: C.ink2 }}>{c.t + c.a}곳</b></span>
        </div>
      ) : inc.matched && total > 0 && (
        <>
          <div role="img" aria-label={`요청 ${total}곳 · 승인 ${c.t + c.a} · 불가 ${c.r} · 대기 ${c.w}`} style={{ display: "flex", height: 16, borderRadius: 8, overflow: "hidden", background: C.bg }}>
            {segs.map(([n, color, label]) =>
              n > 0 ? (
                <div key={label} style={{ flex: `${n} 0 0`, minWidth: 0, background: color, color: "#fff", fontSize: 10.5, fontWeight: 700, display: "flex", alignItems: "center", justifyContent: "center", whiteSpace: "nowrap" }}>
                  {n >= 2 || total <= 3 ? `${label} ${n}` : n}
                </div>
              ) : null,
            )}
          </div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: "2px 10px", fontSize: 11.5, color: C.sub, whiteSpace: "normal" }}>
            <span>요청 후 <b style={{ color: C.ink2 }}>{fmtSpan(now - requestedAt)}</b></span>
            <span>{lastResp ? <>마지막 응답 <b style={{ color: C.ink2 }}>{fmtSpan(now - lastResp)} 전</b></> : "아직 응답 없음"}</span>
            {inc.zoneExpandAt != null && (
              <span style={{ color: "#C75B00", fontWeight: 700 }}>다음 자동 확장 {Math.max(0, Math.ceil((inc.zoneExpandAt - now) / 1000))}초 뒤</span>
            )}
            {inc.zoneExpandAt == null && inc.zonePausedLeft != null && <span style={{ color: C.muted, fontWeight: 700 }}>자동 확장 ⏸ {inc.zonePausedLeft}초</span>}
          </div>
        </>
      )}
    </div>
  );
}
