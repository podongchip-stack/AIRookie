"use client";

import { useEffect, useRef } from "react";
import { css } from "styled-system/css";
import { useKakaoMapScript } from "@/hooks/use-kakao-map-script";
import {
  createAmbulanceMarkerImage,
  createColoredMarkerImage,
  createLabelOverlay,
  escapeHtml,
} from "@/lib/kakao-map-markers";
import {
  MAP_COLORS, PHASE_SHORT, STATUS_ICON, STATUS_SHORT, requestColor, statusInk, topStatus, type HospitalRequest,
} from "@/lib/monitor";
import type { AmbulanceSimState, MapOverview, MonitorCase } from "@/types/dashboard";

// 관제 지도(2026-10-03). 서울 지도에 병원(남색 원)·구급차(주황 사각형)를 이름과 함께 찍고, 구급차는 hub가
// 보내는 출동 시뮬레이션 위치로 1초마다 옮긴다. 환자 요청이 온 병원은 마커 위에 빨간 표시를 달고, 그 병원만
// 눌러서 병원 대시보드를 연다. 사건마다 지금 요청 중인 존(거절 비율로 넓혀진 범위 포함)을 점선 원으로 그린다.
//
// 카카오맵 객체는 React 상태가 아니라 ref에 둔다(마커 수백 개를 매 렌더 다시 만들지 않게). 효과마다 바뀐 부분만
// 지도에 반영한다.

const SEOUL_CENTER = { lat: 37.5565, lng: 126.99 };
const INITIAL_LEVEL = 8;
// 이 확대 단계 이하(더 확대)일 때만 모든 병원 이름을 보인다 — 서울 전체를 볼 때 병원 이름 50여 개가 겹치지
// 않게. 환자 요청이 온 병원과 구급차 이름은 항상 보인다. 축소 상태에선 병원 마커를 누르면 그 병원 이름만
// 뜨고(2026-10-03), 지도 빈 곳을 누르면 사라진다.
const LABEL_MAX_LEVEL = 7;
const MOVING_PHASES = new Set(["dispatching", "transporting", "returning"]);

type HospitalLayer = { marker: kakao.maps.Marker; label: kakao.maps.CustomOverlay };
type AmbulanceLayer = { marker: kakao.maps.Marker; label: kakao.maps.CustomOverlay; text: string };

// 요청 표시는 짧게(상태만) — 요청 병원이 존 확장으로 20곳 가까이 되면 긴 표시는 서로 겹쳐 지도를 가렸다.
// 어느 구급대의 요청인지는 마우스를 올리면(title) 보인다. 색은 상태별(노랑·연두·빨강·초록).
function badgeElement(requests: HospitalRequest[], onClick: () => void): HTMLElement {
  const status = topStatus(requests);
  const only = requests.length === 1 ? requests[0] : null;
  // 병상이 없어 불가(E-Gen)면 "병상 없음"으로 — 병원이 직접 거절한 것과 구분한다(2026-10-03)
  const label = only && only.status === "rejected" && only.note?.startsWith("병상 없음") ? "병상 없음" : STATUS_SHORT[status];
  const text = requests.length > 1 ? `${STATUS_ICON[status]} ${requests.length}건` : `${STATUS_ICON[status]} ${label}`;
  const el = document.createElement("button");
  el.type = "button";
  el.title =
    requests.map((r) => `${r.ambulanceName} · ${STATUS_SHORT[r.status]}${r.note ? `(${r.note})` : ""} · 존 ${r.zone}`).join("\n") +
    "\n눌러서 병원 대시보드 열기";
  el.style.cssText =
    `transform:translateY(-14px);cursor:pointer;white-space:nowrap;font-size:11px;font-weight:700;` +
    `color:${statusInk(status)};background:${requestColor(requests)};border:2px solid #FFFFFF;border-radius:999px;` +
    `padding:1px 7px;box-shadow:0 1px 4px rgba(22,34,46,.35);`;
  el.textContent = text;
  el.onclick = (event) => {
    event.stopPropagation();
    onClick();
  };
  return el;
}

function zoneLabel(text: string): string {
  return (
    `<div style="font-size:11px;font-weight:700;white-space:nowrap;color:${MAP_COLORS.zone};background:#FFFFFF;` +
    `border:1px dashed ${MAP_COLORS.zone};padding:1px 6px;border-radius:6px;">${escapeHtml(text)}</div>`
  );
}

