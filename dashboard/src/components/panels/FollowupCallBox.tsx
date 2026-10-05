"use client";

import type { PatientInfo, Severity, Vital } from "@/types/dashboard";

// 이송 중 2차(추가) 통화로 갱신된 환자 정보(2026-10-05) — 직전 통화와 비교해 무엇이 바뀌었는지 한 상자로 보여준다.
// 병원 대시보드 수용 요청 카드와 구급차 대시보드 이송 중 모니터링이 같은 상자를 쓴다. 통화 요약은 AI 처리 결과
// (STT·MF_BERT)이고, 바뀐 항목 계산(직전 요약과 비교)은 규칙이다.

const SEV_LABEL: Record<Severity, string> = { high: "중증 의심", medium: "중등도 의심", low: "경증 의심" };

function bp(v?: Vital | null): string | null {
  if (!v || (v.sbp == null && v.dbp == null)) return null;
  return `${v.sbp ?? "?"}/${v.dbp ?? "?"}`;
}

function change(label: string, before: string | number | null | undefined, after: string | number | null | undefined): string | null {
  if (after == null || after === "") return null;
  if (before == null || before === "") return `${label} ${after}`;
  return String(before) === String(after) ? null : `${label} ${before} → ${after}`;
}

/** 2차 이상 통화면 { 회차, 갱신 시각, 바뀐 항목들 }, 첫 통화면 null */
export function followupDelta(p: PatientInfo | null | undefined) {
  const round = p?.callRound ?? 1;
  const prev = p?.previousCalls?.[p.previousCalls.length - 1];
  if (!p || round < 2 || !prev) return null;
  const now = p.vitals?.[p.vitals.length - 1];
  const before = prev.vitals?.[prev.vitals.length - 1];
  const items = [
    change("KTAS", prev.ktasLevel, p.ktasLevel),
    prev.severityTag !== p.severityTag ? `${SEV_LABEL[prev.severityTag]} → ${SEV_LABEL[p.severityTag]}` : null,
    change("혈압", bp(before), bp(now)),
    change("맥박", before?.hr, now?.hr),
    change("호흡", before?.rr, now?.rr),
    change("SpO₂", before?.spo2 != null ? `${before.spo2}%` : null, now?.spo2 != null ? `${now.spo2}%` : null),
    change("의식", prev.consciousness, p.consciousness),
  ].filter((x): x is string => x != null);
  return { round, at: prev.receivedAt, items, diagnosis: p.expectedDiagnosis };
}

export function FollowupCallBox({ patientInfo, compact = false }: { patientInfo: PatientInfo | null | undefined; compact?: boolean }) {
  const delta = followupDelta(patientInfo);
  if (!delta) return null;
  const time = (() => {
    const t = Date.parse(delta.at);
    return Number.isNaN(t) ? "" : new Date(t).toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit" });
  })();
  return (
    <div
      style={{
        display: "flex", flexDirection: "column", gap: 3, background: "#FFF1E0", border: "1px solid #F3C99A",
        borderRadius: 10, padding: compact ? "6px 10px" : "8px 12px", whiteSpace: "normal",
      }}
    >
      <div style={{ display: "flex", flexWrap: "wrap", alignItems: "baseline", gap: "2px 8px" }}>
        <span style={{ fontSize: 12.5, fontWeight: 700, color: "#C75B00" }}>📞 이송 중 {delta.round}차 통화로 갱신</span>
        {time && <span style={{ fontSize: 11, color: "#8A6A4A" }}>{time}</span>}
        <span style={{ fontSize: 10.5, color: "#1F4E9C", background: "#E8EEF8", borderRadius: 999, padding: "1px 7px" }}>AI 구조화</span>
      </div>
      <span style={{ fontSize: 12.5, color: "#14213D", fontWeight: 700 }}>{delta.diagnosis}</span>
      {delta.items.length > 0 ? (
        <span style={{ fontSize: 12, color: "#4A5565" }}>바뀐 점 · {delta.items.join(" · ")}</span>
      ) : (
        <span style={{ fontSize: 12, color: "#4A5565" }}>직전 통화와 활력징후·중증도 변화 없음</span>
      )}
    </div>
  );
}
