"use client";

import { useEffect, useRef } from "react";
import { css } from "styled-system/css";
import { useKakaoMapScript } from "@/hooks/use-kakao-map-script";
import { escapeHtml } from "@/lib/kakao-map-markers";
import { centerInView, focusInView } from "@/lib/map-view";
import {
  C, LEVEL_DEFAULT, LEVEL_DOT, ST_DOT, ST_PILL, ambState, reqLabel, shortAmb, shortHospital, zoneText, type Incident, type St,
} from "@/lib/control-map";
import type { AmbulanceSimState, MapOverview } from "@/types/dashboard";

// 관제 지도 개편(2026-10-04, 디자인 시안 "골든링크 관제")의 지도 부분. 카카오맵 위에 시안의 표시를 DOM 오버레이로 그린다.
// - 병원: 작은 점. 선택한 사건의 요청 병원은 응답 상태 색(판단 대기 노랑·수용 불가 빨강·수용 승인 연두·이송 확정 초록),
//   그 밖의 병원은 등급 색을 옅게. 응답이 온 병원(판단 대기 제외)과 마우스를 올린 병원 위에 상태 말풍선.
// - 구급차: 사각형 + 십자. 출동·현장은 주황, 이송은 초록, 기지 대기는 흰 바탕. 사건 구급차는 크게 + 사건 번호,
//   선택한 사건 구급차는 가장 크게(현장이면 맥박) + 이름표.
// - 선택한 사건의 요청 존 범위: 보라 점선 원(넓혀졌으면 처음 범위를 옅게 같이).
// 마커 수백 개를 매 렌더 다시 만들지 않도록 DOM 요소를 ref에 두고 스타일만 갈아 끼운다(기존 MonitorMapPanel과 같은 원칙).
// 사건 상황판(/case)은 기존 MonitorMapPanel을 그대로 쓴다.

const SEOUL_CENTER = { lat: 37.5565, lng: 126.99 };
const INITIAL_LEVEL = 8;

/** 두 점을 잇는 완만한 호(2차 베지어, 같은 쪽으로 휜다) — 직선이면 선이 겹쳐 어느 병원으로 가는지 구분이 안 된다 */
function arcPath(a: { lat: number; lng: number }, b: { lat: number; lng: number }, n = 20): { lat: number; lng: number }[] {
  const bow = 0.16;
  const mx = (a.lng + b.lng) / 2 - (b.lat - a.lat) * bow;
  const my = (a.lat + b.lat) / 2 + (b.lng - a.lng) * bow;
  return Array.from({ length: n + 1 }, (_, i) => {
    const t = i / n, u = 1 - t;
    return { lat: u * u * a.lat + 2 * u * t * my + t * t * b.lat, lng: u * u * a.lng + 2 * u * t * mx + t * t * b.lng };
  });
}
const MOVING = new Set(["dispatching", "transporting", "returning"]);

type HospitalLayer = { overlay: kakao.maps.CustomOverlay; dot: HTMLDivElement; pill: HTMLDivElement; key: string };
type AmbLayer = { overlay: kakao.maps.CustomOverlay; root: HTMLDivElement; key: string };

const PILL_ICON: Record<St, string> = {
  w: `<svg width="10" height="10" viewBox="0 0 10 10"><path d="M5 1a3 3 0 0 0-3 3v2L1 8h8L8 6V4a3 3 0 0 0-3-3zM4 9h2" fill="#fff" stroke="#fff" stroke-width=".8"/></svg>`,
  r: `<svg width="9" height="9" viewBox="0 0 10 10"><path d="M2 2l6 6M8 2L2 8" stroke="#fff" stroke-width="2"/></svg>`,
  a: `<svg width="10" height="10" viewBox="0 0 10 10"><path d="M1.8 5.2L4 7.4 8.2 2.6" fill="none" stroke="#fff" stroke-width="1.9"/></svg>`,
  t: `<svg width="12" height="10" viewBox="0 0 12 10"><path d="M1 2h6v5H1zM7 4h2.5L11 5.5V7H7z" fill="#fff"/><circle cx="3" cy="8" r="1.1" fill="#fff" stroke="#168A55" stroke-width=".6"/><circle cx="9" cy="8" r="1.1" fill="#fff" stroke="#168A55" stroke-width=".6"/></svg>`,
};

