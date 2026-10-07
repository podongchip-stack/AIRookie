"use client";

import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { AD } from "@/components/ambulance/ambulance-design";
import { formatDeclarationAge, liveBedReliability } from "@/lib/bedReliability";
import type { BedReliabilityMatch, HospitalCandidate, ReliabilityConfidence } from "@/types/dashboard";

// 병원 수용 승인 알림(2026-10-06, 시안 2026-10-07) — 병원(병원 대시보드·시연 콘솔)이 [승인]을 누르면 구급차 대시보드에
// 그 병원 정보를 띄운다. 0.5초에 걸쳐 나타나 5초 머문 뒤 0.5초에 걸쳐 사라지고, 위의 파란 막대가 남은 5초를 보여 준다.
// [이송 확인]은 이송 승인(final_approval), [닫기]는 기다리지 않고 바로 닫는다. 시연 일시정지 중엔 시간이 멈추고(사라지던
// 중이면 다시 보인다) 두 버튼이 막힌다.
// 큰 숫자는 그 정보가 **틀릴 확률** = 1 − 유효 확률(AI 병상 신뢰도). 중증질환 신고는 학습 모델이 없어(규칙 기반 신고
// 나이·심평원 대조 판정) 확률 대신 신고 상태를 보인다 — 없는 확률을 만들어 보이지 않는다.

const FADE_MS = 500;
const HOLD_MS = 5000;
/** 틀릴 확률이 이 이하면 "그대로 믿어도 돼요" */
const OK_MAX = 0.2;
/** 이 이하면 "확인이 필요해요", 넘으면 "전화로 확인하세요" */
const CHECK_MAX = 0.5;

const C = {
  navy: "#3F5AA6",
  navySoft: "#EEF3FB",
  navyLine: "#C9D6EE",
  card: "#F1F4F9",
  ink: "#1B2430",
  sub: "#5A6676",
  muted: "#8A94A2",
  track: "#E3E8F0",
  amber: "#B45309",
  amberSoft: "#FFF6E8",
  amberLine: "#EFD3A6",
  red: "#B3261E",
  redSoft: "#FDEDEB",
  redLine: "#F2C2BD",
} as const;

const CONFIDENCE_LABEL: Record<ReliabilityConfidence, string> = { high: "신뢰도 높음", medium: "신뢰도 보통", low: "신뢰도 낮음" };

const pct = (p: number) => `${Math.round(p * 100)}%`;

type Tone = "ok" | "check" | "call";
const toneOf = (err: number): Tone => (err <= OK_MAX ? "ok" : err <= CHECK_MAX ? "check" : "call");
const TONE_TEXT: Record<Tone, string> = { ok: "그대로 믿어도 돼요", check: "확인이 필요해요", call: "전화로 확인하세요" };
const TONE_COLOR: Record<Tone, string> = { ok: C.navy, check: C.amber, call: C.red };

function updatedAgo(br: BedReliabilityMatch, nowMs: number): string | null {
  const born = br.bornAt ? Date.parse(br.bornAt) : NaN;
  if (Number.isNaN(born)) return null;
  const min = Math.floor(Math.max(nowMs - born, 0) / 60000);
  if (min < 1) return "방금 갱신";
  return min < 60 ? `갱신 ${min}분 전` : `갱신 ${Math.floor(min / 60)}시간 전`;
}

