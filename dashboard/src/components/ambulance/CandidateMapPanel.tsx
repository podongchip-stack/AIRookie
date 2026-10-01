"use client";

import { useEffect, useRef } from "react";
import { css } from "styled-system/css";
import { Panel } from "@/components/layout/Panel";
import { Tag } from "@/components/hospital/Tag";
import { useKakaoMapScript } from "@/hooks/use-kakao-map-script";
import { createColoredMarkerImage, createLabelOverlay } from "@/lib/kakao-map-markers";
import { fetchRoadPath } from "@/lib/route";
import type { AmbulanceSimState, HospitalCandidate, HubMatchResult, SceneCandidates } from "@/types/dashboard";

const sideBoxStyle = css({
  flex: "1",
  borderWidth: "1px",
  borderColor: "line",
  borderRadius: "field",
  paddingX: "3.5",
  paddingY: "3",
});

// 구급차 위치는 hub가 내려주는 ambulanceGps(2026-09-24 신설)를 쓴다. 구버전 hub라 그
// 값이 없을 때만 후보 병원들의 중심 좌표에서 살짝 떨어진 자리를 임시 표시 위치로 쓴다.
const PLACEHOLDER_AMBULANCE_OFFSET = { lat: 0.014, lng: -0.012 };

// 출동 시뮬레이션 지도 기본 중심(서울시청). 사건·위치가 아직 없을 때만 쓴다.
const DEFAULT_CENTER = { lat: 37.5665, lng: 126.978 };
const SIM_MOVING_PHASES = new Set(["dispatching", "transporting", "returning"]);

function markerColorHex(hospital: Pick<HospitalCandidate, "status">, isConfirmed: boolean): string {
  if (isConfirmed) return "#0E9F6E"; // mint
  if (hospital.status === "rejected") return "#CBD5E1"; // lineStrong
  if (hospital.status === "approved" || hospital.status === "confirmed") return "#1E5FA8"; // navy
  return "#66778A"; // ink3
}

