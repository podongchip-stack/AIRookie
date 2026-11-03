"use client";

import type { DispatcherRequest } from "@/types/dashboard";

// 상황실 → 병원 알림 띠(2026-11-04). 두 가지다:
// - dispatcher_request: 상황실이 이 사건의 수용 여부를 다시 확인해 달라고 요청했다(아래 카드에서 수용 / 수용 곤란 회신)
// - dispatcher_designated: 수용 회신 전인데 상황실이 이 병원을 이송 병원으로 지정했다(개정 응급의료법의 지정 통보 자리)
// 사건마다 가장 최근 것 하나만 보이고, 닫으면 이 화면에서만 숨긴다.

export function DispatcherRequestBanner({ items, dismissed, onDismiss }: {
  items: DispatcherRequest[];
  dismissed: ReadonlySet<string>;
  onDismiss: (key: string) => void;
}) {
  const latest = new Map<string, DispatcherRequest>();
  for (const it of items) if (!latest.has(it.caseId)) latest.set(it.caseId, it);
  const shown = [...latest.values()].filter((it) => !dismissed.has(`${it.type}:${it.caseId}:${it.at}`));
  if (shown.length === 0) return null;
  return (
    <div style={{ flex: "none", display: "flex", flexDirection: "column", gap: 6 }}>
      {shown.map((it) => {
        const designated = it.type === "dispatcher_designated";
        const key = `${it.type}:${it.caseId}:${it.at}`;
        const who = [it.ambulanceName, it.ktasLevel != null ? `Pre-KTAS ${it.ktasLevel}` : null, it.chiefComplaint].filter(Boolean).join(" · ");
        return (
          <div key={key} role="status" style={{
            display: "flex", alignItems: "center", gap: 12, padding: "10px 16px", borderRadius: 12,
            background: designated ? "#FDECEA" : "#F1EEFF", border: `1px solid ${designated ? "#D9434B" : "#6B5BD2"}`,
            color: designated ? "#B3261E" : "#3B2F8F", fontSize: 14, fontWeight: 700, whiteSpace: "normal",
          }}>
            <span style={{ flex: 1 }}>
              {designated ? "상황실이 귀원을 이송 병원으로 지정했습니다" : "상황실 수용 확인 요청 — 아래 요청 카드에서 수용 여부를 회신해 주세요"}
              {who && <span style={{ fontWeight: 500 }}> · {who}</span>}
            </span>
            <button type="button" onClick={() => onDismiss(key)} style={{ flex: "none", fontFamily: "inherit", fontSize: 12, border: 0, background: "transparent", color: "inherit", cursor: "pointer" }}>닫기 ✕</button>
          </div>
        );
      })}
    </div>
  );
}
