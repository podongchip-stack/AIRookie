"use client";

import { css } from "styled-system/css";
import { Panel } from "@/components/layout/Panel";
import { Tag } from "@/components/hospital/Tag";
import type { HospitalCandidate, HubMatchResult } from "@/types/dashboard";

const mapLabelStyle = css({
  position: "absolute",
  top: "4",
  transform: "translateX(-50%)",
  fontSize: "2xs",
  fontWeight: "semibold",
  whiteSpace: "nowrap",
  backgroundColor: "surface",
  borderWidth: "1px",
  borderColor: "line",
  paddingX: "1.5",
  borderRadius: "chip",
});

const markerDotStyle = css({
  display: "block",
  width: "3.5",
  height: "3.5",
  borderRadius: "full",
  border: "2.5px solid #FFFFFF",
  boxShadow: "0 0 0 1px #CBD5E1",
});

const sideBoxStyle = css({
  flex: "1",
  borderWidth: "1px",
  borderColor: "line",
  borderRadius: "field",
  paddingX: "3.5",
  paddingY: "3",
});

const AMBULANCE_LEFT = 12;
const AMBULANCE_TOP = 50;

// hub가 병원별 실제 gps(lat/lng)를 내려주므로, 위경도를 후보군 범위 안에서 정규화해
// 지도 위 22%~78%(가로) / 18%~82%(세로) 구간에 배치한다 (구급차 마커는 12%/50% 고정 —
// hub 스키마에 구급차 자신의 gps는 없으므로 스타일화된 고정 위치를 유지한다).
function normalize(value: number, min: number, max: number, rangeMin: number, rangeMax: number) {
  if (max === min) return (rangeMin + rangeMax) / 2;
  return rangeMin + ((value - min) / (max - min)) * (rangeMax - rangeMin);
}

function markerColor(hospital: HospitalCandidate, isConfirmed: boolean): string {
  if (isConfirmed) return "mint";
  if (hospital.status === "rejected") return "lineStrong";
  if (hospital.status === "approved" || hospital.status === "confirmed") return "navy";
  return "ink3";
}

