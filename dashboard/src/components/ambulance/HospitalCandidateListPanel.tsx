"use client";

import { css, cx } from "styled-system/css";
import { hospitalStatusBadge } from "styled-system/recipes";
import { Tag } from "@/components/hospital/Tag";
import { mintButtonStyle, primaryButtonStyle } from "@/components/ui/button-styles";
import { thinScrollbarStyle } from "@/components/ui/scrollbar-style";
import type { HospitalStatus, HubMatchResult, ReliabilityConfidence } from "@/types/dashboard";

// 공용 Panel은 height:100%만 두고 minHeight/overflow는 안 잡아서, 그리드 셀이
// 콘텐츠(병원 몇 개)만큼 계속 늘어나는 걸 막지 못했다 — maxHeight를 목록에
// 고정값으로 줘봤지만 이번엔 그 값이 실제 셀 높이보다 작아서 패널 하단에
// 빈 공간이 남았다(2026-08-11 두 번 다 확인됨). Panel을 공용으로 고치면 다른
// 패널에도 영향이 갈 수 있어서, 이 컴포넌트만 자체 마크업(같은 시각 스타일 +
// minHeight:0 + overflow:hidden)으로 바꿔 셀 높이에 정확히 맞추고, 넘치는 건
// 안쪽 <ul>이 스크롤로 흡수하게 한다.
function ListPanelShell({
  subtitle,
  children,
}: {
  subtitle?: string;
  children: React.ReactNode;
}) {
  return (
    <section
      className={css({
        display: "flex",
        flexDirection: "column",
        height: "100%",
        minHeight: "0",
        overflow: "hidden",
        borderWidth: "1px",
        borderColor: "line",
        borderRadius: "panel",
        backgroundColor: "surface",
        padding: "4",
        minWidth: "0",
      })}
    >
      <header
        className={css({
          display: "flex",
          alignItems: "flex-start",
          justifyContent: "space-between",
          gap: "2.5",
          paddingBottom: "3",
          marginBottom: "3",
          borderBottomWidth: "1px",
          borderColor: "line",
          flexShrink: "0",
        })}
      >
        <h2 className={css({ fontSize: "sm", fontWeight: "semibold", letterSpacing: "-0.01em", color: "ink" })}>
          병원 후보 리스트
          {subtitle && (
            <span className={css({ display: "block", fontSize: "xs", fontWeight: "normal", color: "ink", marginTop: "0.5" })}>
              {subtitle}
            </span>
          )}
        </h2>
        <Tag source="rule">hv1 · hvec · hv2</Tag>
      </header>
      {children}
    </section>
  );
}

const STATUS_LABEL: Record<HospitalStatus, string> = {
  pending: "판단 대기",
  approved: "후보 등록",
  rejected: "수용 불가",
  confirmed: "이송 확정",
};

// 정렬 기준(2026-08-13 변경): 1차 병상 유무 → 2차 승인 여부 → 3차 적합도.
// 거절해도 목록에서 없애지 않는다 — 병원이 "불가"였다가 병상이 나서 다시
// 받아주는 경우가 있어서, 매번 이 우선순위로 다시 정렬해두면 승인으로
// 바뀌는 순간 자동으로 위로 올라온다(2026-08-11 논의, 순위 기준만 바뀌고
// 이 원칙은 그대로 유지).
const STATUS_PRIORITY: Record<HospitalStatus, number> = {
  confirmed: 0,
  approved: 1,
  pending: 2,
  rejected: 3,
};

// 1차 기준(병상 유무)의 두 그룹. "미상"은 "확인된 만실"과 같은 그룹으로 묶지
// 않는다 — 미상은 실제로 자리가 있을 수도 있는데, 만실과 같이 맨 뒤로 밀어
// 버리면 구급대원이 그 병원을 스스로 후보에서 빼게 되어 뺑뺑이 방지 목적과
// 어긋난다(CLAUDE.md 원칙). 그래서 "병상 있음"과 "미상"을 같은 상위 그룹으로,
// "확인된 만실(0석)"만 하위 그룹으로 나눈다.
function bedAvailabilityPriority(hospital: { availableBedCount: number; bedCountUnknown: boolean }): number {
  const confirmedEmpty = !hospital.bedCountUnknown && hospital.availableBedCount <= 0;
  return confirmedEmpty ? 1 : 0;
}

const deptChipStyle = css({
  display: "inline-flex",
  alignItems: "center",
  fontSize: "xs",
  fontWeight: "semibold",
  color: "navy",
  backgroundColor: "navySoft",
  paddingX: "2",
  paddingY: "0.5",
  borderRadius: "chip",
});