// hub가 병원별 실제 gps(lat/lng)를 내려주므로 그대로 실좌표에 마커를 찍는다.
// 2026-08-11: 정규화된 좌표를 %로 흩뿌려 그리던 가짜 지도를 실제 카카오맵으로 교체.
export function CandidateMapPanel({
  data,
  confirmedHospitalId,
  sim = null,
  scene = null,
}: {
  data: HubMatchResult | null;
  confirmedHospitalId: string | null;
  // 출동 시뮬레이션 상태(2026-10-01). 있으면 구급차 마커·경로는 이 값으로 따로 그린다 — 1초마다
  // 오는 위치에 병원 마커 전체를 다시 그리고 화면 범위를 다시 맞추지 않게.
  sim?: AmbulanceSimState | null;
  // 매칭 전 현장 후보(거리순). 매칭 결과가 없을 때 병원 위치만 보여준다.
  scene?: SceneCandidates | null;
}) {
  const hospitals: Pick<HospitalCandidate, "hospitalId" | "name" | "gps" | "status">[] =
    data?.hospitals ?? scene?.hospitals.map((h) => ({ ...h, status: "pending" as const })) ?? [];
  const simActive = sim != null;
  const ambulanceGps = simActive ? null : data?.ambulanceGps ?? scene?.ambulanceGps ?? null;
  const confirmedHospital = data?.hospitals.find((h) => h.hospitalId === confirmedHospitalId) ?? null;
  // 이송 중이면 시뮬레이션이 받아 둔 경로의 남은 비율로 계산한 도착 시간(실제 도로 기준)을 쓴다.
  const confirmedEtaMin =
    sim?.phase === "transporting" && sim.etaSec != null
      ? Math.max(1, Math.ceil(sim.etaSec / 60))
      : confirmedHospital?.etaMin ?? null;
  const { ready, error } = useKakaoMapScript();

  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<kakao.maps.Map | null>(null);
  const hospitalMarkersRef = useRef<{ marker: kakao.maps.Marker; label: kakao.maps.CustomOverlay }[]>([]);
  const ambulanceMarkerRef = useRef<kakao.maps.Marker | null>(null);
  const ambulanceLabelRef = useRef<kakao.maps.CustomOverlay | null>(null);
  const polylineRef = useRef<kakao.maps.Polyline | null>(null);
  const simMarkerRef = useRef<kakao.maps.Marker | null>(null);
  const simLabelRef = useRef<kakao.maps.CustomOverlay | null>(null);
  const simPathRef = useRef<kakao.maps.Polyline | null>(null);
  const simPinsRef = useRef<{ marker: kakao.maps.Marker; label: kakao.maps.CustomOverlay }[]>([]);

  function ensureMap(center: { lat: number; lng: number }): kakao.maps.Map | null {
    if (!containerRef.current) return null;
    if (!mapRef.current) {
      mapRef.current = new window.kakao.maps.Map(containerRef.current, {
        center: new window.kakao.maps.LatLng(center.lat, center.lng),
        level: 6,
      });
    }
    return mapRef.current;
  }

  useEffect(() => {
    if (!ready || !containerRef.current) return;

    // 후보가 없어지면(hospitals가 빈 배열) 예전엔 여기서 그냥 return해버려서
    // 마지막으로 그려둔 마커·경로가 지도에 그대로 남아있었다(병원 대시보드
    // MapPanel에서 2026-08-12 먼저 발견된 것과 같은 종류의 문제 — 후보가 없어졌으면
    // 지도도 같이 비워야 한다).
    if (hospitals.length === 0) {
      hospitalMarkersRef.current.forEach(({ marker, label }) => {
        marker.setMap(null);
        label.setMap(null);
      });
      hospitalMarkersRef.current = [];
      ambulanceMarkerRef.current?.setMap(null);
      ambulanceMarkerRef.current = null;
      ambulanceLabelRef.current?.setMap(null);
      ambulanceLabelRef.current = null;
      polylineRef.current?.setMap(null);
      polylineRef.current = null;
      return;
    }

    const { kakao } = window;

    const lats = hospitals.map((h) => h.gps.lat);
    const lngs = hospitals.map((h) => h.gps.lng);
    const centerLat = lats.reduce((sum, v) => sum + v, 0) / lats.length;
    const centerLng = lngs.reduce((sum, v) => sum + v, 0) / lngs.length;
    const ambulancePos = ambulanceGps
      ? new kakao.maps.LatLng(ambulanceGps.lat, ambulanceGps.lng)
      : new kakao.maps.LatLng(
          centerLat + PLACEHOLDER_AMBULANCE_OFFSET.lat,
          centerLng + PLACEHOLDER_AMBULANCE_OFFSET.lng,
        );

    if (!mapRef.current) {
      mapRef.current = new kakao.maps.Map(containerRef.current, {
        center: new kakao.maps.LatLng(centerLat, centerLng),
        level: 7,
      });
    }
    const map = mapRef.current;

    hospitalMarkersRef.current.forEach(({ marker, label }) => {
      marker.setMap(null);
      label.setMap(null);
    });

    const bounds = new kakao.maps.LatLngBounds();
    hospitalMarkersRef.current = hospitals.map((hospital) => {
      const isConfirmed = hospital.hospitalId === confirmedHospitalId;
      const pos = new kakao.maps.LatLng(hospital.gps.lat, hospital.gps.lng);
      bounds.extend(pos);
      const marker = new kakao.maps.Marker({
        position: pos,
        map,
        title: hospital.name,
        image: createColoredMarkerImage(markerColorHex(hospital, isConfirmed)),
        zIndex: isConfirmed ? 10 : 1,
      });
      const label = createLabelOverlay(pos, hospital.name, { muted: hospital.status === "rejected" && !isConfirmed });
      label.setMap(map);
      return { marker, label };
    });

    ambulanceMarkerRef.current?.setMap(null);
    ambulanceLabelRef.current?.setMap(null);
    ambulanceMarkerRef.current = null;
    ambulanceLabelRef.current = null;
    polylineRef.current?.setMap(null);
    polylineRef.current = null;
    if (simActive) {
      // 구급차 마커·경로는 시뮬레이션 레이어(아래 두 effect)가 그린다.
      map.setBounds(bounds);
      return;
    }
    ambulanceMarkerRef.current = new kakao.maps.Marker({
      position: ambulancePos,
      map,
      title: ambulanceGps ? "구급차 현재 위치" : "구급차 현재 위치(임시 표시)",
      image: createColoredMarkerImage("#1E5FA8"),
      zIndex: 20,
    });
    ambulanceLabelRef.current = createLabelOverlay(ambulancePos, "구급차 현재 위치");
    ambulanceLabelRef.current.setMap(map);
    bounds.extend(ambulancePos);

    if (confirmedHospital) {
      const confirmedPos = new kakao.maps.LatLng(confirmedHospital.gps.lat, confirmedHospital.gps.lng);
      polylineRef.current = new kakao.maps.Polyline({
        path: [ambulancePos, confirmedPos],
        strokeWeight: 3,
        strokeColor: "#1E5FA8",
        strokeOpacity: 0.85,
        strokeStyle: "shortdash",
      });
      polylineRef.current.setMap(map);
    } else {
      polylineRef.current = null;
    }

    map.setBounds(bounds);

    // 이송 확정 병원까지 도로 경로를 받아오면 직선(점선)을 실제 길(실선)로 바꾼다. 받는 사이
    // 사건·확정 병원이 바뀌었으면(cancelled) 늦게 온 응답은 버린다. 실패하면 직선 그대로.
    let cancelled = false;
    if (confirmedHospital && data && ambulanceGps) {
      fetchRoadPath(data.caseId, confirmedHospital.hospitalId).then((path) => {
        if (cancelled || !path) return;
        polylineRef.current?.setMap(null);
        polylineRef.current = new kakao.maps.Polyline({
          path: path.map(([lat, lng]) => new kakao.maps.LatLng(lat, lng)),
          strokeWeight: 4,
          strokeColor: "#1E5FA8",
          strokeOpacity: 0.9,
          strokeStyle: "solid",
        });
        polylineRef.current.setMap(map);
      });
    }
    return () => {
      cancelled = true;
    };
    // hospitals는 매 렌더 새 배열일 수 있어 참조 대신 caseId+길이로 변경을 감지한다.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, data?.caseId, scene?.caseId, hospitals.length, confirmedHospitalId, ambulanceGps?.lat, ambulanceGps?.lng, simActive]);

  // 시뮬레이션: 상태가 바뀔 때만 경로 선·현장/기지 표시를 다시 그리고 화면을 맞춘다.
  useEffect(() => {
    if (!ready) return;
    simPathRef.current?.setMap(null);
    simPathRef.current = null;
    simPinsRef.current.forEach(({ marker, label }) => {
      marker.setMap(null);
      label.setMap(null);
    });
    simPinsRef.current = [];
    if (!sim) return;
    const { kakao } = window;
    const map = ensureMap(sim.gps ?? sim.base ?? DEFAULT_CENTER);
    if (!map) return;
    const bounds = new kakao.maps.LatLngBounds();
    const pin = (p: { lat: number; lng: number }, text: string, color: string) => {
      const pos = new kakao.maps.LatLng(p.lat, p.lng);
      bounds.extend(pos);
      const marker = new kakao.maps.Marker({ position: pos, map, title: text, image: createColoredMarkerImage(color), zIndex: 15 });
      const label = createLabelOverlay(pos, text);
      label.setMap(map);
      simPinsRef.current.push({ marker, label });
    };
    pin(sim.base, "기지", "#66778A");
    if (sim.incident && (sim.phase === "dispatching" || sim.phase === "on_scene")) pin(sim.incident, "환자 발생 위치", "#E5484D");
    if (sim.path && SIM_MOVING_PHASES.has(sim.phase)) {
      const path = sim.path.map(([lat, lng]) => new kakao.maps.LatLng(lat, lng));
      path.forEach((p) => bounds.extend(p));
      simPathRef.current = new kakao.maps.Polyline({
        path,
        strokeWeight: 4,
        strokeColor: sim.phase === "returning" ? "#66778A" : "#1E5FA8",
        strokeOpacity: 0.85,
        strokeStyle: "solid",
      });
      simPathRef.current.setMap(map);
    }
    if (hospitals.length === 0 || SIM_MOVING_PHASES.has(sim.phase)) map.setBounds(bounds);
    // 상태·사건·확정 병원·경로가 바뀔 때만 다시 그린다(1초 위치 갱신엔 반응하지 않음).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, sim?.phase, sim?.caseId, sim?.hospitalId, sim?.path?.length]);

  // 시뮬레이션: 1초마다 구급차 마커만 옮긴다.
  useEffect(() => {
    if (!ready) return;
    if (!sim?.gps) {
      simMarkerRef.current?.setMap(null);
      simLabelRef.current?.setMap(null);
      simMarkerRef.current = null;
      simLabelRef.current = null;
      return;
    }
    const { kakao } = window;
    const map = ensureMap(sim.gps);
    if (!map) return;
    const pos = new kakao.maps.LatLng(sim.gps.lat, sim.gps.lng);
    if (!simMarkerRef.current) {
      simMarkerRef.current = new kakao.maps.Marker({
        position: pos, map, title: "구급차 (시뮬레이션 위치)", image: createColoredMarkerImage("#1E5FA8"), zIndex: 30,
      });
      simLabelRef.current = createLabelOverlay(pos, "구급차 (시뮬레이션)");
      simLabelRef.current.setMap(map);
    } else {
      simMarkerRef.current.setPosition(pos);
      simLabelRef.current?.setPosition(pos);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, sim?.gps?.lat, sim?.gps?.lng]);

  return (
    <Panel
      title="지도 · 네비게이션"
      subtitle="데이터를 보낸 병원 전체 위치"
      badge={<Tag source="rule">GPS · 카카오내비</Tag>}
    >
      <div className={css({ display: "flex", flexDirection: "column", gap: "3.5", flex: "1", minHeight: "0" })}>
        <div
          className={css({
            position: "relative",
            flex: "1",
            minWidth: "240px",
            minHeight: "160px",
            borderWidth: "1px",
            borderColor: "line",
            borderRadius: "field",
            backgroundColor: "#EDF2F7",
            overflow: "hidden",
          })}
        >
          {/* 카카오맵이 이 div 안쪽 DOM을 직접 그리므로, React가 관리하는 자식은
              여기 안 두고 아래 오버레이 div를 형제로 절대배치한다. */}
          <div
            ref={containerRef}
            role="img"
            aria-label="구급차 현재 위치와 데이터를 보낸 병원들의 위치를 표시한 지도"
            // zIndex:0으로 별도 쌓임 맥락을 만들어 카카오맵 내부 z-index가 형제인
            // 오버레이 위로 새어나가지 않게 한다(병원 대시보드 MapPanel과 동일한
            // 이유, 2026-08-12).
            className={css({ position: "absolute", inset: "0", zIndex: "0" })}
          />
          {/* 출동 시뮬레이션 중엔 병원 후보가 없어도 지도를 가리지 않는다 — 출동 중 움직이는 구급차를 보여야 한다. */}
          {(!ready || error || (hospitals.length === 0 && !sim)) && (
            <div
              className={css({
                position: "absolute",
                inset: "0",
                zIndex: "1",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                textAlign: "center",
                paddingX: "4",
                fontSize: "xs",
                color: error ? "coral" : "ink3",
                backgroundColor: "#EDF2F7",
              })}
            >
              {error ?? (hospitals.length === 0 ? "수신 대기 중..." : "지도를 불러오는 중...")}
            </div>
          )}
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
                {confirmedEtaMin != null ? `${confirmedEtaMin}분` : "-"}
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
