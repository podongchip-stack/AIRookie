"use client";

import { useMemo } from "react";
import Link from "next/link";
import { css, cx } from "styled-system/css";
import { MonitorMapPanel } from "@/components/map/MonitorMapPanel";
import { distanceLabel } from "@/lib/distance";
import { rejectionReasonLabel, unavailableReasonLabel } from "@/lib/rejection";
import type { MonitorCaseHospital } from "@/types/dashboard";

// 수용 불가의 종류 — E-Gen 병상 없음이면 그것, 병원이 직접 거절했으면 고른 사유(2026-10-03)
function reasonNote(hospital: MonitorCaseHospital): string | null {
  return unavailableReasonLabel(hospital.unavailableReason) ?? rejectionReasonLabel(hospital.rejectReason);
}
import { thinScrollbarStyle } from "@/components/ui/scrollbar-style";
import { CONNECTION_LABEL, useDashboardSocket } from "@/hooks/use-dashboard-socket";
import {
  AMBULANCE_PHASE_COLORS, LEVEL_COLORS, MAP_COLORS, PHASE_SHORT, SEVERITY_SHORT, STATUS_ICON, STATUS_SHORT, hospitalRequests, statusColor,
} from "@/lib/monitor";

// 관제 지도(2026-10-03). hub에 role=monitor로 붙어 전체 병원·구급차 위치와 사건 요약만 받는다 — 통화 전문 등
// 환자 상세는 받지 않는다. 병원 대시보드와는 분리돼 있다(2026-10-03 회의): 여기선 병원 이름과 접근 코드(H-<hpid>)만
// 보여주고, 병원 대시보드는 첫 페이지에서 그 코드로 연다.
export default function MonitorMapPage() {
  const { state, connectionMode } = useDashboardSocket({ role: "monitor", id: "map" });
  const requests = useMemo(() => hospitalRequests(state.monitorCases), [state.monitorCases]);
  const cases = Object.values(state.monitorCases);
  const ambulances = state.mapOverview?.ambulances ?? [];
  const calls = Object.values(state.callStatus).filter((c) => c.state === "calling");
  // 사건 클릭(2026-10-04) — 관제 지도 본창은 항상 **전체 현황**(모든 병원 상태·모든 구급대)을
  // 유지한다. 사건 하나를 깊게 보는 건 새 창의 사건 상황판(/case?id=) 몫이다.
  const openCaseBoard = (caseId: string) => window.open(`/case?id=${encodeURIComponent(caseId)}`, "_blank", "noopener");
  // 매칭 전(신고 접수 → 출동 → 현장 통화 전) 사건(2026-10-04) — 관제는 신고 접수부터 전 과정을
  // 팔로잉한다. 구급차 시뮬레이션 상태(사건 배정됨)와 예비 고지 요약으로 만들고, 현장 통화가
  // 끝나 매칭되면 case_overview(아래 목록)가 같은 caseId로 이어받는다.
  const preCases = Object.values(state.ambulanceSim)
    .filter((s) => s.caseId && !state.monitorCases[s.caseId] && !["idle", "returning"].includes(s.phase))
    .map((s) => ({
      sim: s,
      alert: s.caseId ? state.preAlerts[s.caseId] ?? null : null,
      name: ambulances.find((a) => a.apid === s.apid)?.name ?? s.apid,
    }));

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
          {/* 등급별 색(2026-10-04) — 분산 원칙의 축: 중증은 센터로, 경증은 기관으로 */}
          <LegendDot color={LEVEL_COLORS["권역응급의료센터"]} label="권역센터 (중증)" round />
          <LegendDot color={LEVEL_COLORS["지역응급의료센터"]} label="지역센터 (중등증)" round />
          <LegendDot color={MAP_COLORS.hospital} label="응급의료기관 (경증)" round />
          <LegendDot color={MAP_COLORS.request} label="🚨 판단 대기" round />
          <LegendDot color={MAP_COLORS.approved} label="✓ 수용 승인" round />
          <LegendDot color={MAP_COLORS.rejected} label="✕ 수용 불가" round />
          <LegendDot color={MAP_COLORS.confirmed} label="🚑 이송 확정" round />
          {/* 구급차 단계별 마커 색(2026-10-04) — 이름은 움직이는 구급차만 뜬다 */}
          <LegendDot color={AMBULANCE_PHASE_COLORS.idle} label="구급차 기지 대기" />
          <LegendDot color={AMBULANCE_PHASE_COLORS.dispatching} label="출동 중" />
          <LegendDot color={AMBULANCE_PHASE_COLORS.on_scene} label="현장 도착" />
          <LegendDot color={AMBULANCE_PHASE_COLORS.transporting} label="병원 이송 중" />
          <LegendDot color={AMBULANCE_PHASE_COLORS.at_hospital} label="병원 도착" />
          <LegendDot color={AMBULANCE_PHASE_COLORS.returning} label="기지 복귀 중" />
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
          <SideSection title={`진행 중인 사건 ${cases.length + preCases.length}건`}>
            {/* 매칭 전 단계 — 신고 접수·출동·현장. 클릭하면 사건 상황판이 신고 단계부터 열린다. */}
            {preCases.map(({ sim, alert, name }) => (
              <div
                key={sim.caseId}
                role="button"
                tabIndex={0}
                onClick={() => sim.caseId && openCaseBoard(sim.caseId)}
                onKeyDown={(e) => {
                  if ((e.key === "Enter" || e.key === " ") && sim.caseId) openCaseBoard(sim.caseId);
                }}
                title="클릭하면 사건 상황판이 새 창으로 열립니다"
                className={cx(cardStyle, css({ cursor: "pointer", _hover: { borderColor: "navy" } }))}
              >
                <div className={css({ display: "flex", alignItems: "center", justifyContent: "space-between", gap: "2" })}>
                  <span className={css({ fontSize: "sm", fontWeight: "bold", color: "ink" })}>🚨 {name}</span>
                  {alert?.reportedSeverity === "high" && (
                    <span className={css({ fontSize: "2xs", fontWeight: "semibold", color: "coral", backgroundColor: "coralSoft", paddingX: "1.5", borderRadius: "chip" })}>
                      중증 의심
                    </span>
                  )}
                </div>
                <span className={css({ fontSize: "xs", color: "ink" })}>
                  {PHASE_SHORT[sim.phase]}{sim.paused ? " · 정지" : ""}
                  {alert?.reportedSymptom ? ` · 신고: ${alert.reportedSymptom}` : ""}
                </span>
                <span className={css({ fontSize: "xs", color: "ink3" })}>
                  {alert && (alert.hospitalCount ?? 0) > 0
                    ? `예비 고지 ${alert.hospitalCount}곳 발송됨`
                    : "예비 고지 없음(경증 신고)"}
                  {" · 현장 통화 전"}
                </span>
              </div>
            ))}
            {cases.length === 0 && preCases.length === 0 ? (
              <p className={css({ fontSize: "xs", color: "ink3" })}>
                아직 사건이 없습니다. 신고가 접수되면(구급대 출동) 여기부터 팔로잉됩니다.
              </p>
            ) : (
              cases.map((monitorCase) => {
                const maxZone = Math.max(...monitorCase.zoneActive, 1);
                const confirmedId = monitorCase.hospitals.find((h) => h.status === "confirmed")?.hospitalId ?? null;
                return (
                  <div
                    key={monitorCase.caseId}
                    role="button"
                    tabIndex={0}
                    onClick={() => openCaseBoard(monitorCase.caseId)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") openCaseBoard(monitorCase.caseId);
                    }}
                    title="클릭하면 사건 상황판이 새 창으로 열립니다 — 이 지도는 전체 현황을 유지합니다"
                    className={cx(cardStyle, css({ cursor: "pointer", _hover: { borderColor: "navy" } }))}
                  >
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
                        const done = confirmedId != null && confirmedId !== hospital.hospitalId;
                        return (
                          <li key={hospital.hospitalId}>
                            <div
                              className={hospitalRowStyle}
                              style={done ? { opacity: 0.5 } : undefined}
                              title={done ? "다른 병원으로 이송이 확정된 사건입니다" : undefined}
                            >
                              <span className={css({ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" })}>
                                {hospital.name}{" "}
                                <span className={css({ color: "navy", fontWeight: "semibold" })}>H-{hospital.hospitalId}</span>
                              </span>
                              <span className={css({ flexShrink: "0", color: "ink3" })}>
                                {distanceLabel(hospital)} · 존 {hospital.zone} ·{" "}
                                <b style={{ color: statusColor(hospital.status) }}>
                                  {STATUS_ICON[hospital.status]} {STATUS_SHORT[hospital.status]}
                                  {hospital.status === "rejected" && reasonNote(hospital) ? ` · ${reasonNote(hospital)}` : ""}
                                </b>
                              </span>
                            </div>
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

          {/* 구급차 목록(2026-10-04) — 서울 119 구급차 160여 대로 바뀌어 한 줄씩 나열하던 목록을 뺐다. 자리만 남김 */}
          <SideSection title="구급차">
            <p className={css({ fontSize: "xs", color: "ink3" })}>테스트</p>
          </SideSection>

          <p className={css({ fontSize: "2xs", color: "ink3" })}>
            병원 이름 옆 H-로 시작하는 값이 병원 대시보드 접근 코드입니다(첫 페이지에서 입력). 지도를 축소해 이름이
            안 보이면 마커를 눌러 이름과 코드를 띄울 수 있습니다. 위치·존은 규칙 기반이며, 구급차 위치는 시연용
            시뮬레이션입니다.
          </p>
        </aside>

        <MonitorMapPanel
          overview={state.mapOverview}
          cases={state.monitorCases}
          ambulanceSim={state.ambulanceSim}
          requests={requests}
          calls={calls}
        />
      </main>
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
