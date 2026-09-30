"use client";

import { css } from "styled-system/css";
import type { PatientInfo, Vital } from "@/types/dashboard";

// voice v2(MF_BERT, 2026-09-29~)가 주는 KTAS·활력징후·의식·발생 시점(2026-10-01). 예전 voice면 이 값들이
// 없어서 아무것도 그리지 않는다. 숫자는 모델이 찾은 발화 구간을 규칙으로 읽은 값이라 AI 처리 결과다.
const VITAL_FIELDS: [keyof Vital, string, string][] = [
  ["hr", "맥박", ""],
  ["rr", "호흡", ""],
  ["bt", "체온", "℃"],
  ["spo2", "SpO₂", "%"],
  ["glucose", "혈당", ""],
];

function formatVital(vital: Vital): string {
  const parts: string[] = [];
  if (vital.sbp != null || vital.dbp != null) parts.push(`혈압 ${vital.sbp ?? "?"}/${vital.dbp ?? "?"}`);
  for (const [key, label, unit] of VITAL_FIELDS) {
    const value = vital[key];
    if (value != null) parts.push(`${label} ${value}${unit}`);
  }
  return parts.join(" · ");
}

const rowStyle = css({ display: "flex", gap: "1.5", flexWrap: "wrap", alignItems: "center", fontSize: "xs", color: "ink2" });
const ktasStyle = css({
  fontSize: "xs",
  fontWeight: "bold",
  color: "white",
  backgroundColor: "coral",
  paddingX: "2",
  paddingY: "0.5",
  borderRadius: "chip",
});

export function PatientVitals({ patientInfo }: { patientInfo: PatientInfo }) {
  const latest = patientInfo.vitals?.[patientInfo.vitals.length - 1];
  const vitalText = latest ? formatVital(latest) : "";
  const facts = [
    patientInfo.patient,
    patientInfo.consciousness && `의식 ${patientInfo.consciousness}`,
    patientInfo.onset && `발생 ${patientInfo.onset}`,
  ].filter(Boolean);
  if (patientInfo.ktasLevel == null && !vitalText && facts.length === 0) return null;
  return (
    <div className={css({ display: "flex", flexDirection: "column", gap: "1" })}>
      <div className={rowStyle}>
        {patientInfo.ktasLevel != null && <span className={ktasStyle}>KTAS {patientInfo.ktasLevel}</span>}
        {facts.map((f) => (
          <span key={f as string}>{f}</span>
        ))}
      </div>
      {vitalText && (
        <div className={rowStyle}>
          <span className={css({ fontWeight: "semibold", color: "ink" })}>활력징후</span>
          <span>{vitalText}</span>
          {(patientInfo.vitals?.length ?? 0) > 1 && <span>(측정 {patientInfo.vitals?.length}회 중 최근)</span>}
        </div>
      )}
    </div>
  );
}
