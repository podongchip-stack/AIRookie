"use client";

import { useEffect, useState } from "react";
import { liveBedReliability, formatDeclarationAge } from "@/lib/bedReliability";
import { HD } from "@/components/hospital/hospital-design";
import type { HospitalSelfInfo } from "@/types/dashboard";

// hub가 identify 직후·info 30분 갱신·정보 확인 직후에 보내주는 "귀원 정보
// 현황"(2026-09-29). 목적은 데이터 공급자 피드백 루프다 — E-Gen 포털에는
// "당신 정보가 얼마나 낡았는지"를 병원에게 보여주는 화면이 없어서 수년 묵은
// 값이 방치된다(실측: 전국 가용병상 1위가 2,457일 묵은 값). 여기서 병원이
// 자기 신선도를 보고 "현재 정보가 맞습니다"를 누르면, 그 확인이 hub의 조건부
// 생존 갱신(S(a)/S(u))으로 이어져 구급대 화면의 신뢰도가 즉시 되올라간다 —
// 값이 그대로여도 "방금 사람이 확인한 값"임을 시스템이 알게 되는 유일한 경로.
// 2026-10-04: 디자인 시안대로 두 줄(현황 / 신뢰도·신고·확인 버튼)로 정리.

const BED_FIELD_LABEL: Record<string, string> = {
  hvoc: "수술실",
  hvicc: "중환자실",
  hvgc: "입원실",
  hv28: "소아",
};

function Item({ label, children, grow }: { label: string; children: React.ReactNode; grow?: boolean }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 1, minWidth: 0, ...(grow ? { flex: "1 1 240px" } : {}) }}>
      <span style={{ fontSize: 11.5, color: HD.sub }}>{label}</span>
      {children}
    </div>
  );
}

const valueStyle: React.CSSProperties = { fontSize: 13.5, fontWeight: 700, color: HD.navy };
const bigStyle: React.CSSProperties = { fontSize: 15, fontWeight: 700, color: HD.navy, lineHeight: 1.3 };

export function HospitalSelfInfoPanel({
  selfInfo,
  onConfirm,
}: {
  selfInfo: HospitalSelfInfo;
  onConfirm: () => void;
}) {
  // 신뢰도 감쇠를 초 단위로 그린다 — 구급차 쪽 칩과 같은 장치.
  const [nowMs, setNowMs] = useState(() => Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNowMs(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);

  const br = selfInfo.bedReliability ?? null;
  const live = br ? liveBedReliability(br, nowMs) : null;
  const confirmed = br?.confirmedAgeSec != null;
  // 확인 시각 = 값 탄생 + 확인 시점 나이 → "N분 전 확인" 표시용.
  const confirmedAgoMin =
    confirmed && br?.bornAt
      ? Math.max(Math.round((nowMs - (Date.parse(br.bornAt) + (br.confirmedAgeSec ?? 0) * 1000)) / 60000), 0)
      : null;

  const declaredGroups = Object.entries(selfInfo.severeDeclarations?.groups ?? {});
  const oldest = declaredGroups.reduce<{ ageSec: number; ageIsMin: boolean } | null>((acc, [, d]) => {
    const ageSec = Math.max((nowMs - Date.parse(d.bornAt)) / 1000, 0);
    return acc === null || ageSec > acc.ageSec ? { ageSec, ageIsMin: d.ageIsMin } : acc;
  }, null);
  const authorityPct = live ? Math.round(live.authority * 100) : null;
  const typeEntries = Object.entries(selfInfo.bedReliabilityByType ?? {});
  const specialties = selfInfo.specialties ?? [];

  return (
    <section
      style={{
        flex: "none", background: "#FFFFFF", borderRadius: 14, border: `1px solid ${HD.line}`, padding: "8px 16px",
        display: "flex", flexDirection: "column", gap: 6,
      }}
    >
      <div style={{ display: "flex", flexWrap: "wrap", gap: "6px 30px", alignItems: "flex-end" }}>
        <Item label="본원 정보 현황">
          <span style={{ display: "inline-flex", alignItems: "center", gap: 7, ...valueStyle }}>
            {selfInfo.name}
            <span style={{ fontSize: 10.5, fontWeight: 500, color: HD.ink3, background: HD.chip, borderRadius: 999, padding: "2px 8px" }}>E-Gen 신고 기준</span>
          </span>
        </Item>
        {selfInfo.emergencyLevel && (
          <Item label="본원 지정">
            <span style={valueStyle}>{selfInfo.emergencyLevel}</span>
          </Item>
        )}
        <Item label="응급실 병상">
          <span style={bigStyle}>
            {selfInfo.bedCountUnknown ? "미상" : `${selfInfo.availableBedCount}석`}
            {(selfInfo.inFlightCount ?? 0) > 0 ? ` · 이송 중 ${selfInfo.inFlightCount}건` : ""}
          </span>
        </Item>
        {authorityPct != null && (
          <Item label="병상 정보 신뢰도 (AI)">
            <span style={{ ...bigStyle, color: authorityPct >= 80 ? HD.green : authorityPct >= 50 ? HD.orange : HD.red }}>
              {authorityPct}%
              {confirmed ? <span style={{ fontSize: 11.5, fontWeight: 500, color: HD.green }}> ✓ {confirmedAgoMin}분 전 확인</span> : null}
            </span>
          </Item>
        )}
        {specialties.length > 0 && (
          <Item label={`수용 분야 (진료과 ${specialties.length}개)`} grow>
            <span style={{ ...valueStyle, overflow: "hidden", textOverflow: "ellipsis" }}>
              {specialties.slice(0, 4).map((s) => s.department).join(" · ")}
              {specialties.length > 4 ? ` 외 ${specialties.length - 4}` : ""}
            </span>
          </Item>
        )}
      </div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: "6px 30px", alignItems: "flex-end", borderTop: `1px solid ${HD.line}`, paddingTop: 6 }}>
        {typeEntries.length > 0 && (
          <Item label="수술실·입원실 신뢰도 (AI)">
            <span style={valueStyle}>
              {typeEntries
                .map(([field, typeBr]) => `${BED_FIELD_LABEL[field] ?? field} ${Math.round(liveBedReliability(typeBr, nowMs).authority * 100)}%`)
                .join(" · ")}
            </span>
          </Item>
        )}
        {declaredGroups.length > 0 && oldest && (
          <Item label="중증질환 수용 신고">
            <span style={valueStyle}>
              {declaredGroups.length}개 질환군 · 가장 오래된 것 {formatDeclarationAge(oldest.ageSec, oldest.ageIsMin)}
            </span>
          </Item>
        )}
        <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: "6px 12px", marginLeft: "auto" }}>
          <span style={{ fontSize: 11.5, color: HD.muted }}>확인하면 구급대 화면의 신뢰도에 즉시 반영됩니다</span>
          <button
            type="button"
            onClick={onConfirm}
            style={{
              minHeight: 36, padding: "0 15px", borderRadius: 999, border: `1.5px solid ${HD.green}`, background: "#FFFFFF",
              color: HD.green, fontSize: 13, fontWeight: 700, fontFamily: "inherit", cursor: "pointer",
            }}
          >
            현재 정보가 맞습니다
          </button>
        </div>
      </div>
    </section>
  );
}
