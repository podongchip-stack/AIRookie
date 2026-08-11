"use client";

import { useEffect, useRef } from "react";
import { css } from "styled-system/css";
import { Panel } from "@/components/layout/Panel";
import { Tag } from "@/components/hospital/Tag";
import { useKakaoMapScript } from "@/hooks/use-kakao-map-script";
import { createColoredMarkerImage, createLabelOverlay } from "@/lib/kakao-map-markers";
import type { HospitalCandidate, HubMatchResult } from "@/types/dashboard";

const sideBoxStyle = css({
  flex: "1",
  borderWidth: "1px",
  borderColor: "line",
  borderRadius: "field",
  paddingX: "3.5",
  paddingY: "3",
});

// 구급차 자신의 GPS는 아직 hub 스키마에 없다(ISSUE_카카오맵연동.md 참고, hub팀에
// 필드 추가 요청해둔 상태). 그 전까지는 후보 병원들의 중심 좌표에서 살짝
// 떨어진 자리를 임시 표시 위치로 쓴다.
const PLACEHOLDER_AMBULANCE_OFFSET = { lat: 0.014, lng: -0.012 };

function markerColorHex(hospital: HospitalCandidate, isConfirmed: boolean): string {
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
}: {
  data: HubMatchResult | null;
  confirmedHospitalId: string | null;
}) {
  const hospitals = data?.hospitals ?? [];
  const confirmedHospital = hospitals.find((h) => h.hospitalId === confirmedHospitalId) ?? null;
  const { ready, error } = useKakaoMapScript();

  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<kakao.maps.Map | null>(null);
  const hospitalMarkersRef = useRef<{ marker: kakao.maps.Marker; label: kakao.maps.CustomOverlay }[]>([]);
  const ambulanceMarkerRef = useRef<kakao.maps.Marker | null>(null);
  const ambulanceLabelRef = useRef<kakao.maps.CustomOverlay | null>(null);
  const polylineRef = useRef<kakao.maps.Polyline | null>(null);

  useEffect(() => {
    if (!ready || !containerRef.current || hospitals.length === 0) return;

    const { kakao } = window;

    const lats = hospitals.map((h) => h.gps.lat);
    const lngs = hospitals.map((h) => h.gps.lng);
    const centerLat = lats.reduce((sum, v) => sum + v, 0) / lats.length;
    const centerLng = lngs.reduce((sum, v) => sum + v, 0) / lngs.length;
    const ambulancePos = new kakao.maps.LatLng(
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
    ambulanceMarkerRef.current = new kakao.maps.Marker({
      position: ambulancePos,
      map,
      title: "구급차 현재 위치(임시 표시)",
      image: createColoredMarkerImage("#1E5FA8"),
      zIndex: 20,
    });
    ambulanceLabelRef.current?.setMap(null);
    ambulanceLabelRef.current = createLabelOverlay(ambulancePos, "구급차 현재 위치");
    ambulanceLabelRef.current.setMap(map);
    bounds.extend(ambulancePos);

    polylineRef.current?.setMap(null);
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
    // hospitals는 매 렌더 새 배열일 수 있어 참조 대신 caseId+길이로 변경을 감지한다.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, data?.caseId, hospitals.length, confirmedHospitalId]);

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
            className={css({ position: "absolute", inset: "0" })}
          />
          {(!ready || error || hospitals.length === 0) && (
            <div
              className={css({
                position: "absolute",
                inset: "0",
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