const bedChipAvailableStyle = css({
  display: "inline-flex",
  alignItems: "center",
  fontSize: "xs",
  fontWeight: "semibold",
  color: "mint",
  backgroundColor: "mintSoft",
  paddingX: "2",
  paddingY: "0.5",
  borderRadius: "chip",
});

const bedChipEmptyStyle = css({
  display: "inline-flex",
  alignItems: "center",
  fontSize: "xs",
  fontWeight: "semibold",
  color: "coral",
  backgroundColor: "coralSoft",
  paddingX: "2",
  paddingY: "0.5",
  borderRadius: "chip",
});

// "확인된 만실"(coral)과는 색을 다르게 둔다 — 미상은 병원에 자리가 없다고 확정된
// 게 아니라 데이터가 아직 없는 것뿐이라, 만실과 같은 경고색으로 보이면 구급대원이
// 실제로는 받아줄 수도 있는 병원을 스스로 후보에서 빼게 된다(CLAUDE.md 참고).
const bedChipUnknownStyle = css({
  display: "inline-flex",
  alignItems: "center",
  fontSize: "xs",
  fontWeight: "semibold",
  color: "ink2",
  backgroundColor: "surfaceSub",
  paddingX: "2",
  paddingY: "0.5",
  borderRadius: "chip",
});

// info-v2(hospital_score) 신뢰도 판정 배지. severityBadge(high=coral)와 반대로
// "high confidence"는 좋은 신호라 mint를 쓴다 — 색 의미가 severity와 정반대라
// 그 recipe를 재사용하지 않고 이 패널 안에서만 쓰는 별도 칩으로 둔다.
const CONFIDENCE_CHIP_STYLE: Record<ReliabilityConfidence, string> = {
  high: css({
    display: "inline-flex",
    alignItems: "center",
    fontSize: "xs",
    fontWeight: "semibold",
    color: "mint",
    backgroundColor: "mintSoft",
    paddingX: "2",
    paddingY: "0.5",
    borderRadius: "chip",
  }),
  medium: css({
    display: "inline-flex",
    alignItems: "center",
    fontSize: "xs",
    fontWeight: "semibold",
    color: "ink2",
    backgroundColor: "surfaceSub",
    paddingX: "2",
    paddingY: "0.5",
    borderRadius: "chip",
  }),
  low: css({
    display: "inline-flex",
    alignItems: "center",
    fontSize: "xs",
    fontWeight: "semibold",
    color: "ink3",
    backgroundColor: "surfaceSub",
    paddingX: "2",
    paddingY: "0.5",
    borderRadius: "chip",
  }),
};

const CONFIDENCE_LABEL: Record<ReliabilityConfidence, string> = {
  high: "신뢰도 높음",
  medium: "신뢰도 보통",
  low: "신뢰도 낮음",
};

const reliabilityBasisStyle = css({
  fontSize: "xs",
  color: "ink3",
  marginTop: "0.5",
});

