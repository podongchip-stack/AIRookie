"use client";

import { useState } from "react";
import { C, type IncHospital } from "@/lib/control-map";
import type { CaseAlternative, DashboardState } from "@/types/dashboard";

const REASON_TEXT: Record<string, string> = {
  expanded: "다음 존으로 넓혀 병원에 요청했습니다",
  not_waiting: "이미 승인한 병원이 있어 넓히지 않았습니다",
  max_zone: "더 넓힐 존이 없습니다",
  paused: "시연 일시정지 중이라 처리되지 않았습니다",
  not_dispatcher: "관제 화면에서만 대행할 수 있습니다",
  no_ambulance_screen: "이송은 확정했지만 구급차 화면이 연결돼 있지 않아 알리지 못했습니다",
  refused: "확정되지 않았습니다 — 병원이 수용 승인했는지 확인하세요",
  no_case_result: "요청 전인 사건이라 지시할 수 없습니다",
  unknown_hospital: "hub가 모르는 병원입니다",
  excluded: "이 사건에서 제외된 병원입니다(도착 후 수용 불가·철회)",
  already_confirmed: "이미 이송이 확정된 사건입니다",
  beds_full: "응급실 병상이 없는 것으로 확인된 병원입니다",
};

/** 가장 최근 개입 결과(8초 안, 이 사건)를 한 줄 문구로. 없으면 null. */
export function resultNotice(s: Pick<DashboardState, "actionResult" | "actionRefused">, caseId: string, now: number): { ok: boolean; text: string } | null {
  const r = s.actionResult, f = s.actionRefused;
  const rr = r && r.caseId === caseId && now - r.at < 8000 ? r : null;
  const ff = f && f.caseId === caseId && now - f.at < 8000 ? f : null;
  if (rr && (!ff || rr.at >= ff.at)) {
    if (rr.ok) return { ok: true, text: rr.action === "final_approval" ? "관제가 이송을 확정했습니다 — 구급대원 화면에 알렸습니다" : rr.action === "dispatcher_notice" ? "이송을 확정하고 구급대원 화면에 알렸습니다" : (REASON_TEXT[rr.reason ?? "expanded"] ?? "처리했습니다") };
    return { ok: false, text: REASON_TEXT[rr.reason ?? "refused"] ?? "처리되지 않았습니다" };
  }
  return ff ? { ok: false, text: REASON_TEXT[ff.reason] ?? "처리되지 않았습니다" } : null;
}

// 병원 문제로 이송이 막힌 사건의 조치 패널.
// 존 확장 즉시 실행은 hub WS zone_expand_now에 연결됨(2026-11-01). 대체 병원 제안 확인은 hub WS case_alternatives_request에 연결됨(2026-11-03) —
// 이미 요청한 병원을 뺀 새 후보를 규칙으로 보여 줄 뿐이고 요청은 [존 확장 즉시 실행]이 보낸다.
// 전화 확인은 응급실 번호(E-Gen dutyTel3)가 오는 병원에 tel: 링크로 연결됨.

const ACTIONS: { title: string; desc: string; hub: string }[] = [
  { title: "존 확장 즉시 실행", desc: "기다리지 않고 다음 존 병원에 요청", hub: "zone_expand_now" },
  { title: "대체 병원 제안 확인", desc: "이미 요청한 병원을 뺀 새 후보 검토", hub: "case_alternatives_request" },
];

