"use client";

import { C } from "@/lib/control-map";
import type { FireHq } from "@/lib/fire-hq";
import type { MciAssessment } from "@/types/dashboard";

// 다수 사상자 약도(2026-11-04) — 외부 지도 없이 실제 좌표 비율대로 그린다(위도·경도 → 화면, 경도는 cos(위도)로 보정).
// 사고 지점 · 분석 반경 · 추천 구급차 · 예상 분배 병원(인원) · 구급차가 모자라면 지원 요청 본부(대략 위치)와 연결선.

const W = 520;
const H = 300;
const PAD = 34;

export function MciSketch({ a, support }: { a: MciAssessment; support: (FireHq & { km: number })[] }) {
  const lat0 = a.gps.lat;
  const kx = Math.cos((lat0 * Math.PI) / 180);
  const toXY = (p: { lat: number; lng: number }) => ({ x: (p.lng - a.gps.lng) * kx, y: -(p.lat - a.gps.lat) });
  const radiusDeg = a.radiusKm / 111;
  const pts = [
    { x: -radiusDeg, y: -radiusDeg }, { x: radiusDeg, y: radiusDeg },
    ...a.plan.map(toXY), ...a.ambulances.map(toXY), ...support.map(toXY),
  ];
  const minX = Math.min(...pts.map((p) => p.x)), maxX = Math.max(...pts.map((p) => p.x));
  const minY = Math.min(...pts.map((p) => p.y)), maxY = Math.max(...pts.map((p) => p.y));
  const scale = Math.min((W - 2 * PAD) / Math.max(1e-6, maxX - minX), (H - 2 * PAD) / Math.max(1e-6, maxY - minY));
  const ox = (W - (maxX - minX) * scale) / 2 - minX * scale;
  const oy = (H - (maxY - minY) * scale) / 2 - minY * scale;
  const px = (p: { lat: number; lng: number }) => { const q = toXY(p); return { x: ox + q.x * scale, y: oy + q.y * scale }; };
  const c = px(a.gps);
  const r = radiusDeg * scale;

  return (
    <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="다수 사상자 약도" style={{ width: "100%", height: "auto", borderRadius: 12, background: "#F7F5FD", border: `1px solid ${C.line}` }}>
      <circle cx={c.x} cy={c.y} r={r} fill="rgba(107,91,210,.07)" stroke="#8E7CF0" strokeDasharray="5 4" />
      <text x={c.x} y={c.y - r - 5} textAnchor="middle" fontSize="10" fill="#6B5BD2">분석 반경 {a.radiusKm}km</text>
      {support.map((h) => {
        const p = px(h);
        return (
          <g key={h.name}>
            <line x1={c.x} y1={c.y} x2={p.x} y2={p.y} stroke="#D9434B" strokeWidth="1.5" strokeDasharray="6 4" opacity=".7" />
            <rect x={p.x - 6} y={p.y - 6} width="12" height="12" rx="3" fill="#D9434B" />
            <text x={p.x} y={p.y + 18} textAnchor="middle" fontSize="10.5" fontWeight="700" fill="#B3261E">{h.city} {Math.round(h.km)}km</text>
          </g>
        );
      })}
      {a.plan.map((h) => {
        const p = px(h);
        return (
          <g key={h.hospitalId}>
            <line x1={c.x} y1={c.y} x2={p.x} y2={p.y} stroke="#6B5BD2" strokeWidth={1 + h.count * 0.6} opacity=".35" />
            <circle cx={p.x} cy={p.y} r={5 + h.count} fill="#6B5BD2" stroke="#fff" strokeWidth="1.5" />
            <text x={p.x} y={p.y + 3.5} textAnchor="middle" fontSize="9.5" fontWeight="900" fill="#fff">{h.count}</text>
          </g>
        );
      })}
      {a.ambulances.map((m) => {
        const p = px(m);
        return <rect key={m.apid} x={p.x - 4} y={p.y - 4} width="8" height="8" rx="1.5" fill="#F26B1D" stroke="#fff" strokeWidth="1" />;
      })}
      <circle cx={c.x} cy={c.y} r="8" fill="#D9434B" stroke="#fff" strokeWidth="2" />
      <text x={c.x} y={c.y + 22} textAnchor="middle" fontSize="11" fontWeight="900" fill={C.navy}>사고 지점</text>
      <g fontSize="10" fill={C.ink2}>
        <circle cx="14" cy={H - 44} r="5" fill="#6B5BD2" /><text x="24" y={H - 40}>분배 병원(숫자=인원)</text>
        <rect x="9" y={H - 31} width="10" height="10" rx="2" fill="#F26B1D" /><text x="24" y={H - 22}>추천 구급차</text>
        {support.length > 0 && <><rect x="9" y={H - 15} width="10" height="10" rx="2" fill="#D9434B" /><text x="24" y={H - 6}>지원 요청 본부(대략 위치)</text></>}
      </g>
    </svg>
  );
}