export function HospitalApprovedModal({ hospital, paused, onApprove, onClose }: {
  hospital: HospitalCandidate;
  paused: boolean;
  onApprove: () => void;
  onClose: () => void;
}) {
  const [shown, setShown] = useState(false);
  const [nowMs, setNowMs] = useState(() => Date.now());
  const [elapsed, setElapsed] = useState(0);
  const closeRef = useRef(onClose);
  const pausedRef = useRef(paused);
  useEffect(() => {
    closeRef.current = onClose;
    pausedRef.current = paused;
  }, [onClose, paused]);

  // 띄운 뒤 흐른 시간은 일시정지가 아닐 때만 쌓는다 — 0.5초 나타남 → 5초 머묾 → 0.5초 사라짐 → 닫힘
  useEffect(() => {
    const raf = requestAnimationFrame(() => setShown(true));
    let acc = 0;
    let last = Date.now();
    const timer = setInterval(() => {
      const t = Date.now();
      if (!pausedRef.current) acc += t - last;
      last = t;
      setNowMs(t);
      setElapsed(acc);
      if (acc >= FADE_MS + HOLD_MS) setShown(false);
      if (acc >= FADE_MS + HOLD_MS + FADE_MS) closeRef.current();
    }, 100);
    return () => {
      cancelAnimationFrame(raf);
      clearInterval(timer);
    };
  }, []);
  const visible = shown || paused;
  const holdLeft = Math.min(Math.max(FADE_MS + HOLD_MS - elapsed, 0), HOLD_MS);

  // ── 틀릴 확률(AI) ──
  const bed = hospital.bedReliability ? liveBedReliability(hospital.bedReliability, nowMs) : null;
  const bedErrNow = bed ? 1 - bed.authority : null;
  const bedErrArrive = bed ? 1 - bed.rArrive : null;
  const typeCard = (field: string, title: string) => {
    const br = hospital.bedReliabilityByType?.[field];
    if (!br) return { title, err: null as number | null, nowErr: null as number | null, ago: null as string | null };
    const live = liveBedReliability(br, nowMs);
    return { title, err: 1 - live.rArrive, nowErr: 1 - live.authority, ago: updatedAgo(br, nowMs) };
  };
  const or = typeCard("hvoc", "수술실 병상 정보");
  const ward = typeCard("hvgc", "입원실 병상 정보");
  const errs = [bedErrNow, bedErrArrive, or.err, ward.err].filter((e): e is number => e != null);
  const worst = errs.length ? Math.max(...errs) : null;
  const overall: Tone | null = worst == null ? null : toneOf(worst);

  const bedTitle = hospital.bedCountUnknown ? "병상 수 미상" : hospital.availableBedCount > 0 ? "병상 여유 있음" : "병상 없음";
  const travel = hospital.travelMin != null ? Math.max(1, Math.round(hospital.travelMin)) : null;
  const severe = severeView(hospital);
  const bedDelta = bedErrNow != null && bedErrArrive != null ? Math.round((bedErrArrive - bedErrNow) * 100) : 0;

  const banner = overall == null
    ? { text: "병상 신뢰도 정보가 없어요", right: "", bg: C.card, line: C.track, fg: C.sub }
    : overall === "ok"
      ? { text: "모든 정보가 최신이고 안정적이에요", right: `${pct(OK_MAX)} 이하`, bg: C.navySoft, line: C.navyLine, fg: C.navy }
      : overall === "check"
        ? { text: "일부 정보는 확인이 필요해요", right: `최대 ${pct(worst!)}`, bg: C.amberSoft, line: C.amberLine, fg: C.amber }
        : { text: "전화로 병상을 먼저 확인하세요", right: `최대 ${pct(worst!)}`, bg: C.redSoft, line: C.redLine, fg: C.red };
  const approveSub = overall === "ok"
    ? "최신 · 안정적이라 전화 없이 이송해요"
    : overall == null ? "병상 신뢰도 정보 없이 이송해요" : "확인이 필요한 정보가 있어요";

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
        width: 540, maxWidth: "100%", maxHeight: "calc(100vh - 32px)", overflowY: "auto", boxSizing: "border-box",
        background: "#fff", borderRadius: 24, boxShadow: "0 24px 70px rgba(20,33,61,.35)", padding: "22px 24px 24px",
        display: "flex", flexDirection: "column", gap: 14,
        transform: visible ? "translateY(0)" : "translateY(8px)", transition: `transform ${FADE_MS}ms ease`,
      }}>
        {/* 남은 시간 막대 — 5초 동안 줄어든다 */}
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <div style={{ flex: "1 1 auto", height: 6, borderRadius: 3, background: C.track, overflow: "hidden" }}>
            <div style={{ width: `${(holdLeft / HOLD_MS) * 100}%`, height: "100%", borderRadius: 3, background: C.navy, transition: "width 100ms linear" }} />
          </div>
          <span style={{ flex: "none", fontSize: 12.5, color: paused ? C.amber : C.sub, fontWeight: paused ? 700 : 400 }}>
            {paused ? "⏸ 시연 일시정지" : `${Math.ceil(holdLeft / 1000)}초 뒤 닫힘`}
          </span>
        </div>

        {/* 머리: 승인 · 병원 · 등급·도착 · 응급실 병상 */}
        <div style={{ display: "flex", alignItems: "flex-end", gap: 16 }}>
          <div style={{ flex: "1 1 auto", minWidth: 0, display: "flex", flexDirection: "column", gap: 8 }}>
            <span style={{ alignSelf: "flex-start", fontSize: 13, fontWeight: 700, color: C.navy, background: C.navySoft, borderRadius: 999, padding: "5px 12px" }}>
              ✓ 병원 수용 승인
            </span>
            <span style={{ fontSize: 28, fontWeight: 900, color: C.ink, letterSpacing: "-0.02em", wordBreak: "keep-all" }}>{hospital.name}</span>
            <span style={{ fontSize: 13.5, color: C.sub }}>
              {[hospital.emergencyLevel, travel != null ? `도착까지 약 ${travel}분` : null].filter(Boolean).join(" · ")}
            </span>
          </div>
          <div style={{ flex: "none", textAlign: "right" }}>
            <div style={{ fontSize: 13, color: C.sub }}>응급실 병상{hospital.bedDataStale ? " · 1일 넘은 값" : ""}</div>
            {hospital.bedCountUnknown ? (
              <div style={{ fontSize: 34, fontWeight: 900, color: C.muted, lineHeight: 1.1 }}>미상</div>
            ) : (
              <div style={{ fontSize: 44, fontWeight: 900, color: hospital.availableBedCount > 0 ? C.navy : C.red, lineHeight: 1.05 }}>
                {hospital.availableBedCount}석
              </div>
            )}
          </div>
        </div>

        {/* 한 줄 요약 */}
        <div style={{ display: "flex", alignItems: "center", gap: 12, background: banner.bg, border: `1px solid ${banner.line}`, borderRadius: 16, padding: "12px 16px" }}>
          <span style={{ flex: "none", width: 34, height: 34, borderRadius: "50%", background: banner.fg, color: "#fff", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 16, fontWeight: 900 }}>
            {overall === "ok" ? "✓" : "!"}
          </span>
          <span style={{ flex: "1 1 auto", fontSize: 16, fontWeight: 800, color: C.ink }}>{banner.text}</span>
          {banner.right && <span style={{ flex: "none", fontSize: 13, color: C.sub }}>{banner.right}</span>}
        </div>

        <div style={{ fontSize: 13, color: C.sub }}>병원이 알려준 정보 · 큰 숫자 = 그 정보가 틀릴 확률(AI)</div>

        {/* 2×2 카드 */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: 10 }}>
          <Card>
            <CardTitle>{bedTitle}</CardTitle>
            {bedErrNow != null && bedErrArrive != null ? (
              <>
                <div style={{ display: "flex", alignItems: "stretch", alignSelf: "stretch" }}>
                  {([["지금 기준", bedErrNow], ["도착 시점", bedErrArrive]] as const).map(([label, err], i) => (
                    <div key={label} style={{ flex: "1 1 0", display: "flex", flexDirection: "column", alignItems: "center", gap: 2, borderLeft: i ? `1px solid ${C.track}` : undefined }}>
                      <span style={{ fontSize: 12.5, color: C.sub }}>{label}</span>
                      <Big color={TONE_COLOR[toneOf(err)]}>{pct(err)}</Big>
                    </div>
                  ))}
                </div>
                <Foot>
                  {[hospital.bedReliability ? updatedAgo(hospital.bedReliability, nowMs) : null,
                    bedDelta > 0 ? `도착 시 ${bedDelta}%p 더 위험` : "도착 때도 그대로"].filter(Boolean).join(" · ")}
                </Foot>
                <Verdict tone={toneOf(bedErrArrive)} />
              </>
            ) : <NoData />}
          </Card>

          <Card tone={severe.tone === "ok" ? undefined : severe.tone}>
            <CardTitle>{severe.title}</CardTitle>
            <Big color={severe.tone === "ok" ? C.navy : severe.tone === "no" ? C.red : C.amber} small>{severe.big}</Big>
            <Foot>{severe.foot}</Foot>
            <Foot strong>{severe.sub}</Foot>
          </Card>

          {[or, ward].map((c) => (
            <Card key={c.title}>
              <CardTitle>{c.title}</CardTitle>
              {c.err != null && c.nowErr != null ? (
                <>
                  <span style={{ fontSize: 12.5, color: C.sub }}>도착 시점</span>
                  <Big color={TONE_COLOR[toneOf(c.err)]}>{pct(c.err)}</Big>
                  <Foot>{[c.ago, `지금 ${pct(c.nowErr)}`].filter(Boolean).join(" · ")}</Foot>
                  <Verdict tone={toneOf(c.err)} />
                </>
              ) : <NoData />}
            </Card>
          ))}
        </div>

        {/* 버튼 */}
        <div style={{ display: "flex", gap: 10 }}>
          <button
            type="button"
            // 시연 일시정지 중엔 누를 수 없다(누른 뒤 거부되며 모달이 닫히지 않게) — 재개하면 다시 눌린다
            disabled={paused}
            onClick={onApprove}
            title={paused ? "시연 일시정지 중에는 이송 확인을 할 수 없습니다" : undefined}
            style={{
              flex: "1 1 auto", minHeight: 64, border: "none", borderRadius: 16, padding: "10px 20px",
              background: paused ? AD.control : C.navy, color: paused ? C.sub : "#fff",
              cursor: paused ? "not-allowed" : "pointer", fontFamily: "inherit",
              display: "flex", alignItems: "center", gap: 14, textAlign: "left",
            }}
          >
            <span style={{ fontSize: 24, fontWeight: 900 }}>✓</span>
            <span style={{ display: "flex", flexDirection: "column", gap: 2 }}>
              <span style={{ fontSize: 18, fontWeight: 900 }}>{paused ? "이송 확인 (일시정지 중)" : "이송 확인"}</span>
              <span style={{ fontSize: 12.5, fontWeight: 600, opacity: 0.9 }}>{approveSub}</span>
            </span>
          </button>
          <button
            type="button"
            // 시연 일시정지 중엔 닫기도 막는다 — 모든 조작이 멈춘 상태를 유지하고, 재개하면 다시 눌린다
            disabled={paused}
            onClick={onClose}
            title={paused ? "시연 일시정지 중에는 닫을 수 없습니다" : undefined}
            style={{
              flex: "0 0 22%", minHeight: 64, border: `1.5px solid ${C.track}`, borderRadius: 16,
              background: paused ? C.card : "#fff", color: paused ? C.muted : C.ink, fontSize: 17, fontWeight: 800,
              cursor: paused ? "not-allowed" : "pointer", fontFamily: "inherit",
            }}
          >
            닫기
          </button>
        </div>
      </div>
    </div>
  );
}

