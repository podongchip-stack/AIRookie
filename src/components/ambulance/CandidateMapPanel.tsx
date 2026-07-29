"use client";

import { css } from "styled-system/css";
import { Panel } from "@/components/layout/Panel";
import { Tag } from "@/components/hospital/Tag";
import type { HospitalCandidate, HospitalMatchMessage } from "@/types/dashboard";

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

// 후보 병원을 거리순으로 지도 위 22%~78% 구간에 펼쳐 배치한다 (구급차 마커는 12% 고정).
function positionFor(distance: number, min: number, max: number) {
  if (max === min) return 50;
  return 22 + ((distance - min) / (max - min)) * 56;
}

// 모든 마커가 한 줄에 나란히 찍히면 지도처럼 안 보이므로, 병원별로 세로 위치도
// (id + 순서 기반으로 결정적이게) 흩뿌려 실제 지도처럼 보이게 한다.
function verticalFor(hospitalId: string, index: number) {
  const seed =
    Array.from(hospitalId).reduce((sum, ch) => sum + ch.charCodeAt(0), 0) + index * 17;
  return 18 + (seed % 65);
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
  data: HospitalMatchMessage | null;
  confirmedHospitalId: string | null;
}) {
  const hospitals = data?.hospitals ?? [];
  const confirmedHospital = hospitals.find((h) => h.hospital_id === confirmedHospitalId) ?? null;

  const distances = hospitals.map((h) => h.distance_km);
  const minD = distances.length ? Math.min(...distances) : 0;
  const maxD = distances.length ? Math.max(...distances) : 0;

  const positioned = hospitals.map((hospital, index) => ({
    hospital,
    left: positionFor(hospital.distance_km, minD, maxD),
    top: verticalFor(hospital.hospital_id, index),
  }));
  const confirmedPosition = positioned.find((p) => p.hospital.hospital_id === confirmedHospitalId);

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
            const isConfirmed = hospital.hospital_id === confirmedHospitalId;
            const muted = hospital.status === "rejected" && !isConfirmed;

            return (
              <div
                key={hospital.hospital_id}
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
                {confirmedHospital.eta_min != null ? `${confirmedHospital.eta_min}분` : "-"}
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
              {confirmedHospital ? `${confirmedHospital.distance_km}km` : "-"}
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
