import { css } from "styled-system/css";
import { severityBadge } from "styled-system/recipes";
import { Panel } from "@/components/layout/Panel";
import { Tag } from "@/components/hospital/Tag";
import { ApprovalActions } from "@/components/panels/ApprovalActions";
import type {
  ApprovalAction,
  CallSummaryMessage,
  HospitalCapacitySnapshot,
  Severity,
  VitalsMessage,
} from "@/types/dashboard";

const SEVERITY_RISK_LABEL: Record<Severity, string> = {
  high: "중증 의심",
  medium: "중등도 의심",
  low: "경증 의심",
};

const deptChipStyle = css({
  display: "inline-flex",
  alignItems: "center",
  fontSize: "xs",
  fontWeight: "semibold",
  color: "navy",
  backgroundColor: "navySoft",
  paddingX: "2.5",
  paddingY: "1",
  borderRadius: "chip",
});

const kvDt = css({ color: "ink", fontSize: "xs" });
const kvDd = css({ fontWeight: "medium", fontSize: "sm" });

export function SummaryCapacityPanel({
  data,
  vitals,
  capacity,
  hospitalId,
  onAction,
}: {
  data: CallSummaryMessage | null;
  vitals: VitalsMessage | null;
  capacity: HospitalCapacitySnapshot | null;
  hospitalId: string;
  onAction: (action: ApprovalAction) => void;
}) {
  if (!data) {
    return (
      <Panel title="통화 요약 · 구조화" badge={<Tag source="ai">sLLM · KM-BERT</Tag>}>
        <p className={css({ color: "ink", fontSize: "sm" })}>수신 대기 중...</p>
      </Panel>
    );
  }

  const { summary } = data;

  return (
    <Panel
      title="통화 요약 · 구조화"
      subtitle="실시간 음성 필터링 → 항목 추출"
      badge={<Tag source="ai">sLLM · KM-BERT</Tag>}
    >
      <dl
        className={css({
          display: "grid",
          gridTemplateColumns: "74px 1fr",
          gap: "2.5 3",
        })}
      >
        <dt className={kvDt}>환자</dt>
        <dd className={kvDd}>{summary.patient}</dd>
        <dt className={kvDt}>기전</dt>
        <dd className={kvDd}>{summary.mechanism}</dd>
        <dt className={kvDt}>증상</dt>
        <dd className={kvDd}>{summary.symptoms.join(", ")}</dd>
        <dt className={kvDt}>바이탈</dt>
        <dd className={kvDd}>
          {vitals
            ? `BP ${vitals.vitals.bp_systolic}/${vitals.vitals.bp_diastolic} · SpO₂ ${vitals.vitals.spo2}%`
            : "수신 대기 중"}
        </dd>
        <dt className={kvDt}>처치</dt>
        <dd className={kvDd}>{summary.treatment.join(", ")}</dd>
      </dl>

      <div className={css({ display: "flex", gap: "1.5", flexWrap: "wrap", marginTop: "3" })}>
        <span className={severityBadge({ severity: summary.severity_tag })}>
          {SEVERITY_RISK_LABEL[summary.severity_tag]} · {summary.mechanism}
        </span>
        {summary.required_department && (
          <span className={deptChipStyle}>필요 진료과 · {summary.required_department}</span>
        )}
      </div>

      <div
        className={css({
          marginTop: "3",
          padding: "2.5 3",
          backgroundColor: "surfaceSub",
          borderWidth: "1px",
          borderColor: "line",
          borderRadius: "field",
        })}
      >
        <div className={css({ fontSize: "xs", color: "ink", marginBottom: "1.5" })}>
          본원 수용 조건 자동 대조
        </div>
        {capacity ? (
          <div className={css({ display: "flex", flexDirection: "column", gap: "0.5" })}>
            <div className={css({ display: "flex", justifyContent: "space-between", fontSize: "sm", paddingY: "0.5" })}>
              <span>필요 진료과 당직</span>
              <span
                className={css({
                  fontWeight: "semibold",
                  color: capacity.specialist_on_call ? "mint" : "coral",
                })}
              >
                {capacity.specialist_on_call ? "가능" : "불가"}
              </span>
            </div>
            <div className={css({ display: "flex", justifyContent: "space-between", fontSize: "sm", paddingY: "0.5" })}>
              <span>응급 병상</span>
              <span className={css({ fontWeight: "semibold", color: "mint" })}>
                {capacity.beds_available}석 가용
              </span>
            </div>
            <div className={css({ display: "flex", justifyContent: "space-between", fontSize: "sm", paddingY: "0.5" })}>
              <span>수술실</span>
              <span
                className={css({
                  fontWeight: "semibold",
                  color: capacity.or_available ? "mint" : "coral",
                })}
              >
                {capacity.or_available
                  ? "가능"
                  : `${capacity.or_available_in_min ?? "?"}분 후 가능`}
              </span>
            </div>
          </div>
        ) : (
          <p className={css({ fontSize: "sm", color: "ink" })}>대조 중...</p>
        )}
      </div>

      <div className={css({ marginTop: "3.5" })}>
        <ApprovalActions role="hospital" hospitalId={hospitalId} onAction={onAction} />
        <p className={css({ marginTop: "2", fontSize: "xs", color: "ink", textAlign: "center" })}>
          이송 여부는 구급대원이 최종 결정합니다
        </p>
      </div>
    </Panel>
  );
}
