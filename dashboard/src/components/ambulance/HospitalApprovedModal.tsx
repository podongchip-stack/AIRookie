"use client";

import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { AD } from "@/components/ambulance/ambulance-design";
import { formatDeclarationAge, liveBedReliability } from "@/lib/bedReliability";
import type { HospitalCandidate, ReliabilityConfidence } from "@/types/dashboard";

// 병원 수용 승인 알림(2026-10-06) — 병원(병원 대시보드·시연 콘솔)이 [승인]을 누르면 구급차 대시보드에 그 병원의 정보를
// 띄운다. 0.5초에 걸쳐 나타나 5초 머문 뒤 0.5초에 걸쳐 사라진다. [이송 승인]으로 바로 이송을 확정할 수 있고, [닫기]는
// 기다리지 않고 바로 닫는다. 표시 값은 전부 hub 매칭 결과 그대로다(병상·신고는 E-Gen 규칙, 신뢰도는 AI 확률).

const FADE_MS = 500;
const HOLD_MS = 5000;

const CONFIDENCE_LABEL: Record<ReliabilityConfidence, string> = { high: "신뢰도 높음", medium: "신뢰도 보통", low: "신뢰도 낮음" };

const pct = (p: number) => `${Math.round(p * 100)}%`;

export function HospitalApprovedModal({ hospital, onApprove, onClose }: {
  hospital: HospitalCandidate;
  onApprove: () => void;
  onClose: () => void;
}) {
  const [shown, setShown] = useState(false);
  const [nowMs, setNowMs] = useState(() => Date.now());
  const closeRef = useRef(onClose);
  useEffect(() => {
    closeRef.current = onClose;
  }, [onClose]);

  useEffect(() => {
    const raf = requestAnimationFrame(() => setShown(true));
    const fadeOut = setTimeout(() => setShown(false), FADE_MS + HOLD_MS);
    const done = setTimeout(() => closeRef.current(), FADE_MS + HOLD_MS + FADE_MS);
    const clock = setInterval(() => setNowMs(Date.now()), 1000);
    return () => {
      cancelAnimationFrame(raf);
      clearTimeout(fadeOut);
      clearTimeout(done);
      clearInterval(clock);
    };
  }, []);

  const bed = hospital.bedReliability ? liveBedReliability(hospital.bedReliability, nowMs) : null;
  const byType = (field: string) => {
    const br = hospital.bedReliabilityByType?.[field];
    return br ? pct(liveBedReliability(br, nowMs).rArrive) : "정보 없음";
  };
  const beds = hospital.bedCountUnknown
    ? "미상"
    : `${hospital.availableBedCount}석${hospital.bedDataStale ? " (1일 넘은 값)" : ""}`;
  const severe = hospital.severeFreshness;
  const rel = hospital.reliability;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={`${hospital.name} 수용 승인`}
      style={{
        position: "fixed", inset: 0, zIndex: 9000, display: "flex", alignItems: "center", justifyContent: "center",
        padding: 16, background: "rgba(20,33,61,.35)", opacity: shown ? 1 : 0, transition: `opacity ${FADE_MS}ms ease`,
      }}
    >
      <div style={{
        width: 460, maxWidth: "100%", boxSizing: "border-box", background: "#fff", borderRadius: 18, border: `2px solid ${AD.green}`,
        boxShadow: "0 20px 60px rgba(20,33,61,.3)", padding: "20px 22px", display: "flex", flexDirection: "column", gap: 14,
        transform: shown ? "translateY(0)" : "translateY(8px)", transition: `transform ${FADE_MS}ms ease`,
      }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <span style={{ alignSelf: "flex-start", fontSize: 12, fontWeight: 700, color: AD.green, background: AD.greenSoft, borderRadius: 999, padding: "3px 10px" }}>
            ✓ 병원 수용 승인
          </span>
          <span style={{ fontSize: 22, fontWeight: 900, color: AD.navy, wordBreak: "keep-all" }}>{hospital.name}</span>
          {hospital.travelMin != null && (
            <span style={{ fontSize: 13, color: AD.sub }}>도착까지 약 {Math.max(1, Math.round(hospital.travelMin))}분</span>
          )}
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 2, borderTop: `1px solid ${AD.line}`, paddingTop: 10 }}>
          <Row label="응급의료기관 지정" source="E-Gen">{hospital.emergencyLevel ?? "지정 정보 없음"}</Row>
          <Row label="응급실 병상" source="E-Gen">
            <span style={{ color: hospital.bedCountUnknown ? AD.muted : hospital.availableBedCount > 0 ? AD.green : AD.red, fontWeight: 700 }}>{beds}</span>
          </Row>
          <Row label="병상 정보 신뢰도" source="AI">
            {bed ? `지금 ${pct(bed.authority)} · 도착 시 ${pct(bed.rArrive)}` : "정보 없음"}
          </Row>
          <Row label="수술실 · 입원실 신뢰도" source="AI">수술실 {byType("hvoc")} · 입원실 {byType("hvgc")}</Row>
          <Row label="중증질환 수용 신고" source="E-Gen">
            {rel || severe ? (
              <span style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 2 }}>
                {rel && <span>{rel.group} · {CONFIDENCE_LABEL[rel.confidence]}</span>}
                {severe && (
                  <span style={{ color: severe.value === "Y" ? AD.green : AD.red, fontWeight: 700 }}>
                    {severe.value === "Y" ? "수용가능 신고" : "수용불가 신고"} · {formatDeclarationAge(severe.ageSec, severe.ageIsMin)}
                  </span>
                )}
              </span>
            ) : "해당 질환군 신고 없음"}
          </Row>
        </div>

        <div style={{ display: "flex", gap: 8 }}>
          <button
            type="button"
            onClick={onApprove}
            style={{ flex: "1 1 auto", minHeight: 48, border: "none", borderRadius: 12, background: AD.green, color: "#fff", fontSize: 16, fontWeight: 800, cursor: "pointer", fontFamily: "inherit" }}
          >
            이송 승인
          </button>
          <button
            type="button"
            onClick={onClose}
            style={{ flex: "none", minHeight: 48, padding: "0 20px", border: `1px solid ${AD.control}`, borderRadius: 12, background: "#fff", color: AD.ink3, fontSize: 15, fontWeight: 700, cursor: "pointer", fontFamily: "inherit" }}
          >
            닫기
          </button>
        </div>
      </div>
    </div>
  );
}

function Row({ label, source, children }: { label: string; source: "AI" | "E-Gen"; children: ReactNode }) {
  return (
    <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 12, padding: "6px 0", fontSize: 14 }}>
      <span style={{ flex: "none", display: "flex", alignItems: "center", gap: 6, color: AD.sub }}>
        {label}
        <span style={{ fontSize: 10.5, fontWeight: 700, borderRadius: 4, padding: "0 5px", lineHeight: "16px", color: source === "AI" ? AD.blue : AD.ink3, background: source === "AI" ? AD.blueSoft : AD.chip }}>
          {source === "AI" ? "AI" : "규칙"}
        </span>
      </span>
      <span style={{ textAlign: "right", color: AD.ink, fontWeight: 600 }}>{children}</span>
    </div>
  );
}
