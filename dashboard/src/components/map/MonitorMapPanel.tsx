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
  AMBULANCE_PHASE_COLORS, MAP_COLORS, PHASE_SHORT, STATUS_ICON, STATUS_SHORT, hospitalLevelColor, requestColor, statusInk, topStatus,
  type HospitalRequest,
} from "@/lib/monitor";
import type { AmbulanceSimState, CallStatus, MapOverview, MonitorCase } from "@/types/dashboard";

// 관제 지도(2026-10-03). 서울 지도에 병원(남색 원 — 이름·접근 코드)·구급차(주황 사각형)를 찍고, 구급차는 hub가
// 보내는 출동 시뮬레이션 위치로 1초마다 옮긴다. 환자 요청이 온 병원은 마커 위에 상태 표시를 단다. 사건마다 지금
// 요청 중인 존(거절 비율로 넓혀진 범위 포함)을 점선 원으로 그린다. 병원 대시보드는 열지 않는다 — 첫 페이지에서
// 접근 코드로 연다(2026-10-03 회의로 분리).
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
// label은 기지 대기 중이면 없다(2026-10-04 — 이름은 사건으로 움직이는 구급차만). color는 마커 색(단계별).
type AmbulanceLayer = { marker: kakao.maps.Marker; label: kakao.maps.CustomOverlay | null; text: string; color: string };

// 요청 표시는 짧게(상태만) — 요청 병원이 존 확장으로 20곳 가까이 되면 긴 표시는 서로 겹쳐 지도를 가렸다.
// 어느 구급대의 요청인지는 마우스를 올리면(title) 보인다. 색은 상태별(노랑·연두·빨강·초록).
function badgeElement(requests: HospitalRequest[]): HTMLElement {
  const status = topStatus(requests);
  const only = requests.length === 1 ? requests[0] : null;
  // 병상이 없어 불가(E-Gen)면 "병상 없음"으로 — 병원이 직접 거절한 것과 구분한다(2026-10-03)
  const label = only && only.status === "rejected" && only.note?.startsWith("병상 없음") ? "병상 없음" : STATUS_SHORT[status];
  const text = requests.length > 1 ? `${STATUS_ICON[status]} ${requests.length}건` : `${STATUS_ICON[status]} ${label}`;
  const el = document.createElement("div");
  el.title = requests
    .map((r) => `${r.ambulanceName} · ${STATUS_SHORT[r.status]}${r.note ? `(${r.note})` : ""} · 존 ${r.zone}`)
    .join("\n");
  el.style.cssText =
    `transform:translateY(-14px);cursor:default;white-space:nowrap;font-size:11px;font-weight:700;` +
    `color:${statusInk(status)};background:${requestColor(requests)};border:2px solid #FFFFFF;border-radius:999px;` +
    `padding:1px 7px;box-shadow:0 1px 4px rgba(22,34,46,.35);`;
  el.textContent = text;
  return el;
}

// 구급대가 휴대폰으로 이 병원에 건 통화(2026-10-03, 연출) — 요청 표시보다 한 칸 위에 띄운다.
function callBadgeElement(calls: CallStatus[]): HTMLElement {
  const el = document.createElement("div");
  el.textContent = calls.length > 1 ? `📞 통화 ${calls.length}건` : `📞 ${calls[0].ambulanceName ?? calls[0].apid} 통화 중`;
  el.style.cssText =
    `transform:translateY(-36px);white-space:nowrap;font-size:11px;font-weight:700;color:#FFFFFF;` +
    `background:#0E9F6E;border:2px solid #FFFFFF;border-radius:999px;padding:1px 7px;` +
    `box-shadow:0 1px 4px rgba(22,34,46,.35);`;
  return el;
}

