import { css } from "styled-system/css";
import { hospitalStatusBadge, severityBadge } from "styled-system/recipes";
import { Panel } from "@/components/layout/Panel";
import { Tag } from "@/components/hospital/Tag";
import { ApprovalActions } from "@/components/panels/ApprovalActions";
import type { ApprovalAction, HospitalCandidate, HospitalStatus, PatientInfo, Severity } from "@/types/dashboard";

const SEVERITY_RISK_LABEL: Record<Severity, string> = {
  high: "중증 의심",
  medium: "중등도 의심",
  low: "경증 의심",
};

// 본원 관점에서의 상태 — 구급차 쪽 라벨과 문구만 다르다(예: "approved"는
// 구급차 쪽엔 "후보 등록"이지만 병원 자신에겐 "본원 승인함"이 더 명확하다).
const STATUS_LABEL: Record<HospitalStatus, string> = {
  pending: "판단 대기 중",
  approved: "본원 승인함",
  rejected: "본원 불가 처리함",
  confirmed: "이송 확정됨",
};

const chipStyle = css({
  display: "inline-flex",
  alignItems: "center",
  fontSize: "sm",
  fontWeight: "medium",
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
// 이 컴포넌트 자체는 "사건 하나"만 그린다 — 여러 사건(구급차)을 동시에 보여주는 건
// hospital/page.tsx가 이 패널을 사건 수만큼 나열하는 방식으로 처리한다(2026-08-11,
// hub의 caseId 도입에 맞춰 다중 사건 지원).
export function CaseMatchPanel({
  patientInfo,
  hospital,
  hospitalId,
  caseId,
  ambulanceName,
  onAction,
}: {
  patientInfo: PatientInfo | null;
  hospital: HospitalCandidate | null;
  hospitalId: string;
  // 여러 사건을 카드로 동시에 나열할 수 있어(hospital/page.tsx 참고), 이 카드가
  // 어느 사건 것인지 승인 액션에 실어 보내야 한다.
  caseId: string;
  // 카드가 여러 개 동시에 나열되므로(사건마다 하나씩), 어느 구급차가 보낸
  // 요청인지 카드 자체에서 구분할 수 있어야 한다(2026-08-11 요청).
  ambulanceName?: string;
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
      subtitle={ambulanceName ? `${ambulanceName} · 실시간 환자 정보 요약` : "실시간 환자 정보 요약"}
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

      {hospital ? (
        <div className={css({ marginTop: "auto" })}>
          <div className={css({ display: "flex", justifyContent: "flex-end", marginBottom: "2" })}>
            <span className={hospitalStatusBadge({ status: hospital.status })}>
              {STATUS_LABEL[hospital.status]}
            </span>
          </div>
          {hospital.status === "confirmed" ? (
            // 구급대원이 이미 이 병원으로 이송을 최종 승인한 상태다 — 병원 쪽에서
            // 뒤집을 수 있는 결정이 아니라서 버튼 대신 확정 안내만 보여준다.
            <p className={css({ fontSize: "sm", color: "mint", textAlign: "center", fontWeight: "semibold" })}>
              이 사건은 본원으로 이송이 확정됐습니다
            </p>
          ) : (
            <>
              {/* 병원의 승인/불가는 최종 결정이 아니라 후보 등록일 뿐이라(CLAUDE.md),
                  한 번 눌렀다고 버튼을 잠그지 않는다 — 병상 상황이 바뀌면 다시 눌러
                  번복할 수 있어야 한다(2026-08-11 논의). */}
              <ApprovalActions role="hospital" hospitalId={hospitalId} caseId={caseId} onAction={onAction} />
              <p className={css({ marginTop: "2", fontSize: "xs", color: "ink", textAlign: "center" })}>
                이송 여부는 구급대원이 최종 결정합니다
              </p>
            </>
          )}
        </div>
      ) : (
        // hospitalId가 이번 매칭 결과의 hospitals[] 안에 없는 경우다 — 승인 버튼을
        // 그냥 숨기면 "버튼이 안 눌린다"는 오해를 사기 쉬워서, 원인을 그대로 보여준다
        // (2026-08-10, develop 테스트에서 실제로 이 상황이 "버튼 비활성화"로 오인됐다).
        <p
          className={css({
            marginTop: "auto",
            fontSize: "xs",
            color: "coral",
            textAlign: "center",
          })}
        >
          본원(ID: {hospitalId})이 이번 사건의 후보 목록에 없습니다. 병원 ID가 hub 데이터와
          일치하는지 확인하세요.
        </p>
      )}
    </Panel>
  );
}
