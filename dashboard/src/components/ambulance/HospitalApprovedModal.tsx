"use client";

import { useEffect, useRef, useState } from "react";
import { AD } from "@/components/ambulance/ambulance-design";
import { liveBedReliability } from "@/lib/bedReliability";
import type { HospitalCandidate, ReliabilityConfidence } from "@/types/dashboard";

// 병원 수용 승인 알림(2026-10-06) — 병원(병원 대시보드·시연 콘솔)이 [승인]을 누르면 구급차 대시보드에 그 병원의 정보를
// 띄운다. 0.5초에 걸쳐 나타나 5초 머문 뒤 0.5초에 걸쳐 사라진다. [이송 승인]으로 바로 이송을 확정할 수 있고, [닫기]는
// 기다리지 않고 바로 닫는다. 시연 일시정지 중엔 남은 시간도 멈추고(사라지던 중이면 다시 보인다) 두 버튼도 막히며, 재개하면 이어서 센다.
// 표시 값은 전부 hub 매칭 결과 그대로다(병상·신고는 E-Gen 규칙, 신뢰도는 AI 확률).

const FADE_MS = 500;
const HOLD_MS = 5000;

const CONFIDENCE_LABEL: Record<ReliabilityConfidence, string> = { high: "신뢰도 높음", medium: "신뢰도 보통", low: "신뢰도 낮음" };

const pct = (p: number) => `${Math.round(p * 100)}%`;

// 시안 색(2026-10-07 "병원 수용 승인" 모달)
const M = {
  head: "#467A50",
  green: "#3F7A4C",
  body: "#F7F8F9",
  line: "#E3E6EA",
  ink: "#1B2430",
  sub: "#5A6676",
  muted: "#8A94A2",
  ai: "#2F4FA2",
  aiSoft: "#E8EEF8",
  amber: "#8A4B00",
  amberSoft: "#FFF6E8",
  amberLine: "#EFD3A6",
  red: "#B3261E",
  redSoft: "#FDEDEB",
  redLine: "#F2C2BD",
  greenSoft: "#EAF4EC",
  greenLine: "#C3DEC8",
} as const;

const card = { background: "#fff", border: `1px solid ${M.line}`, borderRadius: 18, boxSizing: "border-box" } as const;

/** 중증질환 신고 칸 — 질환군 신고(E-Gen, 규칙)와 심평원 대조 판정(규칙)으로 가능·불가·확인 필요를 고른다 */
function severeView(h: HospitalCandidate): { title: string; big: string; sub: string; tone: "ok" | "no" | "check" } {
  const rel = h.reliability;
  const fresh = h.severeFreshness;
  const title = fresh?.group ?? rel?.group ?? "중증질환 신고";
  const conf = rel ? CONFIDENCE_LABEL[rel.confidence] : null;
  if (!rel && !fresh) return { title, big: "해당 없음", sub: "관련 질환군 신고 없음", tone: "check" };
  const declared = fresh?.value ?? (rel && rel.score >= 1 ? "Y" : rel && rel.score <= 0.2 ? "불가능" : null);
  const sub = [declared === "Y" ? "수용 신고" : declared === "불가능" ? "불가 신고" : "신고 미상", conf].filter(Boolean).join(" · ");
  if (declared === "불가능") return { title, big: "수용 불가", sub, tone: "no" };
  if (declared === "Y" && rel?.confidence !== "low") return { title, big: "수용 가능", sub, tone: "ok" };
  return { title, big: "확인 필요", sub, tone: "check" };
}

