"use client";

import { css } from "styled-system/css";
import { distanceLabel } from "@/lib/distance";
import {
  PHASE_SHORT, SEVERITY_SHORT, STATUS_ICON, STATUS_SHORT, hospitalReasonNote, statusColor,
} from "@/lib/monitor";
import type { AmbulancePhase, MonitorCase, MonitorEvent } from "@/types/dashboard";

// 사건 상황판 패널(2026-10-04) — 관제 지도에서 사건을 클릭하면 **새 창**(/case?id=)으로
// 열리는 사건 전용 화면의 왼쪽 내용. 관제 지도 자체는 항상 전체 현황(모든 병원 상태)을
// 유지해야 해서(2026-10-04 요청), 사건 상세는 지도 화면을 바꾸지 않고 따로 띄운다.
// 환자 상세(통화 전문·활력징후)는 여기서도 안 받는다 — 관제는 case_overview 요약만.
export function CaseFocusPanel({
  monitorCase,
  phase,
  paused,
  events,
}: {
  monitorCase: MonitorCase;
  phase: AmbulancePhase | null;
  paused: boolean;
  events: MonitorEvent[];
}) {
  const maxZone = Math.max(...monitorCase.zoneActive, 1);
  const confirmedId = monitorCase.hospitals.find((h) => h.status === "confirmed")?.hospitalId ?? null;
  const counts = monitorCase.hospitals.reduce(
    (acc, h) => ({ ...acc, [h.status]: (acc[h.status] ?? 0) + 1 }),
    {} as Record<string, number>,
  );
  return (
    <>
      <Section title={`사건 상황판 — ${monitorCase.ambulanceName ?? monitorCase.apid ?? "구급차"}`}>
        <div className={css({ display: "flex", gap: "1.5", flexWrap: "wrap", fontSize: "xs" })}>
          {monitorCase.severityTag && (
            <span className={css({ fontWeight: "bold", color: "coral", backgroundColor: "coralSoft", paddingX: "2", paddingY: "0.5", borderRadius: "chip" })}>
              {SEVERITY_SHORT[monitorCase.severityTag]}
            </span>
          )}
          {phase && (
            <span className={css({ fontWeight: "semibold", color: "ink", backgroundColor: "surfaceSub", paddingX: "2", paddingY: "0.5", borderRadius: "chip" })}>
              🚑 {PHASE_SHORT[phase]}{paused ? " · 정지됨" : ""}
            </span>
          )}
          <span className={css({ color: "ink3", alignSelf: "center" })}>
            요청 존 1{maxZone > 1 ? `~${maxZone}` : ""} ({maxZone * monitorCase.zoneBandKm}km)
            {maxZone > 1 ? " · 거절로 확장" : ""}
          </span>
        </div>
        <p className={css({ fontSize: "xs", color: "ink2" })}>
          요청 {monitorCase.hospitals.length}곳 — 승인 {counts.approved ?? 0} · 대기 {counts.pending ?? 0} · 불가{" "}
          {counts.rejected ?? 0}{confirmedId ? " · 이송 확정 1" : ""}
        </p>
        <ul className={css({ display: "flex", flexDirection: "column", gap: "1" })}>
          {monitorCase.hospitals.map((hospital) => (
            <li
              key={hospital.hospitalId}
              className={css({ display: "flex", justifyContent: "space-between", gap: "2", fontSize: "xs", color: "ink", paddingY: "0.5" })}
              style={confirmedId && confirmedId !== hospital.hospitalId ? { opacity: 0.55 } : undefined}
            >
              <span className={css({ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" })}>
                {hospital.name}
              </span>
              <span className={css({ flexShrink: "0", color: "ink3" })}>
                {distanceLabel(hospital)} · 존 {hospital.zone} ·{" "}
                <b style={{ color: statusColor(hospital.status) }}>
                  {STATUS_ICON[hospital.status]} {STATUS_SHORT[hospital.status]}
                  {hospital.status === "rejected" && hospitalReasonNote(hospital) ? ` · ${hospitalReasonNote(hospital)}` : ""}
                </b>
              </span>
            </li>
          ))}
        </ul>
      </Section>
      <Section title="이 사건의 병원 응답">
        {events.length === 0 ? (
          <p className={css({ fontSize: "xs", color: "ink3" })}>아직 응답이 없습니다.</p>
        ) : (
          <ul className={css({ display: "flex", flexDirection: "column", gap: "1.5" })}>
            {events.map((event) => (
              <li
                key={`${event.hospitalId}-${event.status}-${event.at}`}
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
                </span>
              </li>
            ))}
          </ul>
        )}
      </Section>
    </>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section
      className={css({
        display: "flex", flexDirection: "column", gap: "2.5",
        backgroundColor: "surface", borderWidth: "1px", borderColor: "line", borderRadius: "panel", padding: "3.5",
      })}
    >
      <h2 className={css({ fontSize: "sm", fontWeight: "bold", color: "ink" })}>{title}</h2>
      {children}
    </section>
  );
}
