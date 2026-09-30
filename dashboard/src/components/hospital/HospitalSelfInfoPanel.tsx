"use client";

import { useEffect, useState } from "react";
import { css } from "styled-system/css";
import { Tag } from "@/components/hospital/Tag";
import { mintButtonStyle } from "@/components/ui/button-styles";
import { liveBedReliability, formatDeclarationAge } from "@/lib/bedReliability";
import type { HospitalSelfInfo } from "@/types/dashboard";

// hub가 identify 직후·info 30분 갱신·정보 확인 직후에 보내주는 "귀원 정보
// 현황"(2026-09-29). 목적은 데이터 공급자 피드백 루프다 — E-Gen 포털에는
// "당신 정보가 얼마나 낡았는지"를 병원에게 보여주는 화면이 없어서 수년 묵은
// 값이 방치된다(실측: 전국 가용병상 1위가 2,457일 묵은 값). 여기서 병원이
// 자기 신선도를 보고 "현재 정보가 맞습니다"를 누르면, 그 확인이 hub의 조건부
// 생존 갱신(S(a)/S(u))으로 이어져 구급대 화면의 신뢰도가 즉시 되올라간다 —
// 값이 그대로여도 "방금 사람이 확인한 값"임을 시스템이 알게 되는 유일한 경로.

const BED_FIELD_LABEL: Record<string, string> = {
  hvoc: "수술실",
  hvicc: "중환자실",
  hvgc: "입원실",
  hv28: "소아",
};

const itemStyle = css({
  display: "flex",
  flexDirection: "column",
  gap: "0.5",
  minWidth: "0",
});

const itemLabelStyle = css({ fontSize: "xs", color: "ink3" });
const itemValueStyle = css({
  fontSize: "sm",
  fontWeight: "semibold",
  color: "ink",
  fontVariantNumeric: "tabular-nums",
});

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
      ? Math.max(
          Math.round(
            (nowMs - (Date.parse(br.bornAt) + (br.confirmedAgeSec ?? 0) * 1000)) / 60000,
          ),
          0,
        )
      : null;

  const declarations = selfInfo.severeDeclarations?.groups ?? {};
  const declaredGroups = Object.entries(declarations);
  const oldest = declaredGroups.reduce<{ ageSec: number; ageIsMin: boolean } | null>(
    (acc, [, d]) => {
      const ageSec = Math.max((nowMs - Date.parse(d.bornAt)) / 1000, 0);
      return acc === null || ageSec > acc.ageSec ? { ageSec, ageIsMin: d.ageIsMin } : acc;
    },
    null,
  );

  return (
    <section
      className={css({
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        flexWrap: "wrap",
        gap: "4",
        borderWidth: "1px",
        borderColor: "line",
        borderRadius: "panel",
        backgroundColor: "surface",
        paddingX: "4",
        paddingY: "3",
        marginBottom: "3.5",
      })}
    >
      <div className={css({ display: "flex", alignItems: "center", gap: "5", flexWrap: "wrap" })}>
        <div className={itemStyle}>
          <span className={itemLabelStyle}>본원 정보 현황</span>
          <span className={css({ fontSize: "sm", fontWeight: "semibold", color: "ink" })}>
            {selfInfo.name} <Tag source="rule">E-Gen 신고 기준</Tag>
          </span>
        </div>
        <div className={itemStyle}>
          <span className={itemLabelStyle}>응급실 병상</span>
          <span className={itemValueStyle}>
            {selfInfo.bedCountUnknown ? "미상" : `${selfInfo.availableBedCount}석`}
          </span>
        </div>
        {live && (
          <div className={itemStyle}>
            <span className={itemLabelStyle}>병상 정보 신뢰도 (AI)</span>
            <span className={itemValueStyle}>
              {Math.round(live.authority * 100)}%
              {confirmed ? ` ✓ ${confirmedAgoMin}분 전 확인` : ""}
            </span>
          </div>
        )}
        {selfInfo.bedReliabilityByType &&
          Object.keys(selfInfo.bedReliabilityByType).length > 0 && (
            <div className={itemStyle}>
              <span className={itemLabelStyle}>수술실·입원실 신뢰도 (AI)</span>
              <span className={itemValueStyle}>
                {Object.entries(selfInfo.bedReliabilityByType)
                  .map(([field, typeBr]) => {
                    const typeLive = liveBedReliability(typeBr, nowMs);
                    return `${BED_FIELD_LABEL[field] ?? field} ${Math.round(typeLive.authority * 100)}%`;
                  })
                  .join(" · ")}
              </span>
            </div>
          )}
        {declaredGroups.length > 0 && oldest && (
          <div className={itemStyle}>
            <span className={itemLabelStyle}>중증질환 수용 신고</span>
            <span className={itemValueStyle}>
              {declaredGroups.length}개 질환군 · 가장 오래된 것{" "}
              {formatDeclarationAge(oldest.ageSec, oldest.ageIsMin)}
            </span>
          </div>
        )}
      </div>

      <div className={css({ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: "1" })}>
        <button type="button" onClick={onConfirm} className={mintButtonStyle}>
          현재 정보가 맞습니다
        </button>
        <span className={css({ fontSize: "xs", color: "ink3" })}>
          확인하면 구급대 화면의 신뢰도에 즉시 반영됩니다
        </span>
      </div>
    </section>
  );
}
