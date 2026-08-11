"use client";

import { useEffect, useRef } from "react";
import { css } from "styled-system/css";
import { Panel } from "@/components/layout/Panel";
import { Tag } from "@/components/hospital/Tag";
import { useKakaoMapScript } from "@/hooks/use-kakao-map-script";
import { createColoredMarkerImage, createLabelOverlay } from "@/lib/kakao-map-markers";
import type { HospitalCandidate, HospitalStatus } from "@/types/dashboard";

const STATUS_LABEL: Record<HospitalStatus, string> = {
  pending: "판단 대기",
  approved: "후보 등록",
  rejected: "수용 불가",
  confirmed: "이송 확정",
};

const sideBoxStyle = css({
  flex: "1",
  borderWidth: "1px",
  borderColor: "line",
  borderRadius: "field",
  paddingX: "3.5",
  paddingY: "3",
});

// 구급차 자신의 GPS는 아직 hub 스키마에 없다(ISSUE_카카오맵연동.md 참고, hub팀에
// 필드 추가 요청해둔 상태). 그 전까지는 병원 좌표에서 살짝 떨어진 자리를 임시
// 표시 위치로 쓴다 — hub가 실제 GPS를 내려주기 시작하면 이 오프셋을 걷어내고
// 그 값으로 바꾸면 된다.
const PLACEHOLDER_AMBULANCE_OFFSET = { lat: 0.012, lng: -0.01 };

// 구급차 대시보드의 CandidateMapPanel과 같은 구조(지도가 위, 정보 박스 3개가 그 아래
// 한 줄)로 맞췄다 — 이전엔 지도 옆에 세로 사이드바를 두는 다른 레이아웃이었다(2026-08-09).
// 2026-08-11: CSS 격자로 그리던 가짜 지도를 실제 카카오맵으로 교체.
export function MapPanel({ hospital }: { hospital: HospitalCandidate | null }) {
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
      return;
    }

    const { kakao } = window;
    const hospitalPos = new kakao.maps.LatLng(hospital.gps.lat, hospital.gps.lng);
    const ambulancePos = new kakao.maps.LatLng(
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
    ambulanceMarkerRef.current = new kakao.maps.Marker({
      position: ambulancePos,
      map,
      title: "구급차 현재 위치(임시 표시)",
      image: createColoredMarkerImage("#1E5FA8"),
    });
    ambulanceLabelRef.current?.setMap(null);
    ambulanceLabelRef.current = createLabelOverlay(ambulancePos, "구급차 현재 위치");
    ambulanceLabelRef.current.setMap(map);

    polylineRef.current?.setMap(null);
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
  }, [ready, hospital, confirmed]);

  return (
    <Panel
      title="지도 · 네비게이션"
      subtitle="구급차 현재 위치 및 본원까지 이동 시간"
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
              여기 안 두고 아래 오버레이 div를 형제로 절대배치한다 — 같이 두면
              리렌더 시 React와 SDK가 서로 다른 DOM을 지우려다 충돌한다. */}
          <div
            ref={containerRef}
            role="img"
            aria-label="구급차 현재 위치와 본원까지의 경로를 표시한 지도"
            // zIndex:0으로 이 div 스스로 별도 쌓임 맥락(stacking context)을 만들어야
            // 카카오맵이 내부적으로 쓰는 z-index들이 바깥으로 새어나가 형제인 오버레이
            // 위를 덮어버리는 걸 막을 수 있다(2026-08-12, 사건이 사라졌는데 지도가
            // 안 지워지던 문제의 원인 중 하나 — 정리 로직 누락과 별개로 겪음).
            className={css({ position: "absolute", inset: "0", zIndex: "0" })}
          />
          {(!ready || error || !hospital) && (
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
              {error ?? (!hospital ? "표시할 사건이 없습니다" : "지도를 불러오는 중...")}
            </div>
          )}
        </div>

        <div className={css({ width: "100%", display: "flex", flexDirection: "row", gap: "2.5" })}>
          <div
            className={css({
              flex: "1",
              borderWidth: "1px",
              borderColor: confirmed ? "#B9E4D3" : "line",
              backgroundColor: confirmed ? "mintSoft" : "surface",
              borderRadius: "field",
              paddingX: "3.5",
              paddingY: "3",
            })}
          >
            <div className={css({ fontSize: "sm", fontWeight: "medium", color: confirmed ? "#0A7351" : "ink" })}>
              본원 도착 예상
            </div>
            <div
              className={css({
                fontSize: "2xl",
                fontWeight: "bold",
                letterSpacing: "-0.02em",
                color: confirmed ? "#0A7351" : "ink",
              })}
            >
              {hospital?.etaMin != null ? `${hospital.etaMin}분` : "-"}
            </div>
            <div className={css({ fontSize: "xs", color: "ink", marginTop: "0.5" })}>
              실시간 교통 반영
            </div>
          </div>

          <div className={sideBoxStyle}>
            <div className={css({ fontSize: "sm", fontWeight: "medium", color: "ink" })}>직선 거리</div>
            <div className={css({ fontSize: "2xl", fontWeight: "bold", letterSpacing: "-0.02em", color: "ink" })}>
              {hospital ? `${hospital.distanceKm}km` : "-"}
            </div>
          </div>

          <div className={sideBoxStyle}>
            <div className={css({ fontSize: "sm", fontWeight: "medium", color: "ink" })}>현재 상태</div>
            <div className={css({ fontSize: "2xl", fontWeight: "bold", letterSpacing: "-0.02em", color: "ink" })}>
              {hospital ? STATUS_LABEL[hospital.status] : "-"}
            </div>
          </div>
        </div>
      </div>
    </Panel>
  );
}
