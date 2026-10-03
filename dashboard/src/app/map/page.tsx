"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { css, cx } from "styled-system/css";
import { HospitalDashboard } from "@/components/hospital/HospitalDashboard";
import { MonitorMapPanel } from "@/components/map/MonitorMapPanel";
import { distanceLabel } from "@/lib/distance";
import { thinScrollbarStyle } from "@/components/ui/scrollbar-style";
import { CONNECTION_LABEL, useDashboardSocket } from "@/hooks/use-dashboard-socket";
import {
  MAP_COLORS, PHASE_SHORT, SEVERITY_SHORT, STATUS_ICON, STATUS_SHORT, hospitalRequests, statusColor,
} from "@/lib/monitor";

// 관제 지도(2026-10-03). 병원 대시보드는 주소로 직접 열지 않고, 여기서 환자 요청이 온 병원을 눌러 지도 위에
// 띄운다([닫기]로 돌아온다). 지도는 hub에 role=monitor로 붙어 전체 병원·구급차 위치와 사건 요약만 받는다 —
// 통화 전문 등 환자 상세는 병원 대시보드(role=hospital)를 열어야 보인다.
export default function MonitorMapPage() {
  const { state, connectionMode } = useDashboardSocket({ role: "monitor", id: "map" });
  const [openHospitalId, setOpenHospitalId] = useState<string | null>(null);
  const requests = useMemo(() => hospitalRequests(state.monitorCases), [state.monitorCases]);
  const cases = Object.values(state.monitorCases);
  const ambulances = state.mapOverview?.ambulances ?? [];

  return (
    <div
      className={css({
        display: "flex",
        flexDirection: "column",
        height: "100vh",
        backgroundColor: "bg",
        padding: "5",
        gap: "3.5",
      })}
    >
      <header
        className={css({
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          flexWrap: "wrap",
          gap: "4",
          backgroundColor: "surface",
          borderWidth: "1px",
          borderColor: "line",
          borderRadius: "panel",
          paddingX: "4.5",
          paddingY: "3",
        })}
      >
        <div className={css({ display: "flex", alignItems: "center", gap: "3" })}>
          <Link href="/" className={css({ fontSize: "md", fontWeight: "bold", color: "ink" })}>
            골든<span className={css({ color: "navy" })}>링크</span>
          </Link>
          <span className={css({ fontSize: "xs", color: "ink", paddingLeft: "3", borderLeftWidth: "1px", borderColor: "line" })}>
            관제 지도 · 병원·구급차 실시간 위치
          </span>
        </div>
        <div className={css({ display: "flex", alignItems: "center", gap: "3.5", flexWrap: "wrap", fontSize: "xs", color: "ink" })}>
          <LegendDot color={MAP_COLORS.hospital} label="병원" round />
          <LegendDot color={MAP_COLORS.request} label="🚨 판단 대기 (눌러서 대시보드 열기)" round />
          <LegendDot color={MAP_COLORS.approved} label="✓ 수용 승인" round />
          <LegendDot color={MAP_COLORS.rejected} label="✕ 수용 불가" round />
          <LegendDot color={MAP_COLORS.confirmed} label="🚑 이송 확정" round />
          <LegendDot color={MAP_COLORS.ambulance} label="구급차 (시뮬레이션 위치)" />
          <LegendDot color={MAP_COLORS.zone} label="요청 존 범위" dashed />
          <span className={css({ color: CONNECTION_LABEL[connectionMode].color })}>{CONNECTION_LABEL[connectionMode].text}</span>
        </div>
      </header>

      <main
        className={css({
          display: "grid",
          gridTemplateColumns: { base: "1fr", lg: "320px 1fr" },
          gap: "3.5",
          flex: "1",
          minHeight: "0",
        })}
      >
        <aside
          className={cx(
            css({
              display: "flex",
              flexDirection: "column",
              gap: "3",
              minHeight: "0",
              overflowY: "auto",
              paddingRight: "1",
            }),
            thinScrollbarStyle,
          )}
        >
          <SideSection title={`진행 중인 환자 요청 ${cases.length}건`}>
            {cases.length === 0 ? (
              <p className={css({ fontSize: "xs", color: "ink3" })}>
                아직 환자 요청이 없습니다. 구급차가 현장에서 통화를 마치면 인근 병원에 요청이 갑니다.
              </p>
            ) : (
              cases.map((monitorCase) => {
                const maxZone = Math.max(...monitorCase.zoneActive, 1);
                const confirmedId = monitorCase.hospitals.find((h) => h.status === "confirmed")?.hospitalId ?? null;
                return (
                  <div key={monitorCase.caseId} className={cardStyle}>
                    <div className={css({ display: "flex", alignItems: "center", justifyContent: "space-between", gap: "2" })}>
                      <span className={css({ fontSize: "sm", fontWeight: "bold", color: "ink" })}>
                        {monitorCase.ambulanceName ?? monitorCase.apid ?? "구급차"}
                      </span>
                      {monitorCase.severityTag && (
                        <span className={css({ fontSize: "2xs", fontWeight: "semibold", color: "coral", backgroundColor: "coralSoft", paddingX: "1.5", borderRadius: "chip" })}>
                          {SEVERITY_SHORT[monitorCase.severityTag]}
                        </span>
                      )}
                    </div>
                    <span className={css({ fontSize: "xs", color: "ink3" })}>
                      요청 범위 존 1{maxZone > 1 ? `~${maxZone}` : ""} ({maxZone * monitorCase.zoneBandKm}km)
                      {maxZone > 1 ? " · 거절 비율로 확장" : ""}
                    </span>
                    <ul className={css({ display: "flex", flexDirection: "column", gap: "1" })}>
                      {monitorCase.hospitals.map((hospital) => {
                        const openable = !confirmedId || confirmedId === hospital.hospitalId;
                        return (
                          <li key={hospital.hospitalId}>
                            <button
                              type="button"
                              disabled={!openable}
                              onClick={() => setOpenHospitalId(hospital.hospitalId)}
                              className={hospitalRowStyle}
                              title={openable ? "병원 대시보드 열기" : "다른 병원으로 이송이 확정된 사건입니다"}
                            >
                              <span className={css({ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" })}>
                                {hospital.name}
                              </span>
                              <span className={css({ flexShrink: "0", color: "ink3" })}>
                                {distanceLabel(hospital)} · 존 {hospital.zone} ·{" "}
                                <b style={{ color: statusColor(hospital.status) }}>
                                  {STATUS_ICON[hospital.status]} {STATUS_SHORT[hospital.status]}
                                </b>
                              </span>
                            </button>
                          </li>
                        );
                      })}
                    </ul>
                  </div>
                );
              })
            )}
          </SideSection>

          <SideSection title="병원 응답">
            {state.monitorEvents.length === 0 ? (
              <p className={css({ fontSize: "xs", color: "ink3" })}>
                병원이 수용 승인·불가를 누르거나 이송이 확정되면 여기에 쌓입니다.
              </p>
            ) : (
              <ul className={css({ display: "flex", flexDirection: "column", gap: "1.5" })}>
                {state.monitorEvents.map((event) => (
                  <li
                    key={`${event.caseId}-${event.hospitalId}-${event.status}-${event.at}`}
                    className={css({ display: "flex", gap: "2", fontSize: "xs", color: "ink" })}
                  >
                    <span className={css({ color: "ink3", flexShrink: "0" })}>
                      {new Date(event.at).toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit", second: "2-digit" })}
                    </span>
                    <span>
                      <b>{event.hospitalName}</b>{" "}
                      <b style={{ color: statusColor(event.status) }}>
                        {STATUS_ICON[event.status]} {STATUS_SHORT[event.status]}
                      </b>
                      <span className={css({ color: "ink3" })}> · {event.ambulanceName}</span>
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </SideSection>

          <SideSection title={`구급차 ${ambulances.length}대`}>
            {ambulances.map((ambulance) => {
              const sim = state.ambulanceSim[ambulance.apid];
              return (
                <div key={ambulance.apid} className={css({ display: "flex", justifyContent: "space-between", gap: "2", fontSize: "xs", color: "ink" })}>
                  <span className={css({ fontWeight: "semibold" })}>{ambulance.name}</span>
                  <span className={css({ color: "ink3" })}>
                    {sim ? `${PHASE_SHORT[sim.phase]}${sim.paused ? " · 정지" : ""}` : "위치 고정"}
                  </span>
                </div>
              );
            })}
          </SideSection>

          <p className={css({ fontSize: "2xs", color: "ink3" })}>
            병원 대시보드는 환자 요청이 온 병원만 열 수 있습니다. 지도를 축소한 상태에선 병원 마커를 누르면 이름이
            뜨고, 확대하면 모든 병원 이름이 보입니다. 위치·존은 규칙 기반이며, 구급차 위치는 시연용
            시뮬레이션입니다.
          </p>
        </aside>

        <MonitorMapPanel
          overview={state.mapOverview}
          cases={state.monitorCases}
          ambulanceSim={state.ambulanceSim}
          requests={requests}
          onOpenHospital={setOpenHospitalId}
        />
      </main>

      {openHospitalId && (
        // 신뢰도 검증 모달(FrameModalButton, zIndex 1000)이 이 위에 떠야 해서 그보다 낮게 둔다.
        <div
          role="dialog"
          aria-modal="true"
          aria-label="병원 대시보드"
          className={cx(
            css({ position: "fixed", inset: "0", zIndex: 900, backgroundColor: "bg", overflowY: "auto" }),
            thinScrollbarStyle,
          )}
        >
          <HospitalDashboard hospitalId={openHospitalId} onClose={() => setOpenHospitalId(null)} />
        </div>
      )}
    </div>
  );
}

const cardStyle = css({
  display: "flex",
  flexDirection: "column",
  gap: "1.5",
  borderWidth: "1px",
  borderColor: "line",
  borderRadius: "field",
  padding: "3",
  backgroundColor: "surface",
});

const hospitalRowStyle = css({
  display: "flex",
  justifyContent: "space-between",
  gap: "2",
  width: "100%",
  textAlign: "left",
  fontSize: "xs",
  color: "ink",
  paddingX: "2",
  paddingY: "1",
  borderRadius: "field",
  cursor: "pointer",
  _hover: { backgroundColor: "surfaceSub" },
  _disabled: { cursor: "not-allowed", opacity: 0.5 },
});

function SideSection({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section
      className={css({
        display: "flex",
        flexDirection: "column",
        gap: "2.5",
        backgroundColor: "surface",
        borderWidth: "1px",
        borderColor: "line",
        borderRadius: "panel",
        padding: "3.5",
      })}
    >
      <h2 className={css({ fontSize: "sm", fontWeight: "bold", color: "ink" })}>{title}</h2>
      {children}
    </section>
  );
}

function LegendDot({ color, label, round, dashed }: { color: string; label: string; round?: boolean; dashed?: boolean }) {
  return (
    <span className={css({ display: "inline-flex", alignItems: "center", gap: "1.5" })}>
      <span
        style={{
          width: 12,
          height: 12,
          borderRadius: round ? 999 : 3,
          background: dashed ? "transparent" : color,
          border: dashed ? `2px dashed ${color}` : "2px solid #FFFFFF",
          boxShadow: dashed ? undefined : `0 0 0 1px ${color}`,
          display: "inline-block",
        }}
      />
      {label}
    </span>
  );
}
