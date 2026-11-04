"use client";

import type { CSSProperties } from "react";
import { C, shortHospital } from "@/lib/control-map";
import type { FireHq } from "@/lib/fire-hq";
import type { MciAssessment } from "@/types/dashboard";

// 다수 사상자 약도(2026-11-04) — 외부 지도 없이 실제 좌표 비율대로 그린다(위도·경도 → 화면, 경도는 cos(위도)로 보정).
// 사고 지점 · 분석 반경 · 추천 구급차 · 예상 분배 병원(인원) · 구급차가 모자라면 지원 요청 본부(대략 위치)와 연결선.
// 처음 한 번 영상처럼 펼쳐진다(에이전트 분석 순서와 같은 박자): 반경이 퍼짐 → 병원이 켜지며 선이 그어짐 → 구급차가 사고 지점
// 쪽으로 출발 → 부족하면 지원 본부로 붉은 선. 끝나면 멈춘 그림으로 남는다(판단하는 동안 움직이지 않게). 사고 지점 파동만 계속.
// 움직임 줄이기 설정이면 바로 완성된 그림을 보인다. 새 분석이 오면(key=incidentId) 다시 펼친다.

const W = 520;
const H = 340;
const PAD = 34;

const CSS = `
.mci-ring{transform-box:fill-box;transform-origin:center;animation:mciRing .7s ease-out both}
.mci-fade{opacity:0;animation:mciFade .45s ease-out forwards}
.mci-draw{stroke-dasharray:1;stroke-dashoffset:1;animation:mciDraw .7s ease-out forwards}
.mci-go{animation:mciGo 1.8s ease-in-out forwards}
.mci-pulse{transform-box:fill-box;transform-origin:center;animation:mciPulse 1.8s ease-out infinite}
@keyframes mciRing{from{transform:scale(0);opacity:0}to{transform:scale(1);opacity:1}}
@keyframes mciFade{to{opacity:1}}
@keyframes mciDraw{to{stroke-dashoffset:0}}
@keyframes mciGo{to{transform:translate(var(--dx),var(--dy))}}
@keyframes mciPulse{from{transform:scale(1);opacity:.55}to{transform:scale(3.2);opacity:0}}
@media (prefers-reduced-motion:reduce){.mci-ring,.mci-fade,.mci-draw,.mci-go,.mci-pulse{animation:none!important;opacity:1;stroke-dashoffset:0}}
`;

const delay = (sec: number): CSSProperties => ({ animationDelay: `${sec}s` });

