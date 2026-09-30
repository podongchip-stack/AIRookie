"use client";

import { css } from "styled-system/css";
import { dangerButtonStyle, primaryButtonStyle } from "@/components/ui/button-styles";
import type { AmbulancePhase, AmbulanceSimState } from "@/types/dashboard";

// 구급차 출동 시뮬레이션 조작부(2026-10-01, hub가 --sim-dispatch로 켜졌을 때만 보인다).
// 위치는 시연용 가짜 위치다 — 실제 GPS로 오인하지 않게 배지를 항상 붙인다.
const PHASE_LABEL: Record<AmbulancePhase, string> = {
  idle: "기지 대기",
  dispatching: "현장으로 출동 중",
  on_scene: "현장 도착",
  transporting: "병원으로 이송 중",
  at_hospital: "병원 도착",
  returning: "기지 복귀 중",
};

const simBadgeStyle = css({
  fontSize: "2xs",
  fontWeight: "semibold",
  color: "coral",
  backgroundColor: "coralSoft",
  paddingX: "2",
  paddingY: "0.5",
  borderRadius: "chip",
});

export function DispatchControlPanel({
  sim,
  confirmed,
  callActive,
  onDispatch,
  onSceneEnd,
}: {
  sim: AmbulanceSimState | null;
  confirmed: boolean;
  callActive: boolean;
  onDispatch: () => void;
  onSceneEnd: () => void;
}) {
  const phase: AmbulancePhase = sim?.phase ?? "idle";
  const canDispatch = phase === "idle" || phase === "returning";
  const canEndScene = phase === "on_scene" && !confirmed && !callActive;
  const etaMin = sim?.etaSec != null && sim.etaSec > 0 ? Math.max(1, Math.ceil(sim.etaSec / 60)) : null;

  return (
    <section
      className={css({
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        gap: "3",
        paddingX: "4",
        paddingY: "3",
        borderWidth: "1px",
        borderColor: "line",
        borderRadius: "panel",
        backgroundColor: "surface",
      })}
    >
      <div className={css({ display: "flex", flexDirection: "column", gap: "1", minWidth: "0" })}>
        <div className={css({ display: "flex", alignItems: "center", gap: "2" })}>
          <span className={css({ fontSize: "sm", fontWeight: "bold", color: "ink" })}>{PHASE_LABEL[phase]}</span>
          <span className={simBadgeStyle}>시뮬레이션 위치</span>
        </div>
        <span className={css({ fontSize: "xs", color: "ink3" })}>
          {etaMin != null
            ? `도착까지 약 ${etaMin}분 (실제 도로 기준)`
            : phase === "on_scene"
              ? callActive
                ? "통화를 끝내야 현장 종료할 수 있습니다"
                : "통화를 시작해 병원에 환자 정보를 보내세요"
              : "[이동]을 누르면 근처(약 10분 거리) 환자 발생 위치로 출동합니다"}
        </span>
      </div>
      <div className={css({ display: "flex", gap: "2", flexShrink: "0" })}>
        {phase === "on_scene" && (
          <button type="button" className={dangerButtonStyle} onClick={onSceneEnd} disabled={!canEndScene}>
            현장 종료
          </button>
        )}
        <button type="button" className={primaryButtonStyle} onClick={onDispatch} disabled={!canDispatch}>
          이동
        </button>
      </div>
    </section>
  );
}
