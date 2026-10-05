"use client";

import { useEffect, useRef } from "react";
import { distanceLabel, distanceTitle } from "@/lib/distance";
import { css } from "styled-system/css";
import { HD } from "@/components/hospital/hospital-design";
import { useKakaoMapScript } from "@/hooks/use-kakao-map-script";
import { createColoredMarkerImage, createLabelOverlay } from "@/lib/kakao-map-markers";
import { fetchRoadPath } from "@/lib/route";
import type { AmbulanceSimState, HospitalCandidate, HospitalStatus } from "@/types/dashboard";

const STATUS_LABEL: Record<HospitalStatus, string> = {
  pending: "판단 대기",
  approved: "후보 등록",
  rejected: "수용 불가",
  confirmed: "이송 확정",
};

// 구급차 위치는 hub가 내려주는 ambulanceGps(2026-09-24 신설)를 쓴다. 구버전 hub라 그
// 값이 없을 때만 병원 좌표에서 살짝 떨어진 자리를 임시 표시 위치로 쓴다.
const PLACEHOLDER_AMBULANCE_OFFSET = { lat: 0.012, lng: -0.01 };

// 구급차 대시보드의 CandidateMapPanel과 같은 구조(지도가 위, 정보 박스 3개가 그 아래
// 한 줄)로 맞췄다 — 이전엔 지도 옆에 세로 사이드바를 두는 다른 레이아웃이었다(2026-08-09).
// 2026-08-11: CSS 격자로 그리던 가짜 지도를 실제 카카오맵으로 교체.
export function MapPanel({
  hospital,
  caseId,
  ambulanceGps,
  sim = null,
  selfGps = null,
  selfName = null,
  unitName = null,
  statusText = null,
  statusInk = null,
}: {
  hospital: HospitalCandidate | null;
  caseId: string | null;
  ambulanceGps: { lat: number; lng: number } | null;
  // 이 병원으로 이송 중인 구급차의 출동 시뮬레이션 상태(2026-10-01). 있으면 구급차 마커는 1초마다
  // 따로 옮기고, 경로는 hub가 보낸 시뮬레이션 경로를 그린다.
  sim?: AmbulanceSimState | null;
  // 본원 위치(identity_info.gps, 2026-10-04) — 사건이 없어도 본원 중심 지도를 그린다.
  selfGps?: { lat: number; lng: number } | null;
  selfName?: string | null;
  // 선택한 요청의 구급대 이름·카드와 같은 상태 문구(2026-10-04 디자인 시안)
  unitName?: string | null;
  statusText?: string | null;
  statusInk?: string | null;
}) {
  const confirmed = hospital?.status === "confirmed";
  const { ready, error } = useKakaoMapScript();

  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<kakao.maps.Map | null>(null);
  const hospitalMarkerRef = useRef<kakao.maps.Marker | null>(null);
  const hospitalLabelRef = useRef<kakao.maps.CustomOverlay | null>(null);
  const ambulanceMarkerRef = useRef<kakao.maps.Marker | null>(null);
  const ambulanceLabelRef = useRef<kakao.maps.CustomOverlay | null>(null);
  const polylineRef = useRef<kakao.maps.Polyline | null>(null);

  useEffect(() => {
    if (!ready || !containerRef.current) return;

    // 다른 병원으로 이송이 확정돼 이 사건이 목록에서 사라지면 hospital이 null로
    // 넘어온다. 예전엔 여기서 그냥 return해버려서 마지막으로 그려둔 마커·경로가
    // 지도에 그대로 남아있었다(2026-08-12 실제로 재현됨) — 사건이 없어졌으면
    // 지도도 같이 비워야 한다.
    if (!hospital) {
      hospitalMarkerRef.current?.setMap(null);
      hospitalMarkerRef.current = null;
      hospitalLabelRef.current?.setMap(null);
      hospitalLabelRef.current = null;
      ambulanceMarkerRef.current?.setMap(null);
      ambulanceMarkerRef.current = null;
      ambulanceLabelRef.current?.setMap(null);
      ambulanceLabelRef.current = null;
      polylineRef.current?.setMap(null);
      polylineRef.current = null;
      // 사건이 없어도 본원 위치 지도는 띄운다(2026-10-04) — "표시할 사건이 없습니다"
      // 회색 화면 대신, 병원 입장의 평시 화면(본원 마커)이 기본이다.
      if (selfGps) {
        const { kakao } = window;
        const selfPos = new kakao.maps.LatLng(selfGps.lat, selfGps.lng);
        if (!mapRef.current) {
          mapRef.current = new kakao.maps.Map(containerRef.current, { center: selfPos, level: 5 });
        }
        hospitalMarkerRef.current = new kakao.maps.Marker({
          position: selfPos, map: mapRef.current, title: selfName ?? "본원",
          image: createColoredMarkerImage("#1E5FA8"),
        });
        hospitalLabelRef.current = createLabelOverlay(selfPos, selfName ?? "본원");
        hospitalLabelRef.current.setMap(mapRef.current);
        mapRef.current.setCenter(selfPos);
      }
      return;
    }

    const { kakao } = window;
    const hospitalPos = new kakao.maps.LatLng(hospital.gps.lat, hospital.gps.lng);
    const ambulancePos = ambulanceGps
      ? new kakao.maps.LatLng(ambulanceGps.lat, ambulanceGps.lng)
      : new kakao.maps.LatLng(
          hospital.gps.lat + PLACEHOLDER_AMBULANCE_OFFSET.lat,
          hospital.gps.lng + PLACEHOLDER_AMBULANCE_OFFSET.lng,
        );

    if (!mapRef.current) {
      mapRef.current = new kakao.maps.Map(containerRef.current, { center: hospitalPos, level: 6 });
    }
    const map = mapRef.current;

    hospitalMarkerRef.current?.setMap(null);
    hospitalMarkerRef.current = new kakao.maps.Marker({
      position: hospitalPos,
      map,
      title: hospital.name,
      image: createColoredMarkerImage(confirmed ? "#0E9F6E" : "#1E5FA8"),
    });
    hospitalLabelRef.current?.setMap(null);
    hospitalLabelRef.current = createLabelOverlay(hospitalPos, hospital.name);
    hospitalLabelRef.current.setMap(map);

    ambulanceMarkerRef.current?.setMap(null);
    ambulanceLabelRef.current?.setMap(null);
    polylineRef.current?.setMap(null);
    if (sim) {
      // 출동 시뮬레이션: 구급차 마커는 아래 effect가 1초마다 옮긴다. 병원에 도착했으면(at_hospital) 경로 선 없이
      // 병원 자리에 "도착"으로 둔다 — 예전엔 이때 경로가 없어 매칭 때의 사고 현장 좌표와 직선을 그렸다.
      ambulanceMarkerRef.current = null;
      ambulanceLabelRef.current = null;
      polylineRef.current = null;
      const simBounds = new kakao.maps.LatLngBounds();
      simBounds.extend(hospitalPos);
      if (sim.phase === "transporting" && sim.path && sim.path.length > 1) {
        const simPath = sim.path.map(([lat, lng]) => new kakao.maps.LatLng(lat, lng));
        polylineRef.current = new kakao.maps.Polyline({
          path: simPath, strokeWeight: 4, strokeColor: "#1E5FA8", strokeOpacity: 0.9, strokeStyle: "solid",
        });
        polylineRef.current.setMap(map);
        simPath.forEach((point) => simBounds.extend(point));
        map.setBounds(simBounds);
      } else {
        map.setCenter(hospitalPos);
      }
      return;
    }
    ambulanceMarkerRef.current = new kakao.maps.Marker({
      position: ambulancePos,
      map,
      title: ambulanceGps ? "구급차 현재 위치" : "구급차 현재 위치(임시 표시)",
      image: createColoredMarkerImage("#1E5FA8"),
    });
    ambulanceLabelRef.current = createLabelOverlay(ambulancePos, "구급차 현재 위치");
    ambulanceLabelRef.current.setMap(map);

    polylineRef.current = new kakao.maps.Polyline({
      path: [ambulancePos, hospitalPos],
      strokeWeight: 3,
      strokeColor: "#1E5FA8",
      strokeOpacity: 0.85,
      strokeStyle: "shortdash",
    });
    polylineRef.current.setMap(map);

    const bounds = new kakao.maps.LatLngBounds();
    bounds.extend(hospitalPos);
    bounds.extend(ambulancePos);
    map.setBounds(bounds);

    // 도로 경로를 받아오면 직선(점선)을 실제 길(실선)로 바꾼다. 받는 사이 다른 사건·병원으로
    // 바뀌었으면(cancelled) 늦게 온 응답은 버린다. 실패하면 직선을 그대로 둔다.
    let cancelled = false;
    if (caseId && ambulanceGps) {
      fetchRoadPath(caseId, hospital.hospitalId).then((path) => {
        if (cancelled || !path) return;
        const roadPath = path.map(([lat, lng]) => new kakao.maps.LatLng(lat, lng));
        polylineRef.current?.setMap(null);
        polylineRef.current = new kakao.maps.Polyline({
          path: roadPath,
          strokeWeight: 4,
          strokeColor: "#1E5FA8",
          strokeOpacity: 0.9,
          strokeStyle: "solid",
        });
        polylineRef.current.setMap(map);
        const roadBounds = new kakao.maps.LatLngBounds();
        roadPath.forEach((point) => roadBounds.extend(point));
        map.setBounds(roadBounds);
      });
    }
    return () => {
      cancelled = true;
    };
    // ambulanceGps는 매 렌더 새 객체일 수 있어 참조 대신 좌표 값으로 변경을 감지한다.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, hospital, confirmed, caseId, ambulanceGps?.lat, ambulanceGps?.lng, sim?.phase, sim?.path?.length, selfGps?.lat, selfGps?.lng, selfName]);

  // 출동 시뮬레이션: 1초마다 구급차 마커만 옮긴다.
  const simMarkerRef = useRef<kakao.maps.Marker | null>(null);
  const simLabelRef = useRef<kakao.maps.CustomOverlay | null>(null);
  const simLabelTextRef = useRef<string | null>(null);
  useEffect(() => {
    if (!ready || !mapRef.current || !sim?.gps) {
      simMarkerRef.current?.setMap(null);
      simLabelRef.current?.setMap(null);
      simMarkerRef.current = null;
      simLabelRef.current = null;
      return;
    }
    const pos = new window.kakao.maps.LatLng(sim.gps.lat, sim.gps.lng);
    if (!simMarkerRef.current) {
      simMarkerRef.current = new window.kakao.maps.Marker({
        position: pos, map: mapRef.current, title: "구급차 (시뮬레이션 위치)",
        image: createColoredMarkerImage("#1E5FA8"), zIndex: 30,
      });
    } else {
      simMarkerRef.current.setPosition(pos);
    }
    // 이름표는 문구가 바뀔 때(도착)만 새로 단다. 나머지는 위치만 옮긴다.
    const labelText = sim.phase === "at_hospital" ? "구급차 도착" : "구급차 (시뮬레이션)";
    if (!simLabelRef.current || simLabelTextRef.current !== labelText) {
      simLabelRef.current?.setMap(null);
      simLabelRef.current = createLabelOverlay(pos, labelText);
      simLabelRef.current.setMap(mapRef.current);
      simLabelTextRef.current = labelText;
    } else {
      simLabelRef.current.setPosition(pos);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, sim?.gps?.lat, sim?.gps?.lng, sim?.phase]);

  const etaMin =
    sim?.phase === "transporting" && sim.etaSec != null ? Math.max(1, Math.ceil(sim.etaSec / 60)) : hospital?.etaMin ?? null;
  const etaText = sim?.phase === "at_hospital" ? "도착" : etaMin != null ? `${etaMin}분` : "-";
  const status = statusText ?? (hospital ? STATUS_LABEL[hospital.status] : "-");

  // 2026-10-04 디자인 시안: 오른쪽 세로 칸 — 제목·배지, 선택한 요청의 구급대, 지도, 숫자 칸 셋, 안내 한 줄
  return (
    <aside
      style={{
        flex: "1 1 auto", width: "100%", minWidth: 0, minHeight: 0, overflow: "hidden", background: "#FFFFFF",
        borderRadius: 14, border: `1px solid ${HD.line}`, padding: "12px 14px", display: "flex", flexDirection: "column",
        gap: 8, boxSizing: "border-box",
      }}
    >
      <div style={{ flex: "none", display: "flex", flexDirection: "column", gap: 2 }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10 }}>
          <h2 style={{ margin: 0, fontSize: 16, fontWeight: 700, color: HD.navy }}>지도 · 네비게이션</h2>
          <span style={{ fontSize: 10.5, color: HD.ink3, background: HD.chip, borderRadius: 999, padding: "3px 9px" }}>GPS · 카카오 내비</span>
        </div>
        <span style={{ fontSize: 11.5, color: HD.muted }}>구급차 현재 위치 및 본원까지 이동 시간</span>
        {unitName && <span style={{ fontSize: 13, fontWeight: 700, color: HD.navy, overflow: "hidden", textOverflow: "ellipsis" }}>{unitName}</span>}
      </div>
      <div
        style={{
          position: "relative", flex: "1 1 140px", minHeight: 110, borderRadius: 12, border: "1px solid #DCE3EB",
          background: "#EAF0F6", overflow: "hidden",
        }}
      >
        {/* 카카오맵이 이 div 안쪽 DOM을 직접 그리므로 React 자식은 형제 오버레이로 둔다(리렌더 충돌 방지).
            zIndex:0으로 쌓임 맥락을 만들어 카카오 내부 z-index가 바깥 오버레이를 덮지 않게 한다(2026-08-12). */}
        <div
          ref={containerRef}
          role="img"
          aria-label="구급차 현재 위치와 본원까지의 경로를 표시한 지도"
          className={css({ position: "absolute", inset: "0", zIndex: "0" })}
        />
        {(!ready || error || (!hospital && !selfGps)) && (
          <div
            style={{
              position: "absolute", inset: 0, zIndex: 1, display: "flex", alignItems: "center", justifyContent: "center",
              textAlign: "center", padding: "0 16px", fontSize: 12, color: error ? HD.red : HD.muted, background: "#EAF0F6",
            }}
          >
            {error ?? (!hospital && !selfGps ? "표시할 사건이 없습니다" : "지도를 불러오는 중...")}
          </div>
        )}
      </div>
      <div style={{ flex: "none", display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))", gap: 6 }}>
        <div style={{ ...statBox, background: confirmed ? HD.greenSoft : "#FFFFFF" }}>
          <span style={statLabel}>본원 도착 예상</span>
          <span style={{ fontSize: 19, fontWeight: 900, lineHeight: 1.2, color: confirmed ? HD.green : HD.navy }}>{etaText}</span>
          <span style={{ fontSize: 10.5, color: HD.muted }}>실시간 교통 반영</span>
        </div>
        <div style={statBox} title={hospital ? distanceTitle(hospital) : undefined}>
          <span style={statLabel}>이동 거리</span>
          <span style={{ fontSize: hospital?.roadDistanceKm != null ? 19 : 15, fontWeight: 900, lineHeight: 1.2, color: HD.navy, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{hospital ? distanceLabel(hospital) : "-"}</span>
        </div>
        <div style={statBox}>
          <span style={statLabel}>현재 상태</span>
          <span style={{ fontSize: 15, fontWeight: 700, lineHeight: 1.5, color: statusInk ?? HD.navy, overflow: "hidden", textOverflow: "ellipsis" }}>{status}</span>
        </div>
      </div>
      <span style={{ flex: "none", fontSize: 11.5, color: HD.muted }}>카드의 도착 예상 시간을 누르면 경로가 표시됩니다.</span>
    </aside>
  );
}

const statBox: React.CSSProperties = {
  border: `1px solid ${HD.line}`, borderRadius: 10, padding: "6px 9px", display: "flex", flexDirection: "column", gap: 1, minWidth: 0,
};
const statLabel: React.CSSProperties = { fontSize: 11.5, color: HD.sub, overflow: "hidden", textOverflow: "ellipsis" };