// 병원 이름표 — 이름·접근 코드(H-<hpid>)·병상 상태를 같이 보여준다(2026-10-04 병상 추가 —
// 관제는 모든 병원의 현재 상태를 봐야 한다). 만실(0 확인)은 빨강, 미상은 회색("미상 ≠ 만실" 원칙).
// 이송 중(이 병원으로 확정돼 아직 도착 전인 환자, TTL 오버레이)이 있으면 함께 표시 — hub가 이 수만큼
// 순위를 뒤로 밀어 다음 환자를 분산시키는 중이라는 뜻이다(쏠림 방지 장치의 작동 표시).
function hospitalLabel(name: string, hospitalId: string, inFlight = 0, hospital?: MapHospitalInfo): string {
  const load =
    inFlight > 0 ? ` <span style="color:#B87514;font-weight:700;">🚑 이송 중 ${inFlight}건</span>` : "";
  let beds = "";
  if (hospital && hospital.bedCountUnknown !== undefined) {
    beds = hospital.bedCountUnknown
      ? ` <span style="color:#8A94A0;">병상 미상</span>`
      : (hospital.availableBedCount ?? 0) > 0
        ? ` <span style="color:#0E9F6E;font-weight:700;">병상 ${hospital.availableBedCount}</span>`
        : ` <span style="color:#D93F35;font-weight:700;">만실</span>`;
  }
  return (
    `<div style="transform:translateY(14px);font-size:11px;font-weight:600;white-space:nowrap;` +
    `background:#FFFFFF;border:1px solid #E2E8EF;padding:1px 6px;border-radius:6px;color:#16222E;">` +
    `${escapeHtml(name)} <span style="color:#1E5FA8;font-weight:700;">H-${escapeHtml(hospitalId)}</span>${beds}${load}</div>`
  );
}

// 확인된 만실(병상 0, 미상 아님)이면 등급 색 대신 회색 — 관제가 "지금 못 받는 병원"을 한눈에 거른다
function markerFill(hospital: { emergencyLevel?: string | null; availableBedCount?: number; bedCountUnknown?: boolean }): string {
  const full = hospital.bedCountUnknown === false && (hospital.availableBedCount ?? 0) <= 0;
  return full ? MAP_COLORS.full : hospitalLevelColor(hospital.emergencyLevel);
}