export function ControlMapPanel({
  overview,
  incidents,
  selected,
  activeTab,
  ambulanceSim,
  focusNonce = 0,
  hoverHospital,
  hoverAmb,
  ambVisible,
  alertCaseIds,
  onHoverHospital,
  onHoverAmb,
  onSelectCase,
  children,
}: {
  overview: MapOverview | null;
  incidents: Incident[];
  selected: Incident | null;
  activeTab: "all" | St;
  ambulanceSim: Record<string, AmbulanceSimState>;
  // 사건을 누를 때마다 올라가는 값 — 같은 사건을 다시 눌러도 그 사건으로 다시 맞춘다
  focusNonce?: number;
  hoverHospital: string;
  hoverAmb: string;
  // 하단 구급차 패널의 탭에 해당하지 않는 구급차는 지도에서 옅게
  ambVisible: (apid: string) => boolean;
  // 확인하지 않은 알림이 걸린 사건 — 그 구급차를 붉은 파동으로 강조(알림 표시는 아이콘 없이 색·파동·글자만)
  alertCaseIds?: ReadonlySet<string>;
  onHoverHospital: (id: string) => void;
  onHoverAmb: (apid: string) => void;
  onSelectCase: (caseId: string) => void;
  children?: React.ReactNode;
}) {
  const { ready, error } = useKakaoMapScript();
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<kakao.maps.Map | null>(null);
  const hospitalsRef = useRef(new Map<string, HospitalLayer>());
  const ambsRef = useRef(new Map<string, AmbLayer>());
  const pathsRef = useRef(new Map<string, { line: kakao.maps.Polyline; key: string }>());
  const linksRef = useRef(new Map<string, { line: kakao.maps.Polyline; key: string }>());
  const ringRef = useRef<{ outer: kakao.maps.Circle; inner: kakao.maps.Circle | null; label: kakao.maps.CustomOverlay; key: string } | null>(null);
  // 카카오·DOM 이벤트 핸들러는 한 번 걸어 두고 최신 콜백은 ref로 읽는다
  const cbRef = useRef({ onHoverHospital, onHoverAmb, onSelectCase });
  useEffect(() => {
    cbRef.current = { onHoverHospital, onHoverAmb, onSelectCase };
  }, [onHoverHospital, onHoverAmb, onSelectCase]);

  // 상단 경보 띠가 나타나거나 창 크기가 바뀌어 지도 칸 크기가 달라지면 카카오 지도를 다시 맞춘다(안 하면 회색 빈틈이 생김)
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => mapRef.current?.relayout());
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  function ensureMap(): kakao.maps.Map | null {
    if (mapRef.current) return mapRef.current;
    if (!ready || !containerRef.current) return null;
    const { kakao } = window;
    mapRef.current = new kakao.maps.Map(containerRef.current, {
      center: new kakao.maps.LatLng(SEOUL_CENTER.lat, SEOUL_CENTER.lng),
      level: INITIAL_LEVEL,
    });
    return mapRef.current;
  }

  // ── 병원 점·말풍선: 목록이 바뀌면 만들고, 사건·탭·마우스가 바뀌면 스타일만 갈아 끼운다 ──
  useEffect(() => {
    const map = ensureMap();
    if (!map || !overview) return;
    const { kakao } = window;
    const layers = hospitalsRef.current;
    const ids = new Set(overview.hospitals.map((h) => h.hospitalId));
    layers.forEach((layer, id) => {
      if (!ids.has(id)) {
        layer.overlay.setMap(null);
        layers.delete(id);
      }
    });
    for (const h of overview.hospitals) {
      if (layers.has(h.hospitalId)) continue;
      const root = document.createElement("div");
      root.style.cssText = "position:relative;width:0;height:0";
      const dot = document.createElement("div");
      dot.title = `${h.name} · H-${h.hospitalId}${h.emergencyLevel ? ` · ${h.emergencyLevel}` : ""}`;
      dot.addEventListener("mouseenter", () => cbRef.current.onHoverHospital(h.hospitalId));
      dot.addEventListener("mouseleave", () => cbRef.current.onHoverHospital(""));
      const pill = document.createElement("div");
      root.append(dot, pill);
      const overlay = new kakao.maps.CustomOverlay({
        position: new kakao.maps.LatLng(h.gps.lat, h.gps.lng),
        content: root,
        xAnchor: 0,
        yAnchor: 0,
        zIndex: 3,
      });
      overlay.setMap(map);
      layers.set(h.hospitalId, { overlay, dot, pill, key: "" });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, overview?.hospitals]);

  useEffect(() => {
    if (!mapRef.current || !overview) return;
    const inCase = new Map((selected?.hospitals ?? []).map((h) => [h.hospitalId, h]));
    for (const h of overview.hospitals) {
      const layer = hospitalsRef.current.get(h.hospitalId);
      if (!layer) continue;
      const req = inCase.get(h.hospitalId);
      const on = hoverHospital === h.hospitalId;
      const inTab = req != null && (activeTab === "all" || activeTab === req.st);
      const showPill = req != null && ((req.st !== "w" && inTab) || on);
      const key = `${req?.st ?? "-"}|${inTab}|${on}|${showPill}`;
      if (layer.key === key) continue;
      layer.key = key;
      const base =
        "position:absolute;box-sizing:border-box;border-radius:50%;border:2px solid #fff;" +
        "box-shadow:0 1px 3px rgba(20,30,50,.35);transition:transform .15s,opacity .2s;cursor:default;";
      if (!req) {
        const color = (h.emergencyLevel && LEVEL_DOT[h.emergencyLevel]) || LEVEL_DEFAULT;
        layer.dot.style.cssText = `${base}left:-5px;top:-5px;width:10px;height:10px;background:${color};opacity:${on ? 1 : 0.45};` +
          (on ? "transform:scale(1.7);" : "");
      } else {
        const big = activeTab === "w" && req.st === "w";
        const size = big ? 12 : 14;
        layer.dot.style.cssText = `${base}left:${-size / 2}px;top:${-size / 2}px;width:${size}px;height:${size}px;` +
          `background:${ST_DOT[req.st]};opacity:${inTab || on ? 1 : 0.18};` + (on ? "transform:scale(1.7);" : "");
      }
      if (showPill && req) {
        const label = reqLabel(req);
        layer.pill.style.cssText =
          "position:absolute;left:0;bottom:11px;transform:translateX(-50%);display:flex;align-items:center;gap:3px;" +
          "height:17px;padding:0 7px 0 5px;border-radius:3px;border:1.5px solid #fff;color:#fff;font-size:10.5px;" +
          `font-weight:700;white-space:nowrap;box-shadow:0 1px 3px rgba(20,30,50,.28);background:${ST_PILL[req.st]};` +
          "font-family:inherit;pointer-events:none;";
        layer.pill.innerHTML = `${PILL_ICON[req.st]}${escapeHtml(on ? `${shortHospital(h.name)} · ${label}` : label)}`;
      } else {
        layer.pill.style.cssText = "display:none";
        layer.pill.innerHTML = "";
      }
      layer.overlay.setZIndex(on ? 60 : !req ? 3 : req.st === "w" ? 6 : 12);
    }
  }, [overview, selected, activeTab, hoverHospital]);

  // ── 선택한 사건 자동 포커스(2026-10-06) — 하단 구급차 패널 등이 덮은 부분을 빼고 보이는 영역에 맞춘다 ──
  // 실제 사건(콘솔 시연)은 단계가 바뀔 때마다 맞춘다: 출동(구급차~현장) → 현장(현장 확대) → 병원 요청(요청 병원이 다
  // 보이게) → 이송(구급차~확정 병원) → 병원 도착(병원 확대). 움직이는 동안 구급차가 화면 밖으로 나가려 하면 다시 맞춘다.
  // 사람이 지도를 끌거나 휠로 확대하면 다음 단계가 바뀔 때까지 따라가지 않는다. 자동 시연(가짜) 사건은 고를 때 한 번만 옮긴다.
  const followRef = useRef(true);
  const lastCaseRef = useRef("");
  const lastNonceRef = useRef(focusNonce);
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const stop = () => { followRef.current = false; };
    el.addEventListener("pointerdown", stop);
    el.addEventListener("wheel", stop, { passive: true });
    return () => {
      el.removeEventListener("pointerdown", stop);
      el.removeEventListener("wheel", stop);
    };
  }, []);

  const selSim = selected?.apid ? ambulanceSim[selected.apid] : undefined;
  const confirmedId = selected?.hospitals.find((h) => h.st === "t")?.hospitalId ?? null;
  const focusKey = selected
    ? `${selected.caseId}|${selSim?.phase ?? ""}|${selected.matched}|${confirmedId ?? ""}|${selected.zone}|${focusNonce}`
    : "";

  function focusTarget(): { center: { lat: number; lng: number }; others: { lat: number; lng: number }[] } | null {
    if (!selected?.center) return null;
    const scene = selected.center;
    const amb = selSim?.gps ?? null;
    const gpsOf = (id: string) => overview?.hospitals.find((h) => h.hospitalId === id)?.gps ?? null;
    const phase = selSim?.phase;
    const dest = confirmedId ? gpsOf(confirmedId) : null;
    // 구급차가 보이는 영역 한가운데에 오게 한다 — 나머지(현장·병원)는 구급차 기준으로 다 보이게 줌을 맞춘다
    if (phase === "at_hospital" && dest) return { center: dest, others: [] };
    if (phase === "transporting" && dest && amb) return { center: amb, others: [dest] };
    if (phase === "dispatching" && amb) return { center: amb, others: [scene] };
    if (selected.matched && !dest) {
      const requested = selected.hospitals.map((h) => gpsOf(h.hospitalId)).filter((g): g is { lat: number; lng: number } => g != null);
      return { center: amb ?? scene, others: amb ? [scene, ...requested] : requested };
    }
    if (amb) return { center: amb, others: [scene] };
    return { center: scene, others: [] };
  }

  useEffect(() => {
    const map = ensureMap();
    const el = containerRef.current;
    if (!map || !el || !selected) return;
    const caseChanged = lastCaseRef.current !== selected.caseId;
    lastCaseRef.current = selected.caseId;
    const nonceChanged = lastNonceRef.current !== focusNonce;
    lastNonceRef.current = focusNonce;
    if (selected.fake) {
      if (caseChanged || nonceChanged) {
        const target = focusTarget();
        if (target) focusInView(map, el, target.center, target.others);   // 위치만 옮기지 않고 확대·축소도 맞춘다
      }
      return;
    }
    followRef.current = true;
    const target = focusTarget();
    if (target) focusInView(map, el, target.center, target.others);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, focusKey]);

  // 움직이는 동안 구급차가 보이는 영역 밖으로 나가려 하면 다시 맞춘다(사람이 지도를 만졌으면 안 함)
  useEffect(() => {
    const map = mapRef.current;
    const el = containerRef.current;
    if (!map || !el || !selected || selected.fake || !followRef.current) return;
    if (!selSim?.gps || !MOVING.has(selSim.phase)) return;
    centerInView(map, el, selSim.gps);   // 줌은 그대로, 움직이는 구급차만 계속 가운데로
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selSim?.gps?.lat, selSim?.gps?.lng]);

  // ── 구급차 사각형·번호·이름표·이동 경로 ──
  useEffect(() => {
    const map = ensureMap();
    if (!map || !overview) return;
    const { kakao } = window;
    const byApid = new Map(incidents.filter((i) => i.apid).map((i) => [i.apid!, i]));
    const seen = new Set<string>();
    for (const a of overview.ambulances) {
      seen.add(a.apid);
      const sim = ambulanceSim[a.apid];
      const gps = sim?.gps ?? a.gps;
      const pos = new kakao.maps.LatLng(gps.lat, gps.lng);
      const st = ambState(sim);
      const inc = byApid.get(a.apid);
      const isInc = !!inc;
      const isSel = isInc && selected?.caseId === inc.caseId;
      const on = hoverAmb === a.apid;
      const size = isSel ? 28 : isInc ? 22 : on ? 24 : 16;
      const filled = st.key !== "b";
      const col = st.key === "t" ? "#168A55" : C.orange;
      const dim = !isInc && !ambVisible(a.apid) && !on;  // 숨김(기지 대기가 접힌 상태) — 흐리게가 아니라 아예 안 보이고 클릭도 막는다
      const alerting = !!inc && !!alertCaseIds?.has(inc.caseId);
      const key = `${st.key}|${st.text}|${inc?.num ?? ""}|${isSel}|${on}|${dim}|${alerting}`;
      let layer = ambsRef.current.get(a.apid);
      if (!layer) {
        const root = document.createElement("div");
        root.addEventListener("mouseenter", () => cbRef.current.onHoverAmb(a.apid));
        root.addEventListener("mouseleave", () => cbRef.current.onHoverAmb(""));
        const overlay = new kakao.maps.CustomOverlay({ position: pos, content: root, xAnchor: 0, yAnchor: 0, zIndex: 14 });
        overlay.setMap(map);
        layer = { overlay, root, key: "" };
        ambsRef.current.set(a.apid, layer);
      } else {
        layer.overlay.setPosition(pos);
      }
      if (layer.key !== key) {
        layer.key = key;
        const plus = Math.round(size * 0.55);
        const alertRing = alerting
          ? `<div style="position:absolute;left:-30px;top:-30px;width:60px;height:60px;box-sizing:border-box;border-radius:50%;border:4px solid #D93025;animation:ctlring 1.3s ease-out infinite;pointer-events:none"></div>`
          : "";
        const pulse = isSel && st.key === "s"
          ? `<div style="position:absolute;left:-10px;top:-10px;width:20px;height:20px;border-radius:50%;background:${C.orange};animation:ctlring 2.2s ease-out infinite;pointer-events:none"></div>`
          : "";
        const badge = isInc
          ? `<div style="position:absolute;left:${size / 2 - 5}px;top:${-size / 2 - 8}px;min-width:15px;height:15px;box-sizing:border-box;border-radius:8px;background:${alerting ? "#D93025" : C.navy};border:1.5px solid #fff;color:#fff;font-size:9.5px;font-weight:700;display:flex;align-items:center;justify-content:center;pointer-events:none">${inc!.num}</div>`
          : "";
        const label = isSel || on
          ? `<div style="position:absolute;left:${size / 2 + 6}px;top:-10px;height:20px;display:flex;align-items:center;white-space:nowrap;font-size:11px;font-weight:700;background:#fff;border:1px solid #F2B48F;border-radius:5px;padding:0 8px;color:${C.ink};box-shadow:0 1px 4px rgba(20,30,50,.18)">${escapeHtml(shortAmb(a.name))} <span style="font-weight:500;color:#C7511A;margin-left:4px">· ${escapeHtml(st.text)}</span></div>`
          : "";
        layer.root.style.cssText = `position:relative;width:0;height:0;opacity:${dim ? 0 : 1};pointer-events:${dim ? "none" : "auto"}`;
        layer.root.title = `${a.name} · ${st.text}${isInc ? ` · 사건 ${inc!.num}` : ""} (시뮬레이션 위치)`;
        layer.root.innerHTML =
          alertRing +
          pulse +
          `<div data-amb style="position:absolute;left:${-size / 2}px;top:${-size / 2}px;width:${size}px;height:${size}px;box-sizing:border-box;` +
          `border-radius:${isInc ? 6 : 4}px;background:${filled ? col : "#fff"};border:${isInc ? 2 : 1.5}px solid ${filled ? "#fff" : col};` +
          `box-shadow:0 1px 3px rgba(20,30,50,.35);display:flex;align-items:center;justify-content:center;cursor:${isInc ? "pointer" : "default"}">` +
          `<svg width="${plus}" height="${plus}" viewBox="0 0 12 12"><path d="M6 1.5v9M1.5 6h9" stroke="${filled ? "#fff" : col}" stroke-width="2.6"/></svg></div>` +
          badge + label;
        const box = layer.root.querySelector<HTMLDivElement>("[data-amb]");
        if (box && inc) box.onclick = () => cbRef.current.onSelectCase(inc.caseId);
        layer.overlay.setZIndex(alerting ? 60 : isSel ? 45 : isInc ? 40 : on ? 55 : 14);
      }

      // 이동 경로: 사건 구급차가 움직이는 구간만
      const path = sim && isInc && MOVING.has(sim.phase) && sim.path && sim.path.length > 1 ? sim.path : null;
      const pathKey = path ? `${sim?.phase}:${path.length}:${path[0].join(",")}:${isSel}` : "";
      const drawn = pathsRef.current.get(a.apid);
      if (drawn && drawn.key !== pathKey) {
        drawn.line.setMap(null);
        pathsRef.current.delete(a.apid);
      }
      if (path && (!drawn || drawn.key !== pathKey)) {
        const line = new kakao.maps.Polyline({
          path: path.map(([lat, lng]) => new kakao.maps.LatLng(lat, lng)),
          strokeWeight: isSel ? 4 : 3, strokeColor: col, strokeOpacity: isSel ? 0.8 : 0.45, strokeStyle: "solid",
        });
        line.setMap(map);
        pathsRef.current.set(a.apid, { line, key: pathKey });
      }
    }
    ambsRef.current.forEach((layer, apid) => {
      if (seen.has(apid)) return;
      layer.overlay.setMap(null);
      ambsRef.current.delete(apid);
      pathsRef.current.get(apid)?.line.setMap(null);
      pathsRef.current.delete(apid);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, overview?.ambulances, ambulanceSim, incidents, selected?.caseId, hoverAmb, ambVisible, alertCaseIds]);

  // ── 선택한 사건의 요청 범위 ──
  useEffect(() => {
    const map = ensureMap();
    if (!map) return;
    const { kakao } = window;
    const sel = selected && selected.matched && selected.center && selected.zone > 0 ? selected : null;
    const key = sel ? `${sel.caseId}|${sel.zone}|${sel.zoneStart}|${sel.center!.lat},${sel.center!.lng}` : "";
    if (ringRef.current?.key === key) return;
    if (ringRef.current) {
      ringRef.current.outer.setMap(null);
      ringRef.current.inner?.setMap(null);
      ringRef.current.label.setMap(null);
      ringRef.current = null;
    }
    if (!sel) return;
    const center = new kakao.maps.LatLng(sel.center!.lat, sel.center!.lng);
    const radiusKm = sel.zone * sel.zoneBandKm;
    const expanded = sel.zone > sel.zoneStart;
    const outer = new kakao.maps.Circle({
      center, radius: radiusKm * 1000, strokeWeight: 1.5, strokeColor: C.zone, strokeOpacity: expanded ? 0.55 : 0.9,
      strokeStyle: "dash", fillColor: C.zone, fillOpacity: 0.035,
    });
    outer.setMap(map);
    let inner: kakao.maps.Circle | null = null;
    if (expanded) {
      inner = new kakao.maps.Circle({
        center, radius: sel.zoneStart * sel.zoneBandKm * 1000, strokeWeight: 1.5, strokeColor: C.zone,
        strokeOpacity: 0.9, strokeStyle: "dash", fillOpacity: 0,
      });
      inner.setMap(map);
    }
    const text = `${shortAmb(sel.name)} 요청 범위 · ${zoneText(sel.zone)} (${radiusKm}km)${expanded ? " · 거절로 확장" : ""}`;
    const label = new kakao.maps.CustomOverlay({
      position: new kakao.maps.LatLng(sel.center!.lat + radiusKm / 111, sel.center!.lng),
      content:
        `<div style="font-size:11px;font-weight:700;color:#6A3DE8;background:#fff;border:1px dashed ${C.zone};` +
        `border-radius:6px;padding:2px 10px;white-space:nowrap">${escapeHtml(text)}</div>`,
      yAnchor: 0.5,
      zIndex: 2,
    });
    label.setMap(map);
    ringRef.current = { outer, inner, label, key };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, selected]);

  // ── 선택한 사건 → 요청한 병원 연결선(2026-11-01) — 병원 응답이 어디로 번지는지 한눈에 보이게 호로 잇는다.
  // 색은 병원 점과 같고(대기 노랑·승인 초록·불가 붉은 점선·확정 진초록 굵게), 확정된 병원이 있으면 나머지는 옅게 둔다.
  useEffect(() => {
    const map = ensureMap();
    if (!map || !overview) return;
    const { kakao } = window;
    const links = linksRef.current;
    // 이송이 시작되면(이송 중·병원 도착) 요청 곡선은 걷고 구급차 이동 경로만 남긴다
    const tPhase = selected?.apid ? ambulanceSim[selected.apid]?.phase : undefined;
    const transporting = tPhase === "transporting" || tPhase === "at_hospital";
    const center = selected && selected.matched && !transporting ? selected.center : null;
    const anyConfirmed = !!selected?.hospitals.some((h) => h.st === "t");
    const gpsById = new Map(overview.hospitals.map((h) => [h.hospitalId, h.gps]));
    const wanted = new Set<string>();
    if (selected && center) {
      for (const h of selected.hospitals) {
        const to = gpsById.get(h.hospitalId);
        if (!to) continue;
        wanted.add(h.hospitalId);
        const on = hoverHospital === h.hospitalId;
        const dim = anyConfirmed && h.st !== "t";
        const key = `${selected.caseId}|${h.st}|${on}|${dim}|${center.lat},${center.lng}`;
        const old = links.get(h.hospitalId);
        if (old?.key === key) continue;
        old?.line.setMap(null);
        const line = new kakao.maps.Polyline({
          path: arcPath(center, to).map((p) => new kakao.maps.LatLng(p.lat, p.lng)),
          strokeColor: ST_DOT[h.st],
          strokeWeight: (h.st === "t" ? 5 : h.st === "a" ? 3.5 : h.st === "w" ? 2 : 1.5) + (on ? 2 : 0),
          strokeOpacity: dim ? 0.18 : h.st === "r" ? 0.5 : on ? 1 : 0.8,
          strokeStyle: h.st === "r" ? "shortdash" : h.st === "w" ? "dash" : "solid",
        });
        line.setMap(map);
        links.set(h.hospitalId, { line, key });
      }
    }
    links.forEach((l, id) => {
      if (wanted.has(id)) return;
      l.line.setMap(null);
      links.delete(id);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, overview?.hospitals, selected, hoverHospital, ambulanceSim]);

  return (
    <section
      className={css({
        position: "absolute",
        inset: "0",
        zIndex: "0",
        overflow: "hidden",
        backgroundColor: "#F4F1EA",
      })}
    >
      <style>{"@keyframes ctlring{0%{transform:scale(.6);opacity:.55}100%{transform:scale(2.4);opacity:0}}"}</style>
      <div
        ref={containerRef}
        role="img"
        aria-label="선택한 사건의 요청 병원 응답 상태와 구급차 위치를 표시한 관제 지도"
        className={css({ position: "absolute", inset: "0", zIndex: "0" })}
      />
      {(!ready || error || !overview) && (
        <div
          className={css({
            position: "absolute", inset: "0", zIndex: "1", display: "flex", alignItems: "center",
            justifyContent: "center", textAlign: "center", paddingX: "4", fontSize: "sm",
          })}
          style={{ color: error ? "#D93025" : C.muted, background: "#F4F1EA" }}
        >
          {error ?? (!ready ? "지도를 불러오는 중..." : "hub에서 병원·구급차 목록을 받는 중...")}
        </div>
      )}
      {children}
    </section>
  );
}