export function HospitalApprovedModal({ hospital, paused, onApprove, onClose }: {
  hospital: HospitalCandidate;
  paused: boolean;
  onApprove: () => void;
  onClose: () => void;
}) {
  const [shown, setShown] = useState(false);
  const [nowMs, setNowMs] = useState(() => Date.now());
  const closeRef = useRef(onClose);
  const pausedRef = useRef(paused);
  useEffect(() => {
    closeRef.current = onClose;
    pausedRef.current = paused;
  }, [onClose, paused]);

  // 띄운 뒤 흐른 시간은 일시정지가 아닐 때만 쌓는다 — 0.5초 나타남 → 5초 머묾 → 0.5초 사라짐 → 닫힘
  useEffect(() => {
    const raf = requestAnimationFrame(() => setShown(true));
    let elapsed = 0;
    let last = Date.now();
    const timer = setInterval(() => {
      const t = Date.now();
      if (!pausedRef.current) elapsed += t - last;
      last = t;
      setNowMs(t);
      if (elapsed >= FADE_MS + HOLD_MS) setShown(false);
      if (elapsed >= FADE_MS + HOLD_MS + FADE_MS) closeRef.current();
    }, 100);
    return () => {
      cancelAnimationFrame(raf);
      clearInterval(timer);
    };
  }, []);
  const visible = shown || paused;

  const bed = hospital.bedReliability ? liveBedReliability(hospital.bedReliability, nowMs) : null;
  const byType = (field: string) => {
    const br = hospital.bedReliabilityByType?.[field];
    return br ? pct(liveBedReliability(br, nowMs).rArrive) : "—";
  };
  const travel = hospital.travelMin != null ? Math.max(1, Math.round(hospital.travelMin)) : null;
  const sev = severeView(hospital);
  const sevStyle = sev.tone === "ok"
    ? { bg: M.greenSoft, line: M.greenLine, fg: M.green }
    : sev.tone === "no" ? { bg: M.redSoft, line: M.redLine, fg: M.red } : { bg: M.amberSoft, line: M.amberLine, fg: M.amber };
  const bedColor = hospital.bedCountUnknown ? M.muted : hospital.availableBedCount > 0 ? M.green : M.red;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={`${hospital.name} 수용 승인`}
      style={{
        position: "fixed", inset: 0, zIndex: 9000, display: "flex", alignItems: "center", justifyContent: "center",
        padding: 16, background: "rgba(20,33,61,.35)", opacity: visible ? 1 : 0, transition: `opacity ${FADE_MS}ms ease`,
      }}
    >
      <div style={{
        width: 500, maxWidth: "100%", maxHeight: "calc(100vh - 32px)", overflowY: "auto", boxSizing: "border-box",
        background: M.body, borderRadius: 22, boxShadow: "0 24px 70px rgba(20,33,61,.35)",
        transform: visible ? "translateY(0)" : "translateY(8px)", transition: `transform ${FADE_MS}ms ease`,
      }}>
        {/* 머리: 승인 · 병원 이름 · 응급의료기관 지정 · 도착까지 */}
        <div style={{ background: M.head, color: "#fff", padding: "26px 28px 22px", display: "flex", alignItems: "flex-end", gap: 16 }}>
          <div style={{ flex: "1 1 auto", minWidth: 0, display: "flex", flexDirection: "column", gap: 12 }}>
            <span style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
              <span style={{ fontSize: 14, fontWeight: 700, background: "rgba(255,255,255,.2)", borderRadius: 999, padding: "6px 14px" }}>✓ 병원 수용 승인</span>
              {paused && <span style={{ fontSize: 13, fontWeight: 700, background: "#fff", color: M.amber, borderRadius: 999, padding: "5px 12px" }}>⏸ 시연 일시정지</span>}
            </span>
            <span style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
              <span style={{ fontSize: 28, fontWeight: 900, letterSpacing: "-0.02em", wordBreak: "keep-all" }}>{hospital.name}</span>
              {hospital.emergencyLevel && (
                <span style={{ fontSize: 12.5, fontWeight: 700, border: "1px solid rgba(255,255,255,.75)", borderRadius: 8, padding: "3px 8px", whiteSpace: "nowrap" }}>
                  {hospital.emergencyLevel}
                </span>
              )}
            </span>
          </div>
          {travel != null && (
            <div style={{ flex: "none", textAlign: "right" }}>
              <div style={{ fontSize: 13, opacity: 0.9 }}>도착까지</div>
              <div style={{ fontSize: 30, fontWeight: 900, lineHeight: 1.1 }}>{travel}분</div>
            </div>
          )}
        </div>

        <div style={{ padding: "22px 28px 26px", display: "flex", flexDirection: "column", gap: 16 }}>
          {/* 병상 정보 신뢰도(AI) — 지금 → 도착 시 */}
          <div style={{ ...card, padding: "18px 20px" }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <span style={{ fontSize: 12, fontWeight: 800, color: M.ai, background: M.aiSoft, borderRadius: 6, padding: "3px 8px" }}>AI</span>
              <span style={{ fontSize: 16, fontWeight: 800, color: M.ink }}>병상 정보 신뢰도</span>
              <span style={{ flex: "1 1 0" }} />
              <span style={{ fontSize: 12.5, color: M.sub }}>도착하는 동안의 변화</span>
            </div>
            {bed ? <TrendChart now={bed.authority} arrive={bed.rArrive} travel={travel} /> : (
              <div style={{ padding: "26px 0 8px", textAlign: "center", fontSize: 14, color: M.muted }}>신뢰도 정보 없음</div>
            )}
          </div>

          {/* 수술실 · 입원실(AI) · 중증질환 신고(규칙) */}
          <div style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))", gap: 10 }}>
            {([["수술실", "hvoc"], ["입원실", "hvgc"]] as const).map(([label, field]) => (
              <div key={field} style={{ ...card, padding: "16px 14px", display: "flex", flexDirection: "column", gap: 8 }}>
                <span style={{ fontSize: 13, color: M.sub }}>{label}</span>
                <span style={{ fontSize: 26, fontWeight: 900, color: M.ink }}>{byType(field)}</span>
                <span style={{ fontSize: 12, fontWeight: 700, color: M.ai }}>AI 신뢰도</span>
              </div>
            ))}
            <div style={{ ...card, background: sevStyle.bg, border: `1px solid ${sevStyle.line}`, padding: "16px 14px", display: "flex", flexDirection: "column", gap: 8 }}>
              <span style={{ fontSize: 13, color: sevStyle.fg, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={sev.title}>{sev.title}</span>
              <span style={{ fontSize: 22, fontWeight: 900, color: sevStyle.fg }}>{sev.big}</span>
              <span style={{ fontSize: 12, fontWeight: 700, color: sevStyle.fg }}>{sev.sub}</span>
            </div>
          </div>

          {/* 응급실 병상(E-Gen) */}
          <div style={{ ...card, padding: "16px 22px", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
            <span style={{ fontSize: 16, fontWeight: 700, color: M.ink }}>
              응급실 병상{hospital.bedDataStale && <span style={{ fontSize: 12, fontWeight: 500, color: M.muted }}> · 1일 넘은 값</span>}
            </span>
            {hospital.bedCountUnknown ? (
              <span style={{ fontSize: 26, fontWeight: 900, color: bedColor }}>미상</span>
            ) : (
              <span style={{ display: "flex", alignItems: "baseline", gap: 2, color: bedColor }}>
                <span style={{ fontSize: 40, fontWeight: 900, lineHeight: 1 }}>{hospital.availableBedCount}</span>
                <span style={{ fontSize: 18, fontWeight: 800 }}>석</span>
              </span>
            )}
          </div>

          <div style={{ display: "flex", gap: 10 }}>
            <button
              type="button"
              // 시연 일시정지 중엔 닫기도 막는다 — 모든 조작이 멈춘 상태를 유지하고, 재개하면 다시 눌린다
              disabled={paused}
              onClick={onClose}
              title={paused ? "시연 일시정지 중에는 닫을 수 없습니다" : undefined}
              style={{
                flex: "0 0 30%", minHeight: 52, border: `1.5px solid ${M.line}`, borderRadius: 14, background: paused ? M.body : "#fff",
                color: paused ? M.muted : M.ink, fontSize: 16, fontWeight: 800, cursor: paused ? "not-allowed" : "pointer", fontFamily: "inherit",
              }}
            >
              닫기
            </button>
            <button
              type="button"
              // 시연 일시정지 중엔 누를 수 없다(누른 뒤 거부되며 모달이 닫히지 않게) — 재개하면 다시 눌린다
              disabled={paused}
              onClick={onApprove}
              title={paused ? "시연 일시정지 중에는 이송 승인을 할 수 없습니다" : undefined}
              style={{
                flex: "1 1 auto", minHeight: 52, border: "none", borderRadius: 14, background: paused ? AD.control : M.head,
                color: paused ? M.sub : "#fff", fontSize: 17, fontWeight: 800, cursor: paused ? "not-allowed" : "pointer", fontFamily: "inherit",
              }}
            >
              {paused ? "이송 승인 (일시정지 중)" : "이송 승인"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

/** 지금 → 도착 시 유효 확률(AI) 두 점을 잇는 선 */
function TrendChart({ now, arrive, travel }: { now: number; arrive: number; travel: number | null }) {
  const W = 360;
  const H = 120;
  const top = 34;
  const bottom = 92;
  const lo = Math.max(0, Math.min(now, arrive) - 0.15);
  const hi = Math.min(1, Math.max(now, arrive) + 0.05);
  const y = (p: number) => bottom - ((p - lo) / Math.max(hi - lo, 0.01)) * (bottom - top);
  const x0 = 8;
  const x1 = W - 8;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" style={{ display: "block", marginTop: 10 }} role="img"
      aria-label={`병상 정보 신뢰도 지금 ${pct(now)}, 도착 시 ${pct(arrive)}`}>
      <line x1={x0} x2={x1} y1={14} y2={14} stroke={M.line} />
      <path d={`M${x0},${y(now)} L${x1},${y(arrive)} L${x1},${bottom} L${x0},${bottom} Z`} fill={M.aiSoft} />
      <line x1={x0} y1={y(now)} x2={x1} y2={y(arrive)} stroke={M.ai} strokeWidth={2.5} />
      <circle cx={x0} cy={y(now)} r={5} fill={M.ai} />
      <circle cx={x1} cy={y(arrive)} r={5.5} fill="#fff" stroke={M.ai} strokeWidth={2.5} />
      <text x={x0} y={y(now) - 12} fontSize={16} fontWeight={900} fill={M.ink}>{pct(now)}</text>
      <text x={x1} y={y(arrive) - 12} fontSize={16} fontWeight={900} fill={M.ink} textAnchor="end">{pct(arrive)}</text>
      <text x={x0} y={H - 6} fontSize={11.5} fill={M.sub}>지금</text>
      <text x={x1} y={H - 6} fontSize={11.5} fill={M.sub} textAnchor="end">도착 시{travel != null ? ` (+${travel}분)` : ""}</text>
    </svg>
  );
}