export function MonitorMapPanel({
  overview,
  cases,
  ambulanceSim,
  requests,
  onOpenHospital,
}: {
  overview: MapOverview | null;
  cases: Record<string, MonitorCase>;
  ambulanceSim: Record<string, AmbulanceSimState>;
  requests: Map<string, HospitalRequest[]>;
  onOpenHospital: (hospitalId: string) => void;
}) {
  const { ready, error } = useKakaoMapScript();
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<kakao.maps.Map | null>(null);
  const hospitalsRef = useRef(new Map<string, HospitalLayer>());
  const badgesRef = useRef(new Map<string, kakao.maps.CustomOverlay>());
  const ambulancesRef = useRef(new Map<string, AmbulanceLayer>());
  const pathsRef = useRef(new Map<string, { line: kakao.maps.Polyline; key: string }>());
  const incidentsRef = useRef(new Map<string, { overlay: kakao.maps.CustomOverlay; key: string }>());
  const zonesRef = useRef(new Map<string, { circle: kakao.maps.Circle; label: kakao.maps.CustomOverlay }>());
  // 카카오 이벤트 핸들러는 한 번 걸어 두고, 최신 값은 ref로 읽는다.
  const requestsRef = useRef(requests);
  // 축소 상태에서 눌러서 이름을 띄운 병원
  const pickedRef = useRef<string | null>(null);
  const onOpenRef = useRef(onOpenHospital);
  useEffect(() => {
    requestsRef.current = requests;
    onOpenRef.current = onOpenHospital;
  }, [requests, onOpenHospital]);

  // 병원 이름은 확대했을 때만(환자 요청이 온 병원은 항상) 보인다.
  function applyLabelVisibility() {
    const map = mapRef.current;
    if (!map) return;
    const showAll = map.getLevel() <= LABEL_MAX_LEVEL;
    hospitalsRef.current.forEach((layer, id) => {
      layer.label.setMap(showAll || requestsRef.current.has(id) || pickedRef.current === id ? map : null);
    });
  }

  function ensureMap(): kakao.maps.Map | null {
    if (mapRef.current) return mapRef.current;
    if (!ready || !containerRef.current) return null;
    const { kakao } = window;
    const map = new kakao.maps.Map(containerRef.current, {
      center: new kakao.maps.LatLng(SEOUL_CENTER.lat, SEOUL_CENTER.lng),
      level: INITIAL_LEVEL,
    });
    kakao.maps.event.addListener(map, "zoom_changed", applyLabelVisibility);
    kakao.maps.event.addListener(map, "click", () => {
      if (pickedRef.current === null) return;
      pickedRef.current = null;
      applyLabelVisibility();
    });
    mapRef.current = map;
    return map;
  }

  // ── 병원 마커·이름 (병원 목록이 바뀔 때만) ──
  useEffect(() => {
    const map = ensureMap();
    if (!map || !overview) return;
    const { kakao } = window;
    const layers = hospitalsRef.current;
    const ids = new Set(overview.hospitals.map((h) => h.hospitalId));
    layers.forEach((layer, id) => {
      if (!ids.has(id)) {
        layer.marker.setMap(null);
        layer.label.setMap(null);
        layers.delete(id);
      }
    });
    for (const hospital of overview.hospitals) {
      if (layers.has(hospital.hospitalId)) continue;
      const pos = new kakao.maps.LatLng(hospital.gps.lat, hospital.gps.lng);
      const marker = new kakao.maps.Marker({
        position: pos,
        map,
        title: hospital.emergencyLevel ? `${hospital.name} (${hospital.emergencyLevel})` : hospital.name,
        image: createColoredMarkerImage(MAP_COLORS.hospital, 18),
        zIndex: 1,
      });
      kakao.maps.event.addListener(marker, "click", () => {
        // 환자 요청이 온 병원은 대시보드를 열고, 나머지는 이름만 띄운다(다시 누르면 숨김).
        if (requestsRef.current.has(hospital.hospitalId)) {
          onOpenRef.current(hospital.hospitalId);
          return;
        }
        pickedRef.current = pickedRef.current === hospital.hospitalId ? null : hospital.hospitalId;
        applyLabelVisibility();
      });
      layers.set(hospital.hospitalId, { marker, label: createLabelOverlay(pos, hospital.name) });
    }
    applyLabelVisibility();
    // ensureMap·applyLabelVisibility는 ref만 읽는다.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, overview?.hospitals]);

  // ── 환자 요청 표시 (사건 요약이 바뀔 때) ──
  useEffect(() => {
    const map = ensureMap();
    if (!map || !overview) return;
    const { kakao } = window;
    badgesRef.current.forEach((badge) => badge.setMap(null));
    badgesRef.current.clear();
    hospitalsRef.current.forEach((layer, id) => {
      const list = requests.get(id);
      layer.marker.setImage(
        list ? createColoredMarkerImage(requestColor(list), 26) : createColoredMarkerImage(MAP_COLORS.hospital, 18),
      );
      layer.marker.setZIndex(list ? 20 : 1);
    });
    requests.forEach((list, id) => {
      const hospital = overview.hospitals.find((h) => h.hospitalId === id);
      if (!hospital) return;
      const badge = new kakao.maps.CustomOverlay({
        position: new kakao.maps.LatLng(hospital.gps.lat, hospital.gps.lng),
        content: badgeElement(list, () => onOpenRef.current(id)),
        yAnchor: 1,
        // 아직 답해야 할(판단 대기) 병원 표시가 거절 병원 표시 위에 오게
        zIndex: 40 + (topStatus(list) === "rejected" ? 0 : 5),
        clickable: true,
      });
      badge.setMap(map);
      badgesRef.current.set(id, badge);
    });
    applyLabelVisibility();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, overview?.hospitals, requests]);

  // ── 구급차 마커·이름·이동 경로·사고 현장 (1초마다 위치가 온다) ──
  useEffect(() => {
    const map = ensureMap();
    if (!map || !overview) return;
    const { kakao } = window;
    const seen = new Set<string>();
    for (const ambulance of overview.ambulances) {
      seen.add(ambulance.apid);
      const sim = ambulanceSim[ambulance.apid];
      const gps = sim?.gps ?? ambulance.gps;
      const pos = new kakao.maps.LatLng(gps.lat, gps.lng);
      const phase = sim ? `${PHASE_SHORT[sim.phase]}${sim.paused ? " · 정지" : ""}` : null;
      const text = phase ? `${ambulance.name} · ${phase}` : ambulance.name;
      let layer = ambulancesRef.current.get(ambulance.apid);
      if (!layer) {
        const marker = new kakao.maps.Marker({
          position: pos, map, title: `${ambulance.name} (시뮬레이션 위치)`,
          image: createAmbulanceMarkerImage(MAP_COLORS.ambulance), zIndex: 50,
        });
        layer = { marker, label: createLabelOverlay(pos, text), text };
        layer.label.setZIndex(51);
        layer.label.setMap(map);
        ambulancesRef.current.set(ambulance.apid, layer);
      } else {
        layer.marker.setPosition(pos);
        if (layer.text !== text) {
          layer.label.setMap(null);
          layer.label = createLabelOverlay(pos, text);
          layer.label.setZIndex(51);
          layer.label.setMap(map);
          layer.text = text;
        } else {
          layer.label.setPosition(pos);
        }
      }

      // 이동 경로: 움직이는 구간만. 경로가 바뀔 때만 다시 그린다.
      const path = sim && MOVING_PHASES.has(sim.phase) && sim.path && sim.path.length > 1 ? sim.path : null;
      const pathKey = path ? `${sim?.phase}:${path.length}:${path[0].join(",")}` : "";
      const drawn = pathsRef.current.get(ambulance.apid);
      if (drawn && drawn.key !== pathKey) {
        drawn.line.setMap(null);
        pathsRef.current.delete(ambulance.apid);
      }
      if (path && (!drawn || drawn.key !== pathKey)) {
        const line = new kakao.maps.Polyline({
          path: path.map(([lat, lng]) => new kakao.maps.LatLng(lat, lng)),
          strokeWeight: 4, strokeColor: MAP_COLORS.ambulance, strokeOpacity: 0.75, strokeStyle: "solid",
        });
        line.setMap(map);
        pathsRef.current.set(ambulance.apid, { line, key: pathKey });
      }

      // 사고 현장: 출동 중·현장 도착일 때
      const incident = sim && (sim.phase === "dispatching" || sim.phase === "on_scene") ? sim.incident : null;
      const incidentKey = incident ? `${incident.lat},${incident.lng}` : "";
      const shown = incidentsRef.current.get(ambulance.apid);
      if (shown && shown.key !== incidentKey) {
        shown.overlay.setMap(null);
        incidentsRef.current.delete(ambulance.apid);
      }
      if (incident && (!shown || shown.key !== incidentKey)) {
        const overlay = new kakao.maps.CustomOverlay({
          position: new kakao.maps.LatLng(incident.lat, incident.lng),
          content:
            `<div style="transform:translateY(-50%);font-size:11px;font-weight:700;color:#FFFFFF;` +
            `background:${MAP_COLORS.incident};padding:2px 6px;border-radius:6px;white-space:nowrap;">✚ 사고 현장</div>`,
          yAnchor: 0.5,
          zIndex: 45,
        });
        overlay.setMap(map);
        incidentsRef.current.set(ambulance.apid, { overlay, key: incidentKey });
      }
    }
    ambulancesRef.current.forEach((layer, apid) => {
      if (seen.has(apid)) return;
      layer.marker.setMap(null);
      layer.label.setMap(null);
      ambulancesRef.current.delete(apid);
      pathsRef.current.get(apid)?.line.setMap(null);
      pathsRef.current.delete(apid);
      incidentsRef.current.get(apid)?.overlay.setMap(null);
      incidentsRef.current.delete(apid);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, overview?.ambulances, ambulanceSim]);

  // ── 사건별 요청 존 범위 (거절 비율로 넓혀지면 원이 커지고 바깥 존 병원이 요청 표시를 받는다) ──
  useEffect(() => {
    const map = ensureMap();
    if (!map) return;
    const { kakao } = window;
    zonesRef.current.forEach((zone) => {
      zone.circle.setMap(null);
      zone.label.setMap(null);
    });
    zonesRef.current.clear();
    for (const monitorCase of Object.values(cases)) {
      if (!monitorCase.ambulanceGps || monitorCase.zoneActive.length === 0) continue;
      if (monitorCase.hospitals.some((h) => h.status === "confirmed")) continue; // 확정되면 범위 표시는 끝
      const maxZone = Math.max(...monitorCase.zoneActive);
      const radiusKm = maxZone * monitorCase.zoneBandKm;
      const center = new kakao.maps.LatLng(monitorCase.ambulanceGps.lat, monitorCase.ambulanceGps.lng);
      const circle = new kakao.maps.Circle({
        center, radius: radiusKm * 1000, strokeWeight: 2, strokeColor: MAP_COLORS.zone, strokeOpacity: 0.9,
        strokeStyle: "dash", fillColor: MAP_COLORS.zone, fillOpacity: 0.05,
      });
      circle.setMap(map);
      const name = monitorCase.ambulanceName ?? monitorCase.apid ?? "구급차";
      const range = maxZone > 1 ? `존 1~${maxZone}` : "존 1";
      const label = new kakao.maps.CustomOverlay({
        position: new kakao.maps.LatLng(monitorCase.ambulanceGps.lat + radiusKm / 111, monitorCase.ambulanceGps.lng),
        content: zoneLabel(`${name} 요청 범위 · ${range} (${radiusKm}km)${maxZone > 1 ? " · 거절로 확장" : ""}`),
        yAnchor: 1,
        zIndex: 10,
      });
      label.setMap(map);
      zonesRef.current.set(monitorCase.caseId, { circle, label });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, cases]);

  return (
    <div
      className={css({
        position: "relative",
        flex: "1",
        minHeight: "0",
        borderWidth: "1px",
        borderColor: "line",
        borderRadius: "panel",
        overflow: "hidden",
        backgroundColor: "#EDF2F7",
      })}
    >
      {/* 카카오맵이 이 div 안을 직접 그리므로 React 자식은 형제로 둔다(MapPanel과 같은 이유). */}
      <div
        ref={containerRef}
        role="img"
        aria-label="병원·구급차 위치와 환자 요청 현황을 표시한 관제 지도"
        className={css({ position: "absolute", inset: "0", zIndex: "0" })}
      />
      {(!ready || error || !overview) && (
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
            fontSize: "sm",
            color: error ? "coral" : "ink3",
            backgroundColor: "#EDF2F7",
          })}
        >
          {error ?? (!ready ? "지도를 불러오는 중..." : "hub에서 병원·구급차 목록을 받는 중...")}
        </div>
      )}
    </div>
  );
}
