import { css } from "styled-system/css";
import { severityBadge } from "styled-system/recipes";
import { Panel } from "@/components/layout/Panel";
import { Tag } from "@/components/hospital/Tag";
import { ApprovalActions } from "@/components/panels/ApprovalActions";
import type { ApprovalAction, HospitalCandidate, PatientInfo, Severity } from "@/types/dashboard";

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

// hub가 하나의 사건(voice의 patientInfo + 이 병원의 후보 정보)으로 묶어 보내는 데이터를
// "진료과 매칭 근거"와 "수용 판단"으로 화면만 쪼개 보여주던 걸 하나로 합쳤다 — 같은
// 사건 정보인데 패널 두 개로 나뉘어 있는 게 오히려 불편하다는 판단(2026-08-09).
// 참고: hub 스키마 자체가 아직 사건(case) 하나만 모델링하고 있어서(hospitals[]가
// 병원 후보 리스트일 뿐 사건 목록은 아님), 여러 구급차의 사건을 동시에 다루려면
// hub 쪽에 caseId 스키마가 먼저 확정돼야 한다 — 그 전까지는 이 병원 대시보드도
// "사건 하나" 기준으로 둔다.
export function CaseMatchPanel({
  patientInfo,
  hospital,
  hospitalId,
  onAction,
}: {
  patientInfo: PatientInfo | null;
  hospital: HospitalCandidate | null;
  hospitalId: string;
  onAction: (action: ApprovalAction) => void;
}) {
  if (!patientInfo) {
    return (
      <Panel title="예상 병명 · 수용 판단" badge={<Tag source="ai">임베딩 매칭</Tag>}>
        <p className={css({ color: "ink", fontSize: "sm" })}>수신 대기 중...</p>
      </Panel>
    );
  }

  return (
    <Panel
      title="구급차 수용 요청 리스트"
      subtitle="실시간 환자 정보 요약"
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

      {hospital && (
        <div className={css({ marginTop: "auto" })}>
          <ApprovalActions role="hospital" hospitalId={hospitalId} onAction={onAction} />
          <p className={css({ marginTop: "2", fontSize: "xs", color: "ink", textAlign: "center" })}>
            이송 여부는 구급대원이 최종 결정합니다
          </p>
        </div>
      )}
    </Panel>
  );
}
