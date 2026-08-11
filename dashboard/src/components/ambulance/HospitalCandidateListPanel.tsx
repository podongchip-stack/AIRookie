"use client";

import { css } from "styled-system/css";
import { hospitalStatusBadge } from "styled-system/recipes";
import { Tag } from "@/components/hospital/Tag";
import { mintButtonStyle, primaryButtonStyle } from "@/components/ui/button-styles";
import type { HospitalStatus, HubMatchResult } from "@/types/dashboard";

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

const deptChipStyle = css({
  display: "inline-flex",
  alignItems: "center",
  fontSize: "2xs",
  fontWeight: "medium",
  color: "navy",
  backgroundColor: "navySoft",
  paddingX: "1.5",
  borderRadius: "chip",
});

const bedChipAvailableStyle = css({
  display: "inline-flex",
  alignItems: "center",
  fontSize: "2xs",
  fontWeight: "medium",
  color: "mint",
  backgroundColor: "mintSoft",
  paddingX: "1.5",
  borderRadius: "chip",
});

const bedChipEmptyStyle = css({
  display: "inline-flex",
  alignItems: "center",
  fontSize: "2xs",
  fontWeight: "medium",
  color: "coral",
  backgroundColor: "coralSoft",
  paddingX: "1.5",
  borderRadius: "chip",
});

// "확인된 만실"(coral)과는 색을 다르게 둔다 — 미상은 병원에 자리가 없다고 확정된
// 게 아니라 데이터가 아직 없는 것뿐이라, 만실과 같은 경고색으로 보이면 구급대원이
// 실제로는 받아줄 수도 있는 병원을 스스로 후보에서 빼게 된다(CLAUDE.md 참고).
const bedChipUnknownStyle = css({
  display: "inline-flex",
  alignItems: "center",
  fontSize: "2xs",
  fontWeight: "medium",
  color: "ink2",
  backgroundColor: "surfaceSub",
  paddingX: "1.5",
  borderRadius: "chip",
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

  return (
    <ListPanelShell subtitle={`Zone ${data.zoneActive.join(", ")} 내 후보`}>
      {/* 병원이 몇 곳이든(거리·우선순위로 이미 정렬돼 오므로) 패널 자체가 늘어나지
          않고 이 목록 안에서만 스크롤되게 한다 — ListPanelShell이 셀 높이를 정확히
          지키므로(minHeight:0 + overflow:hidden), 여기는 남는 공간을 그대로
          차지하다가(flex:1) 넘칠 때만 스스로 스크롤하면 된다(고정 maxHeight 불필요). */}
      <ul
        className={css({
          display: "flex",
          flexDirection: "column",
          gap: "2",
          flex: "1",
          minHeight: "0",
          overflowY: "auto",
          // 기본 스크롤바가 진한 회색/검정이라 전체 톤(연한 파스텔)과 안 어울려서
          // 옅고 투명하게 맞춘다. scrollbarWidth/scrollbarColor는 Firefox용,
          // ::-webkit-scrollbar*는 Chrome/Edge용 — 둘 다 있어야 브라우저 상관없이 적용된다.
          scrollbarWidth: "thin",
          scrollbarColor: "rgba(203, 213, 225, 0.5) transparent",
          "&::-webkit-scrollbar": {
            width: "6px",
          },
          "&::-webkit-scrollbar-track": {
            backgroundColor: "transparent",
          },
          "&::-webkit-scrollbar-thumb": {
            backgroundColor: "rgba(203, 213, 225, 0.5)",
            borderRadius: "full",
          },
          "&::-webkit-scrollbar-thumb:hover": {
            backgroundColor: "rgba(203, 213, 225, 0.8)",
          },
        })}
      >
        {data.hospitals.map((hospital) => {
          const confirmed = hospital.hospitalId === confirmedHospitalId;
          const approvable = hospital.status === "approved" || hospital.status === "confirmed";
          // "이송 확정"은 실제로 이 구급차 세션에서 승인 버튼을 눌렀을 때만 보여준다.
          // 데이터상 이미 confirmed여도, 로컬에서 아직 안 눌렀으면 "후보 등록"으로 표시한다.
          const displayStatus: HospitalStatus = confirmed
            ? "confirmed"
            : hospital.status === "confirmed"
              ? "approved"
              : hospital.status;

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
                <span className={css({ fontSize: "xs", color: "ink2" })}>
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
                </div>
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
