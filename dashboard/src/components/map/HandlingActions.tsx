"use client";

import { C } from "@/lib/control-map";

// 병원 문제로 이송이 막힌 사건의 조치 패널 — UI 시안. 아직 hub에 연결되지 않아 버튼은 눌리지 않는다.
// 연결 대상: 전화 확인 요청(무응답 병원 플래그) / 존 확장(WS zone_expand_now) / 대체 병원 제안·헬기 권고(hub transport_assessment)

const ACTIONS: { title: string; desc: string; hub: string }[] = [
  { title: "전화 확인 요청", desc: "응답 없는 병원에 전화 확인 우선 표시", hub: "무응답 병원 플래그" },
  { title: "존 확장 즉시 실행", desc: "기다리지 않고 다음 존 병원에 요청", hub: "zone_expand_now" },
  { title: "대체 병원 제안 확인", desc: "이송 중 상태 악화 시 hub 제안 검토", hub: "transport_assessment" },
  { title: "헬기 대기 권고 확인", desc: "대체 후보 0곳일 때 권고 확인", hub: "transport_assessment" },
];

export function HandlingActions() {
  return (
    <div style={{ border: "1px solid #1F4E9C", borderRadius: 10, background: "#F3F7FD", padding: "8px 10px", display: "flex", flexDirection: "column", gap: 6 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
        <span style={{ fontSize: 12.5, fontWeight: 700, color: "#1F4E9C" }}>처리 조치</span>
        <span style={{ fontSize: 10.5, fontWeight: 700, color: C.muted, border: `1px solid ${C.line2}`, borderRadius: 8, padding: "0 6px", lineHeight: "16px", background: "#fff" }}>시안 · hub 연결 전</span>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6 }}>
        {ACTIONS.map((a) => (
          <button
            key={a.title}
            type="button"
            disabled
            title={`hub 연결 후 동작합니다 (${a.hub})`}
            style={{ textAlign: "left", fontFamily: "inherit", border: `1px solid ${C.line2}`, borderRadius: 8, background: "#fff", padding: "6px 8px", cursor: "not-allowed", opacity: 0.85, whiteSpace: "normal" }}
          >
            <div style={{ fontSize: 12, fontWeight: 700, color: C.navy }}>{a.title}</div>
            <div style={{ marginTop: 2, fontSize: 10.5, color: C.sub, lineHeight: 1.35 }}>{a.desc}</div>
          </button>
        ))}
      </div>
    </div>
  );
}