type MapHospitalInfo = { availableBedCount?: number; bedCountUnknown?: boolean };

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
  calls = [],
  focus = null,
}: {
  overview: MapOverview | null;
  cases: Record<string, MonitorCase>;
  ambulanceSim: Record<string, AmbulanceSimState>;
  requests: Map<string, HospitalRequest[]>;
  // 지금 진행 중인 통화(state "calling")
  calls?: CallStatus[];
  // 사건 선택(2026-10-04) — 왼쪽에서 사건을 클릭하면 그 사건 중심으로 지도를 당긴다.
  // key가 바뀔 때만 이동한다(같은 사건을 보는 동안 지도 조작을 방해하지 않게).
  focus?: { lat: number; lng: number; key: string } | null;
}) {
  const { ready, error } = useKakaoMapScript();
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<kakao.maps.Map | null>(null);
  const hospitalsRef = useRef(new Map<string, HospitalLayer>());
  const badgesRef = useRef(new Map<string, kakao.maps.CustomOverlay>());
  const callBadgesRef = useRef(new Map<string, kakao.maps.CustomOverlay>());
  const ambulancesRef = useRef(new Map<string, AmbulanceLayer>());
  const pathsRef = useRef(new Map<string, { line: kakao.maps.Polyline; key: string }>());
  const incidentsRef = useRef(new Map<string, { overlay: kakao.maps.CustomOverlay; key: string }>());
  const zonesRef = useRef(new Map<string, { circle: kakao.maps.Circle; label: kakao.maps.CustomOverlay }>());
  // 카카오 이벤트 핸들러는 한 번 걸어 두고, 최신 값은 ref로 읽는다.
  const requestsRef = useRef(requests);
  // 축소 상태에서 눌러서 이름을 띄운 병원
  const pickedRef = useRef<string | null>(null);
  // 병원별 이송 중 건수(map_overview) — 라벨 상시 표시 판정에 쓴다
  const inFlightRef = useRef(new Map<string, number>());
  useEffect(() => {
    requestsRef.current = requests;
  }, [requests]);

  // 병원 이름은 확대했을 때만(환자 요청이 온 병원·이송 중인 병원·눌러서 띄운 병원은 항상) 보인다.
  function isLabelShown(id: string): boolean {
    const map = mapRef.current;
    if (!map) return false;
    return (
      map.getLevel() <= LABEL_MAX_LEVEL ||
      requestsRef.current.has(id) ||
      (inFlightRef.current.get(id) ?? 0) > 0 ||
      pickedRef.current === id
    );
  }

  function applyLabelVisibility() {
    const map = mapRef.current;
    if (!map) return;
    hospitalsRef.current.forEach((layer, id) => {
      layer.label.setMap(isLabelShown(id) ? map : null);
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
        inFlightRef.current.delete(id);
      }
    });
    for (const hospital of overview.hospitals) {
      // 이송 중 건수는 병원 목록이 같아도 확정·도착마다 바뀐다(hub가 그때마다 overview 재전송) —
      // 기존 라벨이면 내용만 갈아끼운다.
      inFlightRef.current.set(hospital.hospitalId, hospital.inFlightCount ?? 0);
      const existing = layers.get(hospital.hospitalId);
      if (existing) {
        existing.label.setContent(hospitalLabel(hospital.name, hospital.hospitalId, hospital.inFlightCount ?? 0, hospital));
        continue;
      }
      const pos = new kakao.maps.LatLng(hospital.gps.lat, hospital.gps.lng);
      const marker = new kakao.maps.Marker({
        position: pos,
        map,
        title: hospital.emergencyLevel ? `${hospital.name} (${hospital.emergencyLevel})` : hospital.name,
        // 등급별 색(2026-10-04): 권역센터(중증)=자홍 · 지역센터(중등)=청록 · 기관(경증)=남색 · 만실=회색
        image: createColoredMarkerImage(markerFill(hospital), 18),
        zIndex: 1,
      });
      // 관제 지도는 병원 대시보드를 열지 않는다(2026-10-03 회의로 분리 — 병원 대시보드는 첫 페이지에서 접근 코드로).
      // 축소 상태라 이름이 안 보이면 마커를 눌러 이름·접근 코드를 띄우고, 다시 누르면 숨긴다.
      kakao.maps.event.addListener(marker, "click", () => {
        pickedRef.current = pickedRef.current === hospital.hospitalId ? null : hospital.hospitalId;
        applyLabelVisibility();
      });
      const label = new kakao.maps.CustomOverlay({
        position: pos,
        content: hospitalLabel(hospital.name, hospital.hospitalId, hospital.inFlightCount ?? 0, hospital),
        yAnchor: 0,
      });
      layers.set(hospital.hospitalId, { marker, label });
    }
    applyLabelVisibility();
    // ensureMap·applyLabelVisibility는 ref만 읽는다.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, overview?.hospitals]);

  // ── 사건 선택 시 지도 이동 (2026-10-04) ──
  useEffect(() => {
    const map = ensureMap();
    if (!map || !focus) return;
    const { kakao } = window;
    map.setLevel(6);
    map.setCenter(new kakao.maps.LatLng(focus.lat, focus.lng));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, focus?.key]);

  // ── 환자 요청 표시 (사건 요약이 바뀔 때) ──
  useEffect(() => {
    const map = ensureMap();
    if (!map || !overview) return;
    const { kakao } = window;
    badgesRef.current.forEach((badge) => badge.setMap(null));
    badgesRef.current.clear();
    hospitalsRef.current.forEach((layer, id) => {
      const list = requests.get(id);
      const hospital = overview.hospitals.find((h) => h.hospitalId === id);
      layer.marker.setImage(
        list
          ? createColoredMarkerImage(requestColor(list), 26)
          : createColoredMarkerImage(hospital ? markerFill(hospital) : MAP_COLORS.hospital, 18),
      );
      layer.marker.setZIndex(list ? 20 : 1);
    });
    requests.forEach((list, id) => {
      const hospital = overview.hospitals.find((h) => h.hospitalId === id);
      if (!hospital) return;
      const badge = new kakao.maps.CustomOverlay({
        position: new kakao.maps.LatLng(hospital.gps.lat, hospital.gps.lng),
        content: badgeElement(list),
        yAnchor: 1,
        // 아직 답해야 할(판단 대기) 병원 표시가 거절 병원 표시 위에 오게
        zIndex: 40 + (topStatus(list) === "rejected" ? 0 : 5),
      });
      badge.setMap(map);
      badgesRef.current.set(id, badge);
    });
    applyLabelVisibility();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, overview?.hospitals, requests]);

  // ── 통화 중 표시 (📞, 통화 상태가 바뀔 때) ──
  const callKey = calls.map((c) => `${c.caseId}:${c.hospitalId}`).sort().join("|");
  useEffect(() => {
    const map = ensureMap();
    if (!map || !overview) return;
    const { kakao } = window;
    callBadgesRef.current.forEach((badge) => badge.setMap(null));
    callBadgesRef.current.clear();
    const byHospital = new Map<string, CallStatus[]>();
    for (const call of calls) {
      if (!call.hospitalId) continue;
      byHospital.set(call.hospitalId, [...(byHospital.get(call.hospitalId) ?? []), call]);
    }
    byHospital.forEach((list, id) => {
      const hospital = overview.hospitals.find((h) => h.hospitalId === id);
      if (!hospital) return;
      const badge = new kakao.maps.CustomOverlay({
        position: new kakao.maps.LatLng(hospital.gps.lat, hospital.gps.lng),
        content: callBadgeElement(list),
        yAnchor: 1,
        zIndex: 60,
      });
      badge.setMap(map);
      callBadgesRef.current.set(id, badge);
    });
    // calls는 callKey로 대신 본다(매 렌더 새 배열)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, overview?.hospitals, callKey]);

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
      // 2026-10-04: 서울 119 구급차 160여 대 — 이름은 사건으로 움직이는(기지 대기가 아닌) 구급차만 띄우고,
      // 단계는 마커 색으로 구분한다(AMBULANCE_PHASE_COLORS). 기지 대기 마커는 작게.
      const phaseKey = sim?.phase ?? "idle";
      const active = phaseKey !== "idle";
      const color = AMBULANCE_PHASE_COLORS[phaseKey];
      const phase = active ? `${PHASE_SHORT[phaseKey]}${sim?.paused ? " · 정지" : ""}` : null;
      const calling = calls.some((c) => c.apid === ambulance.apid);
      const text = active || calling ? `${ambulance.name}${phase ? ` · ${phase}` : ""}${calling ? " · 📞" : ""}` : "";
      const title = `${ambulance.name} · ${PHASE_SHORT[phaseKey]} (시뮬레이션 위치)`;
      let layer = ambulancesRef.current.get(ambulance.apid);
      if (!layer) {
        const marker = new kakao.maps.Marker({
          position: pos, map, title,
          image: createAmbulanceMarkerImage(color, active ? 28 : 20), zIndex: active ? 50 : 40,
        });
        layer = { marker, label: null, text: "", color };
        ambulancesRef.current.set(ambulance.apid, layer);
      } else {
        layer.marker.setPosition(pos);
        if (layer.color !== color) {
          layer.marker.setImage(createAmbulanceMarkerImage(color, active ? 28 : 20));
          layer.marker.setZIndex(active ? 50 : 40);
          layer.color = color;
        }
      }
      if (layer.text !== text) {
        layer.label?.setMap(null);
        layer.label = null;
        if (text) {
          layer.label = createLabelOverlay(pos, text);
          layer.label.setZIndex(51);
          layer.label.setMap(map);
        }
        layer.text = text;
      } else {
        layer.label?.setPosition(pos);
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
          strokeWeight: 4, strokeColor: color, strokeOpacity: 0.75, strokeStyle: "solid",
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
      layer.label?.setMap(null);
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