/** 중증질환 신고 칸 — 학습 모델이 없어 확률 대신 신고 상태(E-Gen)·신고 나이(규칙)·심평원 대조 판정(규칙)을 보인다 */
function severeView(h: HospitalCandidate): { title: string; big: string; foot: string; sub: string; tone: "ok" | "no" | "check" } {
  const rel = h.reliability;
  const fresh = h.severeFreshness;
  const group = fresh?.group ?? rel?.group ?? null;
  if (!group) return { title: "중증질환 신고", big: "해당 없음", foot: "예상 병명과 맞는 질환군 없음", sub: "", tone: "check" };
  const declared = fresh?.value ?? (rel && rel.score >= 1 ? "Y" : rel && rel.score <= 0.2 ? "불가능" : null);
  const conf = rel ? `심평원 대조 ${CONFIDENCE_LABEL[rel.confidence]}` : "";
  const foot = fresh
    ? `신고 ${formatDeclarationAge(fresh.ageSec, fresh.ageIsMin)}${fresh.ruleRemainingSec > 0 ? ` · 만료까지 ${Math.max(1, Math.round(fresh.ruleRemainingSec / 3600))}시간` : ""}`
    : "신고 시각 정보 없음";
  if (declared === "불가능") return { title: group, big: "수용 불가 신고", foot, sub: conf, tone: "no" };
  if (declared === "Y" && rel?.confidence !== "low") return { title: `${group} 가능`, big: "가능 신고", foot, sub: conf, tone: "ok" };
  return { title: group, big: declared === "Y" ? "가능 · 확인 필요" : "확인 필요", foot, sub: conf, tone: "check" };
}

