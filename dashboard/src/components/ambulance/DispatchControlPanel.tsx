"use client";

import { useState } from "react";
import { css, cx } from "styled-system/css";
import {
  dangerButtonStyle,
  inputStyle,
  primaryButtonStyle,
  secondaryButtonStyle,
} from "@/components/ui/button-styles";
import { thinScrollbarStyle } from "@/components/ui/scrollbar-style";
import { searchPlaces } from "@/lib/geocode";
import type { AmbulancePhase, AmbulanceSimState, DispatchTarget, GeocodeResult } from "@/types/dashboard";

// 구급차 출동 시뮬레이션 조작부(2026-10-01, hub가 --sim-dispatch로 켜졌을 때만 보인다).
// 위치는 시연용 가짜 위치다 — 실제 GPS로 오인하지 않게 배지를 항상 붙인다.
// 출동 위치: 아무것도 고르지 않으면 기지 근처 무작위, 주소 검색·지도 클릭으로 고르면 그곳.
// 고른 주소 글자는 이 탭에만 남고 hub로는 좌표만 간다(집 주소일 수 있음).
const PHASE_LABEL: Record<AmbulancePhase, string> = {
  idle: "기지 대기",
  dispatching: "현장으로 출동 중",
  on_scene: "현장 도착",
  transporting: "병원으로 이송 중",
  at_hospital: "병원 도착 — 수용 결과 대기",
  rerouting: "재선택 대기 (도착 병원 수용 불가)",
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

const targetChipStyle = css({
  display: "inline-flex",
  alignItems: "center",
  gap: "1.5",
  fontSize: "xs",
  fontWeight: "semibold",
  color: "navy",
  backgroundColor: "navySoft",
  paddingX: "2",
  paddingY: "0.5",
  borderRadius: "chip",
});

const resultButtonStyle = css({
  display: "flex",
  justifyContent: "space-between",
  gap: "2",
  width: "100%",
  textAlign: "left",
  paddingX: "2.5",
  paddingY: "1.5",
  fontSize: "xs",
  color: "ink",
  borderRadius: "field",
  cursor: "pointer",
  _hover: { backgroundColor: "surfaceSub" },
});

export function DispatchControlPanel({
  apid,
  sim,
  confirmed,
  callActive,
  target,
  onTargetChange,
  onDispatch,
  onSceneEnd,
}: {
  apid: string;
  sim: AmbulanceSimState | null;
  confirmed: boolean;
  callActive: boolean;
  target: DispatchTarget | null;
  onTargetChange: (target: DispatchTarget | null) => void;
  onDispatch: () => void;
  onSceneEnd: () => void;
}) {
  const phase: AmbulancePhase = sim?.phase ?? "idle";
  const canDispatch = phase === "idle" || phase === "returning";
  const canEndScene = (phase === "on_scene" || phase === "rerouting") && !confirmed && !callActive;
  const etaMin = sim?.etaSec != null && sim.etaSec > 0 ? Math.max(1, Math.ceil(sim.etaSec / 60)) : null;

  const [query, setQuery] = useState("");
  const [results, setResults] = useState<GeocodeResult[]>([]);
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);

  async function handleSearch() {
    if (query.trim().length < 2) return;
    setSearching(true);
    setSearchError(null);
    const { results: found, error } = await searchPlaces(query.trim(), apid);
    setResults(found);
    setSearchError(error ?? (found.length === 0 ? "검색 결과가 없습니다" : null));
    setSearching(false);
  }

  function pick(result: GeocodeResult) {
    onTargetChange({ lat: result.lat, lng: result.lng, label: result.name, mode: "address", etaMin: result.etaMin });
    setResults([]);
  }

  return (
    <section
      className={css({
        display: "flex",
        flexDirection: "column",
        gap: "2.5",
        paddingX: "4",
        paddingY: "3",
        borderWidth: "1px",
        borderColor: "line",
        borderRadius: "panel",
        backgroundColor: "surface",
      })}
    >
      <div className={css({ display: "flex", alignItems: "center", justifyContent: "space-between", gap: "3" })}>
        <div className={css({ display: "flex", flexDirection: "column", gap: "1", minWidth: "0" })}>
          <div className={css({ display: "flex", alignItems: "center", gap: "2", flexWrap: "wrap" })}>
            <span className={css({ fontSize: "sm", fontWeight: "bold", color: "ink" })}>{PHASE_LABEL[phase]}</span>
            <span className={simBadgeStyle}>시뮬레이션 위치</span>
            {sim?.speedup != null && sim.speedup > 1 && (
              <span className={simBadgeStyle}>{Math.round(sim.speedup)}배속</span>
            )}
          </div>
          <span className={css({ fontSize: "xs", color: "ink3" })}>
            {etaMin != null
              ? `도착까지 약 ${etaMin}분 (실제 도로 기준)`
              : phase === "at_hospital"
                ? "병원이 수용 결과를 고를 때까지 병원 앞에서 기다립니다"
                : phase === "rerouting"
                  ? "같은 환자 정보로 넓힌 존의 병원들에 다시 요청했습니다 — 승인한 병원을 이송 승인하세요"
                  : phase === "on_scene"
                    ? callActive
                      ? "통화를 끝내야 현장 종료할 수 있습니다"
                      : "통화를 시작해 병원에 환자 정보를 보내세요"
                    : "위치를 고르지 않으면 기지 근처(약 10분 거리) 무작위 위치로 출동합니다"}
          </span>
        </div>
        <div className={css({ display: "flex", gap: "2", flexShrink: "0" })}>
          {(phase === "on_scene" || phase === "rerouting") && (
            <button type="button" className={dangerButtonStyle} onClick={onSceneEnd} disabled={!canEndScene}>
              현장 종료
            </button>
          )}
          <button type="button" className={primaryButtonStyle} onClick={onDispatch} disabled={!canDispatch}>
            이동
          </button>
        </div>
      </div>

      {canDispatch && (
        <div className={css({ display: "flex", flexDirection: "column", gap: "1.5" })}>
          <div className={css({ display: "flex", alignItems: "center", gap: "2", flexWrap: "wrap" })}>
            <span className={css({ fontSize: "xs", fontWeight: "semibold", color: "ink2" })}>출동 위치</span>
            {target ? (
              <span className={targetChipStyle}>
                {target.mode === "map" ? "지도에서 고른 위치" : target.label}
                {target.etaMin != null && ` · 기지에서 약 ${target.etaMin}분`}
                <button
                  type="button"
                  aria-label="출동 위치 지우기(무작위로)"
                  onClick={() => onTargetChange(null)}
                  className={css({ cursor: "pointer", color: "ink3", _hover: { color: "coral" } })}
                >
                  ×
                </button>
              </span>
            ) : (
              <span className={css({ fontSize: "xs", color: "ink3" })}>무작위 — 주소를 검색하거나 지도를 눌러 고를 수 있습니다</span>
            )}
          </div>
          <form
            className={css({ display: "flex", gap: "2" })}
            onSubmit={(event) => {
              event.preventDefault();
              void handleSearch();
            }}
          >
            <input
              className={inputStyle}
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="주소 또는 장소 이름 (예: 코엑스, 강남구 테헤란로 152)"
              maxLength={60}
            />
            <button
              type="submit"
              className={cx(secondaryButtonStyle, css({ whiteSpace: "nowrap", flexShrink: "0" }))}
              disabled={searching || query.trim().length < 2}
            >
              {searching ? "검색 중" : "검색"}
            </button>
          </form>
          {searchError && <span className={css({ fontSize: "xs", color: "coral" })}>{searchError}</span>}
          {results.length > 0 && (
            <ul
              className={cx(
                css({
                  display: "flex",
                  flexDirection: "column",
                  borderWidth: "1px",
                  borderColor: "line",
                  borderRadius: "field",
                  maxHeight: "176px",
                  overflowY: "auto",
                }),
                thinScrollbarStyle,
              )}
            >
              {results.map((result) => (
                <li key={`${result.lat},${result.lng},${result.name}`}>
                  <button type="button" className={resultButtonStyle} onClick={() => pick(result)}>
                    <span>
                      <span className={css({ fontWeight: "semibold" })}>{result.name}</span>
                      {result.address !== result.name && (
                        <span className={css({ color: "ink3", marginLeft: "1.5" })}>{result.address}</span>
                      )}
                    </span>
                    {result.etaMin != null && (
                      <span className={css({ color: "ink3", flexShrink: "0" })}>기지에서 약 {result.etaMin}분</span>
                    )}
                  </button>
                </li>
              ))}
            </ul>
          )}
          <span className={css({ fontSize: "2xs", color: "ink3" })}>
            시연용 기능입니다. 검색어는 위치를 찾는 데만 쓰고 저장하지 않습니다(검색과 길찾기에 카카오가 쓰입니다).
          </span>
        </div>
      )}
    </section>
  );
}
