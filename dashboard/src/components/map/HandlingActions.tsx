"use client";

import { useState } from "react";
import { C, type IncHospital } from "@/lib/control-map";
import type { DashboardState } from "@/types/dashboard";

const REASON_TEXT: Record<string, string> = {
  expanded: "다음 존으로 넓혀 병원에 요청했습니다",
  not_waiting: "이미 승인한 병원이 있어 넓히지 않았습니다",
  max_zone: "더 넓힐 존이 없습니다",
  paused: "시연 일시정지 중이라 처리되지 않았습니다",
  not_dispatcher: "관제 화면에서만 대행할 수 있습니다",
  no_ambulance_screen: "이송은 확정했지만 구급차 화면이 연결돼 있지 않아 알리지 못했습니다",
  refused: "확정되지 않았습니다 — 병원이 수용 승인했는지 확인하세요",
};

/** 가장 최근 개입 결과(8초 안, 이 사건)를 한 줄 문구로. 없으면 null. */
export function resultNotice(s: Pick<DashboardState, "actionResult" | "actionRefused">, caseId: string, now: number): { ok: boolean; text: string } | null {
  const r = s.actionResult, f = s.actionRefused;
  const rr = r && r.caseId === caseId && now - r.at < 8000 ? r : null;
  const ff = f && f.caseId === caseId && now - f.at < 8000 ? f : null;
  if (rr && (!ff || rr.at >= ff.at)) {
    if (rr.ok) return { ok: true, text: rr.action === "final_approval" ? "관제가 이송을 확정했습니다" : rr.action === "dispatcher_notice" ? "이송을 확정하고 구급대원 화면에 알렸습니다" : (REASON_TEXT[rr.reason ?? "expanded"] ?? "처리했습니다") };
    return { ok: false, text: REASON_TEXT[rr.reason ?? "refused"] ?? "처리되지 않았습니다" };
  }
  return ff ? { ok: false, text: REASON_TEXT[ff.reason] ?? "처리되지 않았습니다" } : null;
}

// 병원 문제로 이송이 막힌 사건의 조치 패널 — UI 시안. 아직 hub에 연결되지 않아 버튼은 눌리지 않는다.
// 존 확장 즉시 실행은 hub WS zone_expand_now에 연결됨(2026-11-01). 나머지는 아직 시안.
// 전화 확인은 응급실 번호(E-Gen dutyTel3)가 오는 병원에 tel: 링크로 연결됨. 연결 대상: 대체 병원 제안·헬기 권고(hub transport_assessment)

const ACTIONS: { title: string; desc: string; hub: string }[] = [
  { title: "존 확장 즉시 실행", desc: "기다리지 않고 다음 존 병원에 요청", hub: "zone_expand_now" },
  { title: "대체 병원 제안 확인", desc: "이송 중 상태 악화 시 hub 제안 검토", hub: "transport_assessment" },
  { title: "헬기 대기 권고 확인", desc: "대체 후보 0곳일 때 권고 확인", hub: "transport_assessment" },
];

export function HandlingActions({ onZoneExpand, approved, onDispatch, waiting, notice, dispatchOnly = false }: { dispatchOnly?: boolean; notice: { ok: boolean; text: string } | null; onZoneExpand: () => boolean; approved: IncHospital[]; onDispatch: (h: IncHospital) => void; waiting: { hospitalId: string; name: string; phone: string | null }[] }) {
  const [zoneMsg, setZoneMsg] = useState("");  // 연결이 끊겨 못 보낸 경우만 — 결과는 hub가 notice로 돌려준다
  const expand = () => setZoneMsg(onZoneExpand() ? "" : "hub 연결이 끊겨 보내지 못했습니다");
  return (
    <div style={{ border: "1px solid #1F4E9C", borderRadius: 4, background: "#F3F7FD", padding: "8px 10px", display: "flex", flexDirection: "column", gap: 6 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
        <span style={{ fontSize: 12.5, fontWeight: 700, color: "#1F4E9C" }}>처리 조치</span>
        <span style={{ fontSize: 10.5, fontWeight: 700, color: C.muted, border: `1px solid ${C.line2}`, borderRadius: 4, padding: "0 6px", lineHeight: "16px", background: "#fff" }}>일부 시안</span>
      </div>
      {(notice || zoneMsg) && (
        <div role="status" style={{ fontSize: 12, fontWeight: 700, color: zoneMsg || !notice?.ok ? "#B3261E" : "#1B7F3B" }}>{zoneMsg || notice?.text}</div>
      )}
      {!dispatchOnly && <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6 }}>
        {ACTIONS.map((a) => {
          const live = a.hub === "zone_expand_now";
          return (
            <button
              key={a.title}
              type="button"
              disabled={!live}
              onClick={live ? expand : undefined}
              title={live ? "다음 존 병원에 바로 요청합니다" : `hub 연결 후 동작합니다 (${a.hub})`}
              style={{ textAlign: "left", fontFamily: "inherit", border: `1px solid ${live ? "#1F4E9C" : C.line2}`, borderRadius: 4, background: "#fff", padding: "6px 8px", cursor: live ? "pointer" : "not-allowed", opacity: live ? 1 : 0.85, whiteSpace: "normal" }}
            >
              <div style={{ fontSize: 12, fontWeight: 700, color: C.navy }}>{a.title}</div>
              <div style={{ marginTop: 2, fontSize: 10.5, color: C.sub, lineHeight: 1.35 }}>{a.desc}</div>
            </button>
          );
        })}
      </div>}
      {!dispatchOnly && waiting.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <div style={{ fontSize: 11, fontWeight: 700, color: C.navy }}>응답 없는 병원 전화 확인</div>
          {waiting.map((h) => (
            <div key={h.hospitalId} style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12, color: C.navy }}>
              <span style={{ flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{h.name}</span>
              {h.phone ? (
                <a href={`tel:${h.phone.replace(/[^0-9+]/g, "")}`} style={{ flex: "none", fontWeight: 700, color: "#1F4E9C" }}>📞 {h.phone}</a>
              ) : (
                <span style={{ flex: "none", color: C.sub }}>번호 없음</span>
              )}
            </div>
          ))}
        </div>
      )}
      {approved.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <div style={{ fontSize: 11, fontWeight: 700, color: C.navy }}>수용 승인 병원으로 이송 확정 (관제 대행)</div>
          {approved.map((h) => (
            <button
              key={h.hospitalId}
              type="button"
              onClick={() => window.confirm(`${h.name}(으)로 이송을 확정합니다.\n구급대원 대신 관제가 승인하며 기록에 남습니다.`) && onDispatch(h)}
              style={{ textAlign: "left", fontFamily: "inherit", fontSize: 12, fontWeight: 700, color: "#fff", background: "#1F4E9C", border: 0, borderRadius: 4, padding: "6px 10px", cursor: "pointer" }}
            >
              {h.name} · {h.km.toFixed(1)}km 이송 확정
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
