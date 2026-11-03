"use client";

import { useEffect, useState } from "react";
import { C, GLASS } from "@/lib/control-map";

// 병원 거절 사유 집계 모달(2026-11-01). 집계는 info 거절 로그 수신구가 만들고 hub(/rejection-stats)가 중계한다.
// 무응답은 수용 능력이 아니라 채널 정보라 거절 사유와 섞지 않고 따로 보인다.
interface Stats {
  days: number;
  total: number;
  noResponse: number;
  byReason: { code: string; axis: string; desc: string; count: number }[];
  topHospitals: { hospitalId: string; name: string; count: number }[];
}

const AXIS_LABEL: Record<string, string> = { structural: "구조적", periodic: "주기적", momentary: "순간적", patient: "환자 요인", unknown: "미분류" };
const DAYS = [7, 30, 365] as const;

export function RejectionStatsModal({ onClose }: { onClose: () => void }) {
  const [days, setDays] = useState<number>(30);
  const [data, setData] = useState<Stats | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    const httpUrl = process.env.NEXT_PUBLIC_HUB_HTTP_URL;
    if (!httpUrl) { setError("hub 주소가 없어 불러올 수 없습니다(목데이터 모드)"); return; }
    const ctl = new AbortController();
    setData(null); setError("");
    fetch(`${httpUrl.replace(/\/$/, "")}/rejection-stats?days=${days}`, { signal: ctl.signal })
      .then(async (r) => { const b = await r.json(); if (!r.ok) throw new Error(b.error ?? `조회 실패 (${r.status})`); setData(b as Stats); })
      .catch((e) => { if (e.name !== "AbortError") setError(String(e.message ?? e)); });
    return () => ctl.abort();
  }, [days]);

  const max = Math.max(1, ...(data?.byReason.map((r) => r.count) ?? [1]));
  return (
    <div role="dialog" aria-modal="true" aria-label="거절 사유 통계" style={{ position: "absolute", inset: 0, zIndex: 300, background: "rgba(28,31,42,.32)", backdropFilter: "blur(6px)", display: "flex", alignItems: "center", justifyContent: "center" }}>
      <button type="button" aria-label="닫기" onClick={onClose} style={{ position: "absolute", inset: 0, border: 0, background: "transparent", cursor: "default" }} />
      <div style={{ position: "relative", width: 640, maxHeight: "calc(100% - 48px)", maxWidth: "calc(100% - 48px)", background: GLASS.solid, border: GLASS.border, borderRadius: GLASS.radius, boxShadow: "0 24px 60px rgba(91,75,138,.28)", fontFamily: GLASS.font, display: "flex", flexDirection: "column", overflow: "hidden" }}>
        <div style={{ flex: "none", display: "flex", alignItems: "center", gap: 10, padding: "16px 22px", borderBottom: `1px solid ${C.line2}` }}>
          <div style={{ fontSize: 18, fontWeight: 900, color: C.navy }}>병원 거절 사유</div>
          {DAYS.map((d) => (
            <button key={d} type="button" onClick={() => setDays(d)} style={{ fontFamily: "inherit", fontSize: 12, fontWeight: 700, border: `1px solid ${days === d ? C.navy : C.line}`, background: days === d ? C.navy : "#fff", color: days === d ? "#fff" : C.ink3, borderRadius: 6, padding: "2px 10px", cursor: "pointer" }}>
              {d === 365 ? "전체" : `${d}일`}
            </button>
          ))}
          <div style={{ flex: 1 }} />
          <button type="button" onClick={onClose} style={{ fontFamily: "inherit", fontSize: 13, color: C.ink3, background: "#fff", border: `1px solid ${C.line}`, borderRadius: 4, padding: "5px 12px", cursor: "pointer" }}>닫기 ✕</button>
        </div>
        <div style={{ padding: "16px 22px", overflowY: "auto", display: "flex", flexDirection: "column", gap: 14 }}>
          {error && <div style={{ fontSize: 13, color: "#B3261E" }}>{error}</div>}
          {!error && !data && <div style={{ fontSize: 13, color: C.sub }}>불러오는 중…</div>}
          {data && (
            <>
              <div style={{ fontSize: 13, color: C.ink2 }}>
                병원이 직접 거절한 {data.total}건 · 무응답 {data.noResponse}건(채널 문제라 사유와 따로 셉니다)
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
                {data.byReason.map((r) => (
                  <div key={r.code} style={{ display: "grid", gridTemplateColumns: "150px 1fr 36px", alignItems: "center", gap: 8, fontSize: 12.5, color: C.navy }}>
                    <span title={r.code}>{r.desc || r.code} <span style={{ color: C.sub, fontSize: 11 }}>· {AXIS_LABEL[r.axis] ?? r.axis}</span></span>
                    <span style={{ height: 10, background: C.bg, borderRadius: 3 }}>
                      <span style={{ display: "block", height: "100%", width: `${(r.count / max) * 100}%`, background: r.axis === "structural" ? "#B3261E" : "#1F4E9C", borderRadius: 3 }} />
                    </span>
                    <span style={{ textAlign: "right", fontWeight: 700 }}>{r.count}</span>
                  </div>
                ))}
                {data.byReason.length === 0 && <div style={{ fontSize: 13, color: C.sub }}>이 기간 거절 기록이 없습니다.</div>}
              </div>
              {data.topHospitals.length > 0 && (
                <div>
                  <div style={{ fontSize: 12.5, fontWeight: 700, color: C.navy, marginBottom: 4 }}>거절이 잦은 병원</div>
                  {data.topHospitals.map((h) => (
                    <div key={h.hospitalId} style={{ display: "flex", justifyContent: "space-between", fontSize: 12.5, color: C.ink2, padding: "2px 0" }}>
                      <span>{h.name}</span><span style={{ fontWeight: 700 }}>{h.count}건</span>
                    </div>
                  ))}
                </div>
              )}
              <div style={{ fontSize: 11, color: C.sub }}>시연·테스트로 쌓인 기록이 섞여 있을 수 있어 운영 통계로 읽으면 안 됩니다.</div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