export function HandlingActions({ onZoneExpand, onAlternatives, onDirect, alternatives, phoneOf, approved, onDispatch, waiting, notice, dispatchOnly = false }: { onAlternatives: () => boolean; onDirect: (h: CaseAlternative) => void; alternatives: { at: number; hospitals: CaseAlternative[] } | null; phoneOf: (hospitalId: string) => string | null; dispatchOnly?: boolean; notice: { ok: boolean; text: string } | null; onZoneExpand: () => boolean; approved: IncHospital[]; onDispatch: (h: IncHospital) => void; waiting: { hospitalId: string; name: string; phone: string | null }[] }) {
  const [zoneMsg, setZoneMsg] = useState("");  // 연결이 끊겨 못 보낸 경우만 — 결과는 hub가 notice로 돌려준다
  const expand = () => setZoneMsg(onZoneExpand() ? "" : "hub 연결이 끊겨 보내지 못했습니다");
  const showAlternatives = () => setZoneMsg(onAlternatives() ? "" : "hub 연결이 끊겨 제안을 받지 못했습니다");
  return (
    <div style={{ border: "1px solid #1F4E9C", borderRadius: 4, background: "#F3F7FD", padding: "8px 10px", display: "flex", flexDirection: "column", gap: 6, minWidth: 0, maxWidth: "100%", boxSizing: "border-box", overflowWrap: "anywhere", wordBreak: "keep-all" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
        <span style={{ fontSize: 12.5, fontWeight: 700, color: "#1F4E9C" }}>처리 조치</span>
        <span style={{ fontSize: 10.5, fontWeight: 700, color: C.muted, border: `1px solid ${C.line2}`, borderRadius: 4, padding: "0 6px", lineHeight: "16px", background: "#fff" }}>일부 시안</span>
      </div>
      {(notice || zoneMsg) && (
        <div role="status" style={{ fontSize: 12, fontWeight: 700, color: zoneMsg || !notice?.ok ? "#B3261E" : "#1B7F3B" }}>{zoneMsg || notice?.text}</div>
      )}
      {!dispatchOnly && <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) minmax(0, 1fr)", gap: 6 }}>
        {ACTIONS.map((a) => {
          const isAlt = a.hub === "case_alternatives_request";
          const live = a.hub === "zone_expand_now" || isAlt;
          return (
            <button
              key={a.title}
              type="button"
              disabled={!live}
              onClick={isAlt ? showAlternatives : live ? expand : undefined}
              title={isAlt ? "이미 요청한 병원을 뺀 새 후보를 보여 줍니다" : live ? "다음 존 병원에 바로 요청합니다" : `hub 연결 후 동작합니다 (${a.hub})`}
              style={{ textAlign: "left", fontFamily: "inherit", border: `1px solid ${live ? "#1F4E9C" : C.line2}`, borderRadius: 4, background: "#fff", padding: "6px 8px", cursor: live ? "pointer" : "not-allowed", opacity: live ? 1 : 0.85, whiteSpace: "normal" }}
            >
              <div style={{ fontSize: 12, fontWeight: 700, color: C.navy }}>{a.title}</div>
              <div style={{ marginTop: 2, fontSize: 10.5, color: C.sub, lineHeight: 1.35 }}>{a.desc}</div>
            </button>
          );
        })}
      </div>}
      {!dispatchOnly && alternatives && (
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <div style={{ fontSize: 11, fontWeight: 700, color: C.navy }}>대체 병원 제안</div>
          <div style={{ fontSize: 10.5, color: C.muted, lineHeight: 1.4 }}>이미 요청한 병원은 뺐습니다 · 골라서 이송 지시하거나, 존 확장으로 요청하세요</div>
          {alternatives.hospitals.length === 0 && <div style={{ fontSize: 12, color: C.sub }}>새로 요청할 만한 병원이 없습니다</div>}
          {alternatives.hospitals.map((h, i) => {
            const phone = phoneOf(h.hospitalId);
            const km = h.roadDistanceKm ?? h.distanceKm;
            const beds = h.bedCountUnknown || h.availableBedCount == null ? "병상 미상" : `응급실 ${h.availableBedCount}석`;
            return (
              <div key={h.hospitalId} style={{ background: "#fff", border: `1px solid ${C.line2}`, borderRadius: 4, padding: "5px 8px", display: "flex", flexDirection: "column", gap: 2 }}>
                <div style={{ display: "flex", alignItems: "center", flexWrap: "wrap", gap: "2px 6px", fontSize: 12, color: C.navy, minWidth: 0 }}>
                  <span style={{ flex: "none", fontWeight: 700 }}>{i + 1}</span>
                  <span style={{ flex: "1 1 120px", minWidth: 0, fontWeight: 700 }}>{h.name}</span>
                  <span style={{ flex: "none", color: C.sub }}>{h.roadDistanceKm == null ? "직선 " : ""}{km.toFixed(1)}km{h.etaMin != null ? ` · ETA ${h.etaMin}분` : ""}</span>
                </div>
                <div style={{ display: "flex", alignItems: "center", flexWrap: "wrap", gap: "2px 6px", fontSize: 11, color: C.sub, minWidth: 0 }}>
                  <span style={{ flex: "1 1 100px", minWidth: 0 }}>{[h.emergencyLevel, beds].filter(Boolean).join(" · ")}</span>
                  {phone ? <a href={`tel:${phone.replace(/[^0-9+]/g, "")}`} style={{ flex: "none", fontWeight: 700, color: "#1F4E9C" }}>📞 {phone}</a> : <span style={{ flex: "none" }}>번호 없음</span>}
                </div>
                {h.reason && <div style={{ fontSize: 10.5, color: C.muted, lineHeight: 1.35 }}>{h.reason}</div>}
                <button
                  type="button"
                  onClick={() => window.confirm(`${h.name}(으)로 이송을 지시합니다.\n병원의 수용 승인 없이 관제가 직접 확정하며, 구급대원 화면에 알리고 기록에 남습니다.\n수용 여부는 도착 후 병원이 확인합니다.`) && onDirect(h)}
                  style={{ alignSelf: "flex-start", fontFamily: "inherit", fontSize: 12, fontWeight: 700, color: "#fff", background: "#1F4E9C", border: 0, borderRadius: 4, padding: "5px 10px", cursor: "pointer" }}
                >
                  이 병원으로 이송 지시
                </button>
              </div>
            );
          })}
        </div>
      )}
      {!dispatchOnly && waiting.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <div style={{ fontSize: 11, fontWeight: 700, color: C.navy }}>응답 없는 병원 전화 확인</div>
          {waiting.map((h) => (
            <div key={h.hospitalId} style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12, color: C.navy }}>
              <span style={{ flex: 1, minWidth: 0, overflowWrap: "anywhere" }}>{h.name}</span>
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
