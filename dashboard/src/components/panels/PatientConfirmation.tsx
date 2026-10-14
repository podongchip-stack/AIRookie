"use client";

import type { OverrideRecord, PatientInfo } from "@/types/dashboard";

// 구급대원 확인·수정(Override, 2026-10-13). 통화 요약은 끝나자마자 병원에 가고(AI 요약 · 구급대원 확인 전), 구급대원이
// 확인·수정하면 hub가 갱신본을 다시 보낸다. 병원 수용 요청 카드와 구급차 통화 요약 카드가 같은 칩·상자를 쓴다.

const FIELD_LABEL: Record<OverrideRecord["field"], string> = {
  expectedDiagnosis: "예상 병명",
  injuryStatus: "증상",
  ktasLevel: "KTAS",
  requiredDepartment: "필요 진료과",
  chiefComplaint: "주 호소",
};

function show(value: OverrideRecord["ai"]): string {
  if (value == null || value === "") return "없음";
  return Array.isArray(value) ? value.join(", ") || "없음" : String(value);
}

function hhmm(iso?: string | null): string {
  const t = iso ? Date.parse(iso) : NaN;
  return Number.isNaN(t) ? "" : new Date(t).toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit" });
}

/** "AI 요약 · 구급대원 확인 전" / "구급대원 확인 hh:mm" 칩. 구버전 hub(필드 없음)면 아무것도 안 그린다. */
export function ConfirmationChip({ patientInfo }: { patientInfo: PatientInfo | null | undefined }) {
  if (!patientInfo?.confirmedBy) return null;
  const confirmed = patientInfo.confirmedBy === "paramedic";
  return (
    <span
      style={{
        fontSize: 10.5, fontWeight: 700, borderRadius: 999, padding: "2px 8px", whiteSpace: "nowrap",
        color: confirmed ? "#168A55" : "#C75B00", background: confirmed ? "#E6F4EC" : "#FFF1E0",
      }}
      title={confirmed
        ? "구급대원이 AI 요약을 확인했습니다. 고친 칸이 있으면 아래에 표시됩니다."
        : "AI가 통화에서 정리한 요약입니다. 구급대원이 아직 확인하지 않았습니다."}
    >
      {confirmed ? `✓ 구급대원 확인 ${hhmm(patientInfo.confirmedAt)}` : "AI 요약 · 구급대원 확인 전"}
    </span>
  );
}

/** 구급대원이 고친 칸이 있으면 "환자 정보 변경" 상자(AI 값 → 구급대원 값). 없으면 null. */
export function OverrideChangesBox({ patientInfo }: { patientInfo: PatientInfo | null | undefined }) {
  const records = patientInfo?.overrides ?? [];
  if (patientInfo?.confirmedBy !== "paramedic" || records.length === 0) return null;
  const ktas = records.find((r) => r.field === "ktasLevel");
  const worse = ktas != null && typeof ktas.ai === "number" && typeof ktas.value === "number" && ktas.value < ktas.ai;
  return (
    <div
      style={{
        display: "flex", flexDirection: "column", gap: 3, borderRadius: 10, padding: "8px 12px", whiteSpace: "normal",
        background: worse ? "#FDECEA" : "#E8EEF8", border: `1px solid ${worse ? "#F2B8B3" : "#C9D6EC"}`,
      }}
    >
      <span style={{ fontSize: 12.5, fontWeight: 700, color: worse ? "#D93025" : "#1F4E9C" }}>
        ✎ 구급대원이 환자 정보를 고쳤습니다{worse ? " · 중증도 상향" : ""}
      </span>
      {records.map((r) => (
        <span key={r.field} style={{ fontSize: 12, color: "#4A5565" }}>
          {FIELD_LABEL[r.field]} <s style={{ color: "#7A8594" }}>{show(r.ai)}</s> → <b style={{ color: "#14213D" }}>{show(r.value)}</b>
        </span>
      ))}
    </div>
  );
}