export function CandidateMapPanel({
  data,
  confirmedHospitalId,
}: {
  data: HubMatchResult | null;
  confirmedHospitalId: string | null;
}) {
  const hospitals = data?.hospitals ?? [];
  const confirmedHospital = hospitals.find((h) => h.hospitalId === confirmedHospitalId) ?? null;

  const lats = hospitals.map((h) => h.gps.lat);
  const lngs = hospitals.map((h) => h.gps.lng);
  const minLat = lats.length ? Math.min(...lats) : 0;
  const maxLat = lats.length ? Math.max(...lats) : 0;
  const minLng = lngs.length ? Math.min(...lngs) : 0;
  const maxLng = lngs.length ? Math.max(...lngs) : 0;

  const positioned = hospitals.map((hospital) => ({
    hospital,
    left: normalize(hospital.gps.lng, minLng, maxLng, 22, 78),
    // 위도가 클수록(북쪽) 화면 위쪽에 오도록 반전한다.
    top: normalize(hospital.gps.lat, minLat, maxLat, 82, 18),
  }));
  const confirmedPosition = positioned.find((p) => p.hospital.hospitalId === confirmedHospitalId);

  return (
    <Panel
      title="지도 · 네비게이션"
      subtitle="데이터를 보낸 병원 전체 위치"
      badge={<Tag source="rule">GPS · 카카오내비</Tag>}
    >
      <div className={css({ display: "flex", flexDirection: "column", gap: "3.5", flex: "1", minHeight: "0" })}>
        <div
          role="img"
          aria-label="구급차 현재 위치와 데이터를 보낸 병원들의 위치를 표시한 지도"
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
          <svg
            viewBox="0 0 100 100"
            preserveAspectRatio="none"
            className={css({ position: "absolute", inset: "0", width: "100%", height: "100%" })}
          >
            {confirmedPosition && (
              <line
                x1={AMBULANCE_LEFT}
                y1={AMBULANCE_TOP}
                x2={confirmedPosition.left}
                y2={confirmedPosition.top}
                stroke="#1E5FA8"
                strokeWidth="1.5"
                strokeDasharray="5 4"
                strokeLinecap="round"
                vectorEffect="non-scaling-stroke"
              />
            )}
          </svg>

          <div
            className={css({ position: "absolute", transform: "translate(-50%, -50%)" })}
            style={{ left: `${AMBULANCE_LEFT}%`, top: `${AMBULANCE_TOP}%` }}
          >
            <span
              className={`${markerDotStyle} ${css({ backgroundColor: "navy", animation: "nudge 2.6s ease-in-out infinite" })}`}
            />
            <span className={mapLabelStyle} style={{ left: "50%" }}>
              구급차 현재 위치
            </span>
          </div>

          {positioned.map(({ hospital, left, top }) => {
            const isConfirmed = hospital.hospitalId === confirmedHospitalId;
            const muted = hospital.status === "rejected" && !isConfirmed;

            return (
              <div
                key={hospital.hospitalId}
                className={css({ position: "absolute", transform: "translate(-50%, -50%)" })}
                style={{ left: `${left}%`, top: `${top}%` }}
              >
                <span
                  className={css({
                    display: "block",
                    width: "3.5",
                    height: "3.5",
                    borderRadius: "full",
                    border: "2.5px solid #FFFFFF",
                    boxShadow: "0 0 0 1px #CBD5E1",
                    backgroundColor: markerColor(hospital, isConfirmed),
                    opacity: muted ? 0.5 : 1,
                  })}
                />
                <span
                  className={mapLabelStyle}
                  style={{ left: "50%", color: muted ? "var(--colors-ink3)" : "var(--colors-ink)" }}
                >
                  {hospital.name}
                </span>
              </div>
            );
          })}
        </div>

        <div className={css({ width: "100%", display: "flex", flexDirection: "row", gap: "2.5" })}>
          {confirmedHospital ? (
            <div
              className={css({
                flex: "1",
                borderWidth: "1px",
                borderColor: "#B9E4D3",
                backgroundColor: "mintSoft",
                borderRadius: "field",
                paddingX: "3.5",
                paddingY: "3",
              })}
            >
              <div className={css({ fontSize: "xs", color: "#0A7351" })}>본원 도착 예상</div>
              <div
                className={css({
                  fontSize: "xl",
                  fontWeight: "semibold",
                  letterSpacing: "-0.02em",
                  color: "#0A7351",
                })}
              >
                {confirmedHospital.etaMin != null ? `${confirmedHospital.etaMin}분` : "-"}
              </div>
              <div className={css({ fontSize: "2xs", color: "ink3", marginTop: "0.5" })}>
                실시간 교통 반영
              </div>
            </div>
          ) : (
            <div
              className={css({
                flex: "1",
                borderWidth: "1px",
                borderStyle: "dashed",
                borderColor: "lineStrong",
                backgroundColor: "surfaceSub",
                borderRadius: "field",
                paddingX: "3.5",
                paddingY: "3",
                fontSize: "xs",
                color: "ink3",
                textAlign: "center",
              })}
            >
              이송 승인된 병원이 없습니다
              <br />
              승인하면 경로가 표시됩니다
            </div>
          )}

          <div className={sideBoxStyle}>
            <div className={css({ fontSize: "xs", color: "ink" })}>직선 거리</div>
            <div className={css({ fontSize: "xl", fontWeight: "semibold", letterSpacing: "-0.02em", color: "ink" })}>
              {confirmedHospital ? `${confirmedHospital.distanceKm}km` : "-"}
            </div>
          </div>

          <div className={sideBoxStyle}>
            <div className={css({ fontSize: "xs", color: "ink" })}>데이터 전송 병원 수</div>
            <div className={css({ fontSize: "md", fontWeight: "semibold", color: "ink" })}>{hospitals.length}곳</div>
          </div>
        </div>
      </div>
    </Panel>
  );
}