export function MciSketch({ a, support }: { a: MciAssessment; support: (FireHq & { km: number })[] }) {
  const kx = Math.cos((a.gps.lat * Math.PI) / 180);
  const toXY = (p: { lat: number; lng: number }) => ({ x: (p.lng - a.gps.lng) * kx, y: -(p.lat - a.gps.lat) });
  const radiusDeg = a.radiusKm / 111;
  // 범위는 사고 지점·분배 병원·추천 구급차에만 맞춘다 — 반경 원·먼 지원 본부까지 넣으면 가운데에 점이 뭉쳤다(2026-11-04).
  // 최소 범위(약 2km)는 둬서 한두 점만 있을 때 과하게 확대되지 않게 한다.
  const minSpan = 2 / 111;
  const pts = [
    { x: -minSpan, y: -minSpan }, { x: minSpan, y: minSpan },
    ...a.plan.map(toXY), ...a.ambulances.map(toXY),
  ];
  const minX = Math.min(...pts.map((p) => p.x)), maxX = Math.max(...pts.map((p) => p.x));
  const minY = Math.min(...pts.map((p) => p.y)), maxY = Math.max(...pts.map((p) => p.y));
  const scale = Math.min((W - 2 * PAD) / Math.max(1e-6, maxX - minX), (H - 2 * PAD) / Math.max(1e-6, maxY - minY));
  const ox = (W - (maxX - minX) * scale) / 2 - minX * scale;
  const oy = (H - (maxY - minY) * scale) / 2 - minY * scale;
  const px = (p: { lat: number; lng: number }) => { const q = toXY(p); return { x: ox + q.x * scale, y: oy + q.y * scale }; };
  const c = px(a.gps);
  const r = radiusDeg * scale;
  // 그림 밖의 지원 본부는 가장자리에 방향 표시로 — 사고 지점에서 본부 쪽으로 그은 선이 테두리와 만나는 곳
  const edge = (p: { x: number; y: number }) => {
    const dx = p.x - c.x, dy = p.y - c.y;
    const inside = p.x >= 16 && p.x <= W - 16 && p.y >= 16 && p.y <= H - 16;
    if (inside) return { ...p, clipped: false };
    const t = Math.min(
      dx > 0 ? (W - 22 - c.x) / dx : dx < 0 ? (22 - c.x) / dx : Infinity,
      dy > 0 ? (H - 22 - c.y) / dy : dy < 0 ? (22 - c.y) / dy : Infinity,
    );
    return { x: c.x + dx * t, y: c.y + dy * t, clipped: true, angle: (Math.atan2(dy, dx) * 180) / Math.PI };
  };
  // 같은 좌표(같은 센터의 구급차 여러 대)는 작은 원 위로 벌려 그린다
  const seen = new Map<string, number>();
  const spread = (p: { x: number; y: number }) => {
    const key = `${Math.round(p.x)}:${Math.round(p.y)}`;
    const n = seen.get(key) ?? 0;
    seen.set(key, n + 1);
    if (n === 0) return p;
    const ang = n * 2.4;
    return { x: p.x + Math.cos(ang) * 9, y: p.y + Math.sin(ang) * 9 };
  };
  // 박자: 반경 0~0.7초 → 병원 0.6초부터 하나씩 → 구급차 출발 1.4초 → 지원 본부 2.4초부터
  const hospitalAt = (i: number) => 0.6 + i * 0.12;
  const ambAt = 1.4;
  const supportAt = (i: number) => 2.4 + i * 0.25;

  return (
    <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="다수 사상자 약도" style={{ width: "100%", height: "auto", borderRadius: 12, background: "#F7F5FD", border: `1px solid ${C.line}` }}>
      <style>{CSS}</style>
      <circle className="mci-ring" cx={c.x} cy={c.y} r={r} fill="rgba(107,91,210,.07)" stroke="#8E7CF0" strokeDasharray="5 4" />
      <text className="mci-fade" style={delay(0.5)} x={c.x} y={c.y - r - 5} textAnchor="middle" fontSize="10" fill="#6B5BD2">분석 반경 {a.radiusKm}km</text>
      {support.map((h, i) => {
        const p = edge(px(h));
        const lx = Math.min(W - 40, Math.max(40, p.x));
        const ly = p.y > H / 2 ? p.y - 12 : p.y + 20;
        return (
          <g key={h.name}>
            <line className="mci-draw" style={delay(supportAt(i))} pathLength={1} x1={c.x} y1={c.y} x2={p.x} y2={p.y} stroke="#D9434B" strokeWidth="1.8" strokeDasharray="1" opacity=".75" />
            <g className="mci-fade" style={delay(supportAt(i) + 0.5)}>
              {p.clipped
                ? <path d="M -7 -6 L 7 0 L -7 6 Z" transform={`translate(${p.x} ${p.y}) rotate(${p.angle})`} fill="#D9434B" />
                : <rect x={p.x - 6} y={p.y - 6} width="12" height="12" rx="3" fill="#D9434B" />}
              <text x={lx} y={ly} textAnchor="middle" fontSize="11" fontWeight="700" fill="#B3261E" stroke="#F7F5FD" strokeWidth="3" paintOrder="stroke">{h.city} 본부 {Math.round(h.km)}km</text>
            </g>
          </g>
        );
      })}
      {a.plan.map((h, i) => {
        const p = px(h);
        return (
          <g key={h.hospitalId}>
            <line className="mci-draw" style={delay(hospitalAt(i))} pathLength={1} x1={c.x} y1={c.y} x2={p.x} y2={p.y} stroke="#6B5BD2" strokeWidth={1 + h.count * 0.6} opacity=".35" />
            <g className="mci-fade" style={delay(hospitalAt(i) + 0.35)}>
              <circle cx={p.x} cy={p.y} r={6 + h.count} fill="#6B5BD2" stroke="#fff" strokeWidth="1.5" />
              <text x={p.x} y={p.y + 3.5} textAnchor="middle" fontSize="9.5" fontWeight="900" fill="#fff">{h.count}</text>
              <text x={p.x} y={p.y - 10 - h.count} textAnchor="middle" fontSize="9.5" fontWeight="700" fill="#3B2F8F" stroke="#F7F5FD" strokeWidth="3" paintOrder="stroke">
                {shortHospital(h.name).replace(/(대학교|의과대학|부속|학교법인)/g, "").slice(0, 10)}
              </text>
            </g>
          </g>
        );
      })}
      {a.ambulances.map((m, i) => {
        const p = spread(px(m));
        // 기지에서 사고 지점 쪽으로 80%까지 이동한 모습으로 멈춘다 — "출동하면 이렇게 모인다"는 미리 보기
        const go = { "--dx": `${(c.x - p.x) * 0.8}px`, "--dy": `${(c.y - p.y) * 0.8}px`, ...delay(ambAt + i * 0.05) } as CSSProperties;
        return (
          <g key={m.apid} className="mci-fade" style={delay(ambAt - 0.3)}>
            <rect className="mci-go" style={go} x={p.x - 4} y={p.y - 4} width="8" height="8" rx="1.5" fill="#F26B1D" stroke="#fff" strokeWidth="1" />
          </g>
        );
      })}
      <circle className="mci-pulse" cx={c.x} cy={c.y} r="8" fill="#D9434B" />
      <circle cx={c.x} cy={c.y} r="8" fill="#D9434B" stroke="#fff" strokeWidth="2" />
      <text x={c.x} y={c.y + 22} textAnchor="middle" fontSize="11" fontWeight="900" fill={C.navy}>사고 지점</text>
      <g fontSize="10" fill={C.ink2}>
        <circle cx="14" cy={H - 44} r="5" fill="#6B5BD2" /><text x="24" y={H - 40}>분배 병원(숫자=인원)</text>
        <rect x="9" y={H - 31} width="10" height="10" rx="2" fill="#F26B1D" /><text x="24" y={H - 22}>추천 구급차(출동하면 모이는 방향)</text>
        {support.length > 0 && <><rect x="9" y={H - 15} width="10" height="10" rx="2" fill="#D9434B" /><text x="24" y={H - 6}>지원 요청 본부(대략 위치)</text></>}
      </g>
    </svg>
  );
}
