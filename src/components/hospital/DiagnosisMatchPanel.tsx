import { css } from "styled-system/css";
import { severityBadge } from "styled-system/recipes";
import { Panel } from "@/components/layout/Panel";
import { Tag } from "@/components/hospital/Tag";
import type { PatientInfo, Severity, SpecialtyMatch } from "@/types/dashboard";

const SEVERITY_RISK_LABEL: Record<Severity, string> = {
  high: "중증 의심",
  medium: "중등도 의심",
  low: "경증 의심",
};

const chipStyle = css({
  display: "inline-flex",
  alignItems: "center",
  fontSize: "xs",
  color: "ink",
  backgroundColor: "surfaceSub",
  borderWidth: "1px",
  borderColor: "line",
  paddingX: "2",
  paddingY: "0.5",
  borderRadius: "chip",
});

// hub는 예상 병명 ↔ 병원 진료과 매칭을 임베딩 유사도(score)로 계산해 그대로 노출한다.
// "왜 이 병원 순위인지" 구급대원·병원 양쪽이 확인할 수 있도록 점수를 막대로 시각화한다
// (hub README "설명 가능성 유지" 원칙).
export function DiagnosisMatchPanel({
  patientInfo,
  specialtyMatch,
}: {
  patientInfo: PatientInfo | null;
  specialtyMatch: SpecialtyMatch | null;
}) {
  if (!patientInfo) {
    return (
      <Panel title="예상 병명 · 진료과 매칭" badge={<Tag source="ai">임베딩 매칭</Tag>}>
        <p className={css({ color: "ink", fontSize: "sm" })}>수신 대기 중...</p>
      </Panel>
    );
  }

  const scorePercent = specialtyMatch ? Math.round(specialtyMatch.score * 100) : null;

  return (
    <Panel
      title="예상 병명 · 진료과 매칭"
      subtitle="실시간 음성 필터링 → 항목 추출"
      badge={<Tag source="ai">임베딩 매칭</Tag>}
    >
      <div className={css({ display: "flex", flexDirection: "column", gap: "1.5" })}>
        <span className={severityBadge({ severity: patientInfo.severityTag })}>
          {SEVERITY_RISK_LABEL[patientInfo.severityTag]} · {patientInfo.expectedDiagnosis}
        </span>
        <div className={css({ display: "flex", gap: "1.5", flexWrap: "wrap" })}>
          {patientInfo.injuryStatus.map((symptom) => (
            <span key={symptom} className={chipStyle}>
              {symptom}
            </span>
          ))}
        </div>
      </div>

      <div
        className={css({
          marginTop: "3.5",
          padding: "3",
          backgroundColor: "surfaceSub",
          borderWidth: "1px",
          borderColor: "line",
          borderRadius: "field",
        })}
      >
        <div className={css({ fontSize: "sm", color: "ink", marginBottom: "2", fontWeight: "semibold" })}>
          본원 진료과 적합도
        </div>
        {specialtyMatch ? (
          <>
            <div className={css({ display: "flex", justifyContent: "space-between", fontSize: "sm", marginBottom: "1" })}>
              <span className={css({ color: "ink" })}>{specialtyMatch.department}</span>
              <span className={css({ fontWeight: "semibold", color: "navy" })}>{scorePercent}%</span>
            </div>
            <div
              className={css({
                width: "100%",
                height: "1.5",
                borderRadius: "full",
                backgroundColor: "line",
                overflow: "hidden",
              })}
            >
              <div
                className={css({ height: "100%", borderRadius: "full", backgroundColor: "navy" })}
                style={{ width: `${scorePercent}%` }}
              />
            </div>
          </>
        ) : (
          <p className={css({ fontSize: "sm", color: "ink" })}>대조 중...</p>
        )}
      </div>
    </Panel>
  );
}