function Card({ children, tone }: { children: ReactNode; tone?: "no" | "check" }) {
  const bg = tone === "no" ? C.redSoft : tone === "check" ? C.amberSoft : C.card;
  return (
    <div style={{ background: bg, borderRadius: 18, padding: "16px 12px", display: "flex", flexDirection: "column", alignItems: "center", gap: 6, textAlign: "center", minHeight: 150, justifyContent: "center" }}>
      {children}
    </div>
  );
}

function CardTitle({ children }: { children: ReactNode }) {
  return <span style={{ fontSize: 16, fontWeight: 800, color: C.ink }}>{children}</span>;
}

function Big({ children, color, small }: { children: ReactNode; color: string; small?: boolean }) {
  return <span style={{ fontSize: small ? 26 : 38, fontWeight: 900, color, lineHeight: 1.15 }}>{children}</span>;
}

function Foot({ children, strong }: { children: ReactNode; strong?: boolean }) {
  if (!children) return null;
  return <span style={{ fontSize: 13, color: strong ? C.ink : C.sub, fontWeight: strong ? 700 : 400 }}>{children}</span>;
}

function Verdict({ tone }: { tone: Tone }) {
  return <span style={{ fontSize: 13.5, fontWeight: 800, color: tone === "ok" ? C.ink : TONE_COLOR[tone] }}>{TONE_TEXT[tone]}</span>;
}

function NoData() {
  return <span style={{ fontSize: 14, color: C.muted, padding: "18px 0" }}>신뢰도 정보 없음</span>;
}
