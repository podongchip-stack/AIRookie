import { css } from "styled-system/css";
import { Panel } from "@/components/layout/Panel";
import { Tag } from "@/components/hospital/Tag";
import { ApprovalActions } from "@/components/panels/ApprovalActions";
import type { ApprovalAction, HospitalCandidate } from "@/types/dashboard";

// hub가 병원별로 넘겨주는 실시간 가용 병상 수(availableBedCount)만 대조한다.
// specialist_on_call/or_available은 hub 스키마에 없는 필드라 더 이상 표시하지 않는다
// (feature/info 담당자 참고사항: 바이탈과 마찬가지로 정식 스키마가 확정되기 전까지는
// hub가 실제로 보내는 값만 신뢰한다).
export function SummaryCapacityPanel({
  hospital,
  hospitalId,
  onAction,
}: {
  hospital: HospitalCandidate | null;
  hospitalId: string;
  onAction: (action: ApprovalAction) => void;
}) {
  if (!hospital) {
    return (
      <Panel title="본원 수용 조건 자동 대조" badge={<Tag source="rule">hv1 · hvec · hv2</Tag>}>
        <p className={css({ color: "ink", fontSize: "sm" })}>수신 대기 중...</p>
      </Panel>
    );
  }

  return (
    <Panel
      title="본원 수용 조건 자동 대조"
      subtitle="hub 매칭 결과와 실시간 병상 대조"
      badge={<Tag source="rule">hv1 · hvec · hv2</Tag>}
    >
      <div
        className={css({
          padding: "2.5 3",
          backgroundColor: "surfaceSub",
          borderWidth: "1px",
          borderColor: "line",
          borderRadius: "field",
        })}
      >
        <div className={css({ display: "flex", justifyContent: "space-between", fontSize: "sm", paddingY: "0.5" })}>
          <span className={css({ color: "ink" })}>필요 진료과</span>
          <span className={css({ fontWeight: "semibold", color: "ink" })}>
            {hospital.specialtyMatch.department}
          </span>
        </div>
        <div className={css({ display: "flex", justifyContent: "space-between", fontSize: "sm", paddingY: "0.5" })}>
          <span className={css({ color: "ink" })}>응급 병상</span>
          <span
            className={css({
              fontWeight: "semibold",
              color: hospital.availableBedCount > 0 ? "mint" : "coral",
            })}
          >
            {hospital.availableBedCount > 0 ? `${hospital.availableBedCount}석 가용` : "가용 병상 없음"}
          </span>
        </div>
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