// 병원이 "승인"(후보 등록) 응답을 보내야만 버튼이 활성화된다. 버튼을 누르면 그 자리에서
// 바로 이송 승인(final_approval)이 전송된다 — 별도의 "선택 → 하단에서 최종 승인" 2단계가 아니다.
export function HospitalCandidateListPanel({
  data,
  confirmedHospitalId,
  onApprove,
}: {
  data: HubMatchResult | null;
  confirmedHospitalId: string | null;
  onApprove: (hospitalId: string) => void;
}) {
  if (!data) {
    return (
      <ListPanelShell>
        <p className={css({ color: "ink3", fontSize: "sm" })}>수신 대기 중...</p>
      </ListPanelShell>
    );
  }

  // displayStatus까지 미리 계산해서 정렬 키로 쓴다 — 렌더링 때 또 계산하지 않고
  // 그대로 재사용한다.
  const sortedHospitals = data.hospitals
    .map((hospital) => {
      const confirmed = hospital.hospitalId === confirmedHospitalId;
      // "이송 확정"은 실제로 이 구급차 세션에서 승인 버튼을 눌렀을 때만 보여준다.
      // 데이터상 이미 confirmed여도, 로컬에서 아직 안 눌렀으면 "후보 등록"으로 표시한다.
      const displayStatus: HospitalStatus = confirmed
        ? "confirmed"
        : hospital.status === "confirmed"
          ? "approved"
          : hospital.status;
      return { hospital, confirmed, displayStatus };
    })
    .sort((a, b) => {
      // 1차: 병상 유무 (있음/미상 vs 확인된 만실)
      const bedDiff = bedAvailabilityPriority(a.hospital) - bedAvailabilityPriority(b.hospital);
      if (bedDiff !== 0) return bedDiff;

      // 2차: 승인 여부 (기존 기준 그대로 — 확정 > 승인 > 대기 > 거절)
      const statusDiff = STATUS_PRIORITY[a.displayStatus] - STATUS_PRIORITY[b.displayStatus];
      if (statusDiff !== 0) return statusDiff;

      // 3차: 적합도 (specialtyMatch.score, 높을수록 우선)
      const matchDiff = b.hospital.specialtyMatch.score - a.hospital.specialtyMatch.score;
      if (matchDiff !== 0) return matchDiff;

      // 여기까지 전부 같으면 거리로 최종 결정 — 동점일 때 순서가 매번
      // 흔들리지 않도록 하는 안정적 타이브레이커일 뿐, 별도 기준은 아니다.
      return a.hospital.distanceKm - b.hospital.distanceKm;
    });

  return (
    <ListPanelShell subtitle={`Zone ${data.zoneActive.join(", ")} 내 후보`}>
      {/* 병원이 몇 곳이든(거리·우선순위로 이미 정렬돼 오므로) 패널 자체가 늘어나지
          않고 이 목록 안에서만 스크롤되게 한다 — ListPanelShell이 셀 높이를 정확히
          지키므로(minHeight:0 + overflow:hidden), 여기는 남는 공간을 그대로
          차지하다가(flex:1) 넘칠 때만 스스로 스크롤하면 된다(고정 maxHeight 불필요). */}
      <ul
        className={cx(
          css({
            display: "flex",
            flexDirection: "column",
            gap: "2",
            flex: "1",
            minHeight: "0",
            overflowY: "auto",
          }),
          thinScrollbarStyle,
        )}
      >
        {sortedHospitals.map(({ hospital, confirmed, displayStatus }) => {
          const approvable = hospital.status === "approved" || hospital.status === "confirmed";

          return (
            <li
              key={hospital.hospitalId}
              className={css({
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                gap: "2.5",
                paddingX: "3.5",
                paddingY: "2.5",
                borderRadius: "field",
                borderWidth: "1px",
                borderColor: confirmed ? "navy" : "line",
                backgroundColor: confirmed ? "navySoft" : "surface",
              })}
            >
              <div className={css({ display: "flex", flexDirection: "column", gap: "0.5", minWidth: "0" })}>
                <span className={css({ fontWeight: "semibold", fontSize: "sm", color: "ink" })}>
                  {hospital.name}
                </span>
                <span className={css({ fontSize: "sm", fontWeight: "medium", color: "ink" })}>
                  {hospital.distanceKm}km
                  {hospital.etaMin != null ? ` · ETA ${hospital.etaMin}분` : ""}
                </span>
                <div className={css({ display: "flex", gap: "1", flexWrap: "wrap" })}>
                  <span className={deptChipStyle}>
                    {hospital.specialtyMatch.department} · 적합도 {Math.round(hospital.specialtyMatch.score * 100)}%
                  </span>
                  <span
                    className={
                      hospital.bedCountUnknown
                        ? bedChipUnknownStyle
                        : hospital.availableBedCount > 0
                          ? bedChipAvailableStyle
                          : bedChipEmptyStyle
                    }
                  >
                    {hospital.bedCountUnknown
                      ? "병상 미상"
                      : hospital.availableBedCount > 0
                        ? `병상 ${hospital.availableBedCount}석`
                        : "병상 없음"}
                  </span>
                  {/* 순위(specialtyMatch·distanceKm)와는 별개의 설명용 정보 —
                      info-v2가 심평원 대조로 판단한 신뢰도. 이 병원에 해당
                      데이터가 없으면(구 feature/info 데이터 등) 칩 자체를 숨긴다. */}
                  {hospital.reliability && (
                    <span className={CONFIDENCE_CHIP_STYLE[hospital.reliability.confidence]}>
                      {hospital.reliability.group} · {CONFIDENCE_LABEL[hospital.reliability.confidence]}
                    </span>
                  )}
                </div>
                {hospital.reliability && hospital.reliability.basis.length > 0 && (
                  <p className={reliabilityBasisStyle}>근거: {hospital.reliability.basis.join(" · ")}</p>
                )}
              </div>

              <div className={css({ display: "flex", alignItems: "center", gap: "2", flexShrink: "0" })}>
                <span className={hospitalStatusBadge({ status: displayStatus })}>
                  {STATUS_LABEL[displayStatus]}
                </span>
                <button
                  type="button"
                  disabled={!approvable}
                  onClick={() => onApprove(hospital.hospitalId)}
                  className={confirmed ? mintButtonStyle : primaryButtonStyle}
                >
                  {confirmed ? "승인 완료" : "이송 승인"}
                </button>
              </div>
            </li>
          );
        })}
      </ul>
    </ListPanelShell>
  );
}
