import { css } from "styled-system/css";
import { Panel } from "@/components/layout/Panel";
import { Tag } from "@/components/hospital/Tag";
import type { HospitalCandidate, HospitalStatus } from "@/types/dashboard";

const STATUS_LABEL: Record<HospitalStatus, string> = {
  pending: "판단 대기",
  approved: "후보 등록",
  rejected: "수용 불가",
  confirmed: "이송 확정",
};

const mapLabelStyle = css({
  position: "absolute",
  top: "4",
  left: "50%",
  transform: "translateX(-50%)",
  fontSize: "2xs",
  fontWeight: "semibold",
  whiteSpace: "nowrap",
  backgroundColor: "surface",
  borderWidth: "1px",
  borderColor: "line",
  paddingX: "1.5",
  borderRadius: "chip",
  color: "ink",
});

const sideBoxStyle = css({
  flex: "1",
  borderWidth: "1px",
  borderColor: "line",
  borderRadius: "field",
  paddingX: "3.5",
  paddingY: "3",
});

const markerDotStyle = css({
  display: "block",
  width: "3.5",
  height: "3.5",
  borderRadius: "full",
  border: "2.5px solid #FFFFFF",
  boxShadow: "0 0 0 1px #CBD5E1",
});

// 구급차 대시보드의 CandidateMapPanel과 같은 구조(지도가 위, 정보 박스 3개가 그 아래
// 한 줄)로 맞췄다 — 이전엔 지도 옆에 세로 사이드바를 두는 다른 레이아웃이었다(2026-08-09).
export function MapPanel({ hospital }: { hospital: HospitalCandidate | null }) {
  const confirmed = hospital?.status === "confirmed";

  return (
    <Panel
      title="지도 · 네비게이션"
      subtitle="구급차 현재 위치 및 본원까지 이동 시간"
      badge={<Tag source="rule">GPS · 카카오내비</Tag>}
    >
      <div className={css({ display: "flex", flexDirection: "column", gap: "3.5", flex: "1", minHeight: "0" })}>
        <div
          role="img"
          aria-label="구급차 현재 위치와 본원까지의 경로를 표시한 지도"
          className={css({
            position: "relative",
            flex: "1",
            minWidth: "240px",
            minHeight: "160px",
            borderWidth: "1px",
            borderColor: "line",
            borderRadius: "field",
            backgroundColor: "#EDF2F7",
            backgroundImage:
              "linear-gradient(#E2E8EF 1px, transparent 1px), linear-gradient(90deg, #E2E8EF 1px, transparent 1px)",
            backgroundSize: "26px 26px",
            overflow: "hidden",
          })}
        >
          <div className={css({ position: "absolute", backgroundColor: "surface", height: "3px", left: "0", right: "0", top: "40%" })} />
          <div className={css({ position: "absolute", backgroundColor: "surface", height: "3px", left: "0", right: "0", top: "78%" })} />
          <div className={css({ position: "absolute", backgroundColor: "surface", width: "3px", top: "0", bottom: "0", left: "30%" })} />
          <div className={css({ position: "absolute", backgroundColor: "surface", width: "3px", top: "0", bottom: "0", left: "72%" })} />

          <div
            className={css({
              position: "absolute",
              height: "3px",
              borderRadius: "sm",
              top: "40%",
              left: "18%",
              width: "56%",
              backgroundImage:
                "repeating-linear-gradient(90deg, #1E5FA8 0 9px, transparent 9px 16px)",
            })}
          />

          <div className={css({ position: "absolute", top: "40%", left: "18%", transform: "translate(-50%, -50%)" })}>
            <span
              className={`${markerDotStyle} ${css({ backgroundColor: "navy", animation: "nudge 2.6s ease-in-out infinite" })}`}
            />
            <span className={mapLabelStyle}>구급차 현재 위치</span>
          </div>
          <div className={css({ position: "absolute", top: "40%", left: "74%", transform: "translate(-50%, -50%)" })}>
            <span className={`${markerDotStyle} ${css({ backgroundColor: "mint" })}`} />
            <span className={mapLabelStyle}>본원</span>
          </div>
        </div>

        <div className={css({ width: "100%", display: "flex", flexDirection: "row", gap: "2.5" })}>
          <div
            className={css({
              flex: "1",
              borderWidth: "1px",
              borderColor: confirmed ? "#B9E4D3" : "line",
              backgroundColor: confirmed ? "mintSoft" : "surface",
              borderRadius: "field",
              paddingX: "3.5",
              paddingY: "3",
            })}
          >
            <div className={css({ fontSize: "sm", fontWeight: "medium", color: confirmed ? "#0A7351" : "ink" })}>
              본원 도착 예상
            </div>
            <div
              className={css({
                fontSize: "2xl",
                fontWeight: "bold",
                letterSpacing: "-0.02em",
                color: confirmed ? "#0A7351" : "ink",
              })}
            >
              {hospital?.etaMin != null ? `${hospital.etaMin}분` : "-"}
            </div>
            <div className={css({ fontSize: "xs", color: "ink", marginTop: "0.5" })}>
              실시간 교통 반영
            </div>
          </div>

          <div className={sideBoxStyle}>
            <div className={css({ fontSize: "sm", fontWeight: "medium", color: "ink" })}>직선 거리</div>
            <div className={css({ fontSize: "2xl", fontWeight: "bold", letterSpacing: "-0.02em", color: "ink" })}>
              {hospital ? `${hospital.distanceKm}km` : "-"}
            </div>
          </div>

          <div className={sideBoxStyle}>
            <div className={css({ fontSize: "sm", fontWeight: "medium", color: "ink" })}>현재 상태</div>
            <div className={css({ fontSize: "2xl", fontWeight: "bold", letterSpacing: "-0.02em", color: "ink" })}>
              {hospital ? STATUS_LABEL[hospital.status] : "-"}
            </div>
          </div>
        </div>
      </div>
    </Panel>
  );
}
