"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { css } from "styled-system/css";
import { liveBedReliability } from "@/lib/bedReliability";
import type { BedReliabilityMatch } from "@/types/dashboard";

// 라이브 채점 보드(2026-10-03, 전면 개편). hub GET /verification/live — info의
// reliability.live_board가 실제 서빙 엔진으로 창(48시간)의 모든 병원 × 폴링을 재생·채점한 결과.
//
// 화면의 주장 하나: "E-Gen 숫자를 그냥 믿을 때보다, 엔진이 고른 값만 믿을 때 더 맞는다."
// 그 주장을 ① 라이브 유지율 그래프(20분마다 점 추가)가 지고, ② 못 믿을 값 보드와
// ③ 채점 기록이 받친다. 숫자 타일 나열 대신 문장 + 그래프로 말한다.

type BoardRow = {
  hpid: string;
  name: string;
  value: number;
  bornAt: string;
  predictedSurvivalSec: number;
  sigma: number;
  authorityAtBuild: number;
  ttlSec: number;
};
type FeedItem = {
  ts: string;
  hpid: string;
  name: string;
  claimValue: number;
  newValue: number;
  delta: number;
  ageMin: number;
  pValid: number;
  becameFull: boolean;
};
type PollStat = {
  ts: string;
  n: number;
  held: number;
  hiN: number;
  hiHeld: number;
  warnN: number;
  warnHeld: number;
  breaks: number;
};
type CalBin = { range: string; total: number; predictedPct: number | null; actualPct: number | null };
type RegionStat = {
  label: string;
  hospitals: number;
  n: number;
  allPct: number | null;
  hiN: number;
  hiPct: number | null;
  warnN: number;
  warnPct: number | null;
  breaks: number;
};
type LiveBoard = {
  schemaVersion?: number;
  generatedAt: string;
  windowHours: number;
  theta: number;
  polls: number;
  lastPollTs: string;
  board: BoardRow[];
  feed: FeedItem[];
  timeseries?: PollStat[];
  regions?: RegionStat[];
  calibration: { bins: CalBin[] };
  headline: { valueChanges: number; bigBreaks: number; warnedBreaks: number; missedBreaks: number };
};

const REFRESH_MS = 5 * 60 * 1000; // hub 쪽 캐시가 20분이라 5분이면 충분히 신선
const REPLAY_SEC = 90;
const WARN_ROLL = 18; // 경고선은 폴링당 표본이 4건 안팎이라 6시간(18폴링) 이동평균으로 그린다

// 시리즈 색 — dataviz 검증을 통과한 카테고리 슬롯(이 파일 안에서만 쓰는 역할 고정 색).
const SERIES = {
  hi: { color: "#2a78d6", label: "엔진이 고른 값" },      // "믿어도 됨"(조건부 확률 80%↑)
  all: { color: "#8a8884", label: "전체 평균" },           // 선별 없이 전부 믿었을 때
  warn: { color: "#eb6834", label: "엔진이 경고한 값" },   // "위험"(50% 미만)
} as const;

const cardStyle = css({
  display: "flex", flexDirection: "column", gap: "4", padding: "5",
  borderWidth: "1px", borderColor: "line", borderRadius: "panel", backgroundColor: "surface",
  "& ::selection": { backgroundColor: "mintSoft" },
});
const smallStyle = css({ fontSize: "xs", color: "ink3", lineHeight: "1.5" });
const scrollStyle = css({
  overflowY: "auto",
  "&::-webkit-scrollbar": { width: "6px" },
  "&::-webkit-scrollbar-thumb": { backgroundColor: "line", borderRadius: "full" },
  "&::-webkit-scrollbar-track": { backgroundColor: "transparent" },
});

const kstTime = (iso: string | number) =>
  new Date(iso).toLocaleTimeString("ko-KR", { timeZone: "Asia/Seoul", hour: "2-digit", minute: "2-digit" });
const kstDayTime = (iso: string) =>
  new Date(iso).toLocaleString("ko-KR", { timeZone: "Asia/Seoul", weekday: "short", hour: "2-digit", minute: "2-digit" });

// hvec 음수는 과밀(만실 + 초과 n명, 2026-10-01 합의) — 날것(-17석)으로 보여주지 않는다.
const bedLabel = (v: number) => (v > 0 ? `${v}석` : v === 0 ? "만실" : `과밀 ${-v}명`);

function pColor(p: number): string {
  if (p >= 0.8) return "#1baf7a";
  if (p >= 0.5) return "var(--colors-ink2, #52514e)";
  return "#d03b3b";
}

// liveBedReliability(매칭 카드와 같은 감쇠 수식)를 보드 행에 그대로 적용한다.
function liveP(row: BoardRow, nowMs: number): number {
  const match: BedReliabilityMatch = {
    authority: row.authorityAtBuild, rArrive: row.authorityAtBuild, horizonSec: 0,
    ttlSec: row.ttlSec, modelTag: "live", source: "ai",
    predictedSurvivalSec: row.predictedSurvivalSec, bornAt: row.bornAt, sigma: row.sigma,
  };
  return liveBedReliability(match, nowMs).authority;
}

// ── 라이브 유지율 그래프 ─────────────────────────────────────────────────────
// 20분 폴링마다 점이 하나씩 붙는 선 3개: 엔진 선별(파랑) / 전체 평균(회색 점선) / 경고(주황).
// 경고선은 소표본이라 6시간 이동평균(범례에 명시). 리플레이 중에는 cutoff까지만 그린다.

type ChartPoint = { tMs: number; hi: number | null; all: number | null; warn: number | null; raw: PollStat };

function buildPoints(timeseries: PollStat[]): ChartPoint[] {
  return timeseries.map((poll, index) => {
    let warnHeld = 0;
    let warnN = 0;
    for (let back = Math.max(0, index - WARN_ROLL + 1); back <= index; back++) {
      warnHeld += timeseries[back].warnHeld;
      warnN += timeseries[back].warnN;
    }
    return {
      tMs: Date.parse(poll.ts),
      hi: poll.hiN >= 20 ? (poll.hiHeld / poll.hiN) * 100 : null,
      all: poll.n >= 20 ? (poll.held / poll.n) * 100 : null,
      warn: warnN >= 15 ? (warnHeld / warnN) * 100 : null,
      raw: poll,
    };
  });
}

function LiveChart({ points, cutoffMs, lastPollMs }: { points: ChartPoint[]; cutoffMs: number | null; lastPollMs: number }) {
  const [hover, setHover] = useState<number | null>(null);
  const W = 1000;
  const H = 240;
  const L = 44;
  const R = 150;
  const T = 14;
  const B = 28;
  const Y_MIN = 40;
  const visible = cutoffMs == null ? points : points.filter((p) => p.tMs <= cutoffMs);
  if (visible.length < 3) return null;
  const t0 = points[0].tMs;
  const t1 = points[points.length - 1].tMs;
  const x = (t: number) => L + ((W - L - R) * (t - t0)) / Math.max(t1 - t0, 1);
  const y = (v: number) => T + (H - T - B) * (1 - (Math.max(v, Y_MIN) - Y_MIN) / (100 - Y_MIN));
  const path = (key: "hi" | "all" | "warn") =>
    visible
      .filter((p) => p[key] != null)
      .map((p, i) => `${i === 0 ? "M" : "L"}${x(p.tMs).toFixed(1)},${y(p[key] as number).toFixed(1)}`)
      .join(" ");
  const lastOf = (key: "hi" | "all" | "warn") => [...visible].reverse().find((p) => p[key] != null);
  const hoverPoint = hover != null ? visible[Math.min(hover, visible.length - 1)] : null;

  const labelRows = (["hi", "all", "warn"] as const)
    .map((key) => ({ key, last: lastOf(key) }))
    .filter((row) => row.last)
    .map((row) => ({ ...row, yPos: y(row.last![row.key] as number) }))
    .sort((a, b) => a.yPos - b.yPos);
  // 선 끝 라벨이 겹치지 않게 위에서부터 16px 간격으로 밀어낸다
  for (let i = 1; i < labelRows.length; i++) {
    if (labelRows[i].yPos - labelRows[i - 1].yPos < 16) labelRows[i].yPos = labelRows[i - 1].yPos + 16;
  }

  return (
    <div className={css({ position: "relative" })}>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className={css({ width: "100%", height: "auto", display: "block" })}
        onMouseLeave={() => setHover(null)}
        onMouseMove={(e) => {
          const rect = e.currentTarget.getBoundingClientRect();
          const vx = ((e.clientX - rect.left) / rect.width) * W;
          const tAt = t0 + ((vx - L) / (W - L - R)) * (t1 - t0);
          let best = 0;
          let bestDist = Infinity;
          visible.forEach((p, i) => {
            const d = Math.abs(p.tMs - tAt);
            if (d < bestDist) { bestDist = d; best = i; }
          });
          setHover(best);
        }}
      >
        {[40, 60, 80, 100].map((v) => (
          <g key={v}>
            <line x1={L} y1={y(v)} x2={W - R} y2={y(v)} stroke="var(--colors-line)" strokeWidth="1" />
            <text x={L - 8} y={y(v) + 4} textAnchor="end" fontSize="11" fill="var(--colors-ink3)">{v}%</text>
          </g>
        ))}
        {visible.filter((_, i) => i % 18 === 0 && i > 0).map((p) => (
          <text key={p.tMs} x={x(p.tMs)} y={H - 8} textAnchor="middle" fontSize="11" fill="var(--colors-ink3)">
            {kstDayTime(p.raw.ts)}
          </text>
        ))}
        <path d={path("all")} fill="none" stroke={SERIES.all.color} strokeWidth="1.6" strokeDasharray="5 4" strokeLinejoin="round" />
        <path d={path("warn")} fill="none" stroke={SERIES.warn.color} strokeWidth="2" strokeLinejoin="round" />
        <path d={path("hi")} fill="none" stroke={SERIES.hi.color} strokeWidth="2" strokeLinejoin="round" />

        {/* 마지막 점 — 라이브임을 말하는 유일한 모션(파랑 선 끝의 맥박) */}
        {(() => {
          const last = lastOf("hi");
          if (!last || (cutoffMs != null && last.tMs < lastPollMs)) return null;
          const cx = x(last.tMs);
          const cy = y(last.hi as number);
          return (
            <g>
              <circle cx={cx} cy={cy} r="3.5" fill={SERIES.hi.color} />
              <circle cx={cx} cy={cy} r="3.5" fill="none" stroke={SERIES.hi.color} strokeWidth="1.5">
                <animate attributeName="r" values="3.5;11" dur="2.2s" repeatCount="indefinite" />
                <animate attributeName="opacity" values="0.7;0" dur="2.2s" repeatCount="indefinite" />
              </circle>
            </g>
          );
        })()}

        {labelRows.map(({ key, last, yPos }) => (
          <g key={key}>
            <circle cx={x(last!.tMs) + 10} cy={yPos - 3} r="3.5" fill={SERIES[key].color} />
            <text x={x(last!.tMs) + 18} y={yPos} fontSize="12" fontWeight="600" fill="var(--colors-ink)">
              {SERIES[key].label} {Math.round(last![key] as number)}%
            </text>
          </g>
        ))}

        {hoverPoint && (
          <line x1={x(hoverPoint.tMs)} y1={T} x2={x(hoverPoint.tMs)} y2={H - B} stroke="var(--colors-ink3)" strokeWidth="1" strokeDasharray="2 3" />
        )}
        <rect x={L} y={T} width={W - L - R} height={H - T - B} fill="transparent" />
      </svg>
      {hoverPoint && (
        <div
          className={css({
            position: "absolute", top: "0", pointerEvents: "none", backgroundColor: "surface",
            borderWidth: "1px", borderColor: "line", borderRadius: "field", paddingX: "3", paddingY: "2",
            fontSize: "xs", color: "ink2", boxShadow: "0 4px 14px rgba(0,0,0,0.12)", whiteSpace: "nowrap",
          })}
          style={{ left: `${Math.min((x(hoverPoint.tMs) / W) * 100, 72)}%` }}
        >
          <b className={css({ color: "ink" })}>{kstDayTime(hoverPoint.raw.ts)} 채점</b>
          <br />전체 {hoverPoint.raw.n}건 중 {hoverPoint.raw.held} 유지
          {hoverPoint.hi != null && <> · 엔진 선별 {hoverPoint.raw.hiN}건 중 {hoverPoint.raw.hiHeld}</>}
          {hoverPoint.warn != null && <> · 경고(6h 평균) {Math.round(hoverPoint.warn)}%</>}
        </div>
      )}
    </div>
  );
}

// ── 지역별 격차 — "평균의 오류" 분해 ─────────────────────────────────────────
// 시도마다 회색 점(E-Gen 원값 유지율)과 파란 점(엔진 선별 유지율)을 한 트랙에 찍는다.
// 두 점을 잇는 띠의 길이 = 엔진이 그 지역에서 끌어올린 폭. 원값이 나쁜 지역(수도권 등)
// 일수록 띠가 길다 — 전국 평균 하나로는 보이지 않는 사실.

function RegionGaps({ regions, windowHours }: { regions: RegionStat[]; windowHours: number }) {
  const rows = regions.filter((r) => r.label !== "기타" && r.allPct != null && r.hiPct != null);
  if (rows.length < 4) return null;
  const minPct = Math.floor(Math.min(...rows.map((r) => r.allPct as number))) - 1;
  const pos = (v: number) => `${((v - minPct) / (100 - minPct)) * 100}%`;
  const days = Math.max(windowHours / 24, 1);
  return (
    <div className={css({ display: "flex", flexDirection: "column", gap: "2", borderTopWidth: "1px", borderColor: "line", paddingTop: "4" })}>
      <h3 className={css({ fontSize: "sm", fontWeight: "semibold", color: "ink" })}>
        지역별로 갈라 보면 <span className={css({ fontSize: "xs", fontWeight: "normal", color: "ink3" })}>전국 평균이 가리는 격차 — 원값 품질이 나쁜 지역일수록 엔진의 이득이 큽니다</span>
      </h3>
      <div className={css({ display: "grid", gridTemplateColumns: { base: "1fr", md: "1fr 1fr" }, columnGap: "8", rowGap: "1" })}>
        {rows.map((region) => {
          const all = region.allPct as number;
          const hi = region.hiPct as number;
          return (
            <div key={region.label} className={css({ display: "flex", alignItems: "center", gap: "2", fontSize: "xs" })}>
              <span className={css({ width: "34px", flexShrink: "0", fontWeight: "semibold", color: "ink" })}>{region.label}</span>
              <div className={css({ position: "relative", flex: "1", height: "16px", minWidth: "0" })}>
                <div className={css({ position: "absolute", top: "50%", left: "0", right: "0", height: "1px", backgroundColor: "line" })} />
                <div
                  className={css({ position: "absolute", top: "50%", height: "4px", transform: "translateY(-50%)", borderRadius: "full" })}
                  style={{ left: pos(all), width: `calc(${pos(hi)} - ${pos(all)})`, backgroundColor: "rgba(42,120,214,0.25)" }}
                />
                <span className={css({ position: "absolute", top: "50%", width: "7px", height: "7px", borderRadius: "full", transform: "translate(-50%, -50%)" })} style={{ left: pos(all), backgroundColor: SERIES.all.color }} />
                <span className={css({ position: "absolute", top: "50%", width: "7px", height: "7px", borderRadius: "full", transform: "translate(-50%, -50%)" })} style={{ left: pos(hi), backgroundColor: SERIES.hi.color }} />
              </div>
              <span className={css({ flexShrink: "0", color: "ink2", fontVariantNumeric: "tabular-nums", width: "92px", textAlign: "right" })}>
                {all.toFixed(1)} → <b className={css({ color: "ink" })}>{hi.toFixed(1)}%</b>
              </span>
              <span className={css({ flexShrink: "0", color: "ink3", fontVariantNumeric: "tabular-nums", width: "72px", textAlign: "right" })}>
                거짓 {Math.round(region.breaks / days).toLocaleString()}/일
              </span>
            </div>
          );
        })}
      </div>
      <p className={smallStyle}>
        <span className={css({ display: "inline-block", width: "7px", height: "7px", borderRadius: "full", marginRight: "1" })} style={{ backgroundColor: SERIES.all.color }} /> E-Gen 원값(선별 없음)
        <span className={css({ display: "inline-block", width: "7px", height: "7px", borderRadius: "full", marginLeft: "3", marginRight: "1" })} style={{ backgroundColor: SERIES.hi.color }} /> 엔진이 고른 값 ·
        20분당 유지율(48시간 집계), 표본 적은 지역 제외 · 서울·경기가 원값 하위권인 건 수도권 응급실의 회전 속도 때문입니다
      </p>
    </div>
  );
}

// ── 본체 ────────────────────────────────────────────────────────────────────

function FeedRow({ item }: { item: FeedItem }) {
  const warned = item.pValid < 0.5;
  const missed = item.pValid >= 0.8;
  return (
    <div className={css({ display: "flex", alignItems: "center", gap: "2", paddingY: "1.5", borderBottomWidth: "1px", borderColor: "line", _last: { borderBottomWidth: "0" }, fontSize: "sm", _hover: { backgroundColor: "bg" } })}>
      <span className={css({ color: "ink3", fontVariantNumeric: "tabular-nums", flexShrink: "0" })}>{kstTime(item.ts)}</span>
      <span className={css({ fontWeight: "semibold", color: "ink", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", minWidth: "0", flex: "1" })}>
        {item.name}
      </span>
      <span className={css({ fontVariantNumeric: "tabular-nums", flexShrink: "0", color: "ink2" })}>
        {bedLabel(item.claimValue)} → {bedLabel(item.newValue)}
      </span>
      <span className={css({ fontSize: "xs", color: "ink3", flexShrink: "0", fontVariantNumeric: "tabular-nums" })}>{Math.round(item.ageMin)}분 묵음</span>
      <span
        className={css({ fontSize: "xs", fontWeight: "semibold", paddingX: "1.5", paddingY: "0.5", borderRadius: "chip", flexShrink: "0", fontVariantNumeric: "tabular-nums" })}
        style={{
          color: warned ? "#157f58" : missed ? "#b32f2f" : "var(--colors-ink2, #52514e)",
          backgroundColor: warned ? "rgba(27,175,122,0.14)" : missed ? "rgba(208,59,59,0.12)" : "rgba(128,128,128,0.10)",
        }}
      >
        직전 신뢰도 {Math.round(item.pValid * 100)}%{warned ? " · 미리 경고했음" : missed ? " · 못 맞힘" : ""}
      </span>
    </div>
  );
}

export function LiveBoardSection() {
  const [data, setData] = useState<LiveBoard | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [nowMs, setNowMs] = useState(() => Date.now());
  const [replayPos, setReplayPos] = useState<number | null>(null);
  const replayTimer = useRef<ReturnType<typeof setInterval> | null>(null);

  const load = useCallback(async () => {
    const httpUrl = process.env.NEXT_PUBLIC_HUB_HTTP_URL;
    if (!httpUrl) {
      setError("hub 주소가 없어 라이브 보드를 숨깁니다(목데이터 모드)");
      return;
    }
    try {
      const response = await fetch(`${httpUrl}/verification/live`);
      const body = await response.json();
      if (!response.ok) throw new Error(body.error ?? `HTTP ${response.status}`);
      setData(body as LiveBoard);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "라이브 보드를 불러오지 못했습니다");
    }
  }, []);

  useEffect(() => {
    const kick = setTimeout(() => void load(), 0); // effect 안 동기 setState lint 회피
    const refresh = setInterval(() => void load(), REFRESH_MS);
    const tick = setInterval(() => setNowMs(Date.now()), 1000);
    return () => {
      clearTimeout(kick);
      clearInterval(refresh);
      clearInterval(tick);
      if (replayTimer.current) clearInterval(replayTimer.current);
    };
  }, [load]);

  const points = useMemo(() => (data?.timeseries ? buildPoints(data.timeseries) : []), [data]);

  const stopReplay = () => {
    if (replayTimer.current) clearInterval(replayTimer.current);
    replayTimer.current = null;
    setReplayPos(null);
  };
  const startReplay = () => {
    if (replayTimer.current) clearInterval(replayTimer.current);
    setReplayPos(0);
    const startedAt = Date.now();
    replayTimer.current = setInterval(() => {
      const pos = (Date.now() - startedAt) / (REPLAY_SEC * 1000);
      if (pos >= 1) {
        setReplayPos(1);
        if (replayTimer.current) clearInterval(replayTimer.current);
        replayTimer.current = null;
      } else {
        setReplayPos(pos);
      }
    }, 100);
  };

  if (error) return <p className={smallStyle}>라이브 채점 보드: {error}</p>;
  if (!data) return <p className={smallStyle}>라이브 채점 보드 불러오는 중… (첫 생성은 수십 초)</p>;

  // 창 전체 집계 — 헤드라인 문장의 숫자들
  const sum = (key: keyof PollStat) => (data.timeseries ?? []).reduce((acc, poll) => acc + (poll[key] as number), 0);
  const allN = sum("n");
  const allPct = allN ? Math.round((sum("held") / allN) * 100) : null;
  const hiN = sum("hiN");
  const hiPct = hiN ? Math.round((sum("hiHeld") / hiN) * 1000) / 10 : null;
  const warnN = sum("warnN");
  const warnPct = warnN ? Math.round((sum("warnHeld") / warnN) * 100) : null;
  const h = data.headline;

  const lastMs = Date.parse(data.lastPollTs);
  const windowStartMs = lastMs - 24 * 3600 * 1000;
  const replayFeed = [...data.feed].reverse().filter((f) => Date.parse(f.ts) >= windowStartMs);
  const replaying = replayPos != null;
  const cutoffMs = replaying ? windowStartMs + (lastMs - windowStartMs) * (replayPos as number) : null;
  const replayShown = replaying ? replayFeed.filter((f) => Date.parse(f.ts) <= (cutoffMs as number)) : [];
  const replayWarned = replayShown.filter((f) => f.pValid < 0.5).length;
  const feedToShow = replaying ? replayShown.slice(-9).reverse() : data.feed.slice(0, 9);

  const dot = (color: string) => (
    <span className={css({ display: "inline-block", width: "9px", height: "9px", borderRadius: "full", marginRight: "1", verticalAlign: "baseline" })} style={{ backgroundColor: color }} />
  );

  return (
    <section className={cardStyle}>
      <div className={css({ display: "flex", alignItems: "baseline", gap: "3", flexWrap: "wrap" })}>
        <h2 className={css({ fontSize: "lg", fontWeight: "bold", color: "ink", letterSpacing: "-0.01em" })}>
          같은 48시간, 믿는 방법만 바꿨을 때
        </h2>
        <span className={css({ display: "inline-flex", alignItems: "center", gap: "1.5", fontSize: "xs", fontWeight: "semibold", color: "mint", backgroundColor: "mintSoft", paddingX: "2", paddingY: "0.5", borderRadius: "chip" })}>
          <span className={css({ width: "7px", height: "7px", borderRadius: "full", backgroundColor: "mint" })} />
          라이브 · 20분마다 실측 채점
        </span>
        <span className={css({ fontSize: "xs", color: "ink3", marginLeft: "auto" })}>
          마지막 폴링 {kstTime(data.lastPollTs)} · 폴링 {data.polls}회 · 실제 서빙 엔진 재생(시뮬 아님)
        </span>
      </div>

      <p className={css({ fontSize: "md", color: "ink2", lineHeight: "1.7", maxWidth: "72ch" })}>
        E-Gen 병상 숫자를 <b className={css({ color: "ink" })}>선별 없이 그냥 믿으면</b> 다음 실측에서 {dot(SERIES.all.color)}
        <b className={css({ color: "ink" })}>{allPct}%</b>만 유효했습니다. 같은 숫자들을{" "}
        <b className={css({ color: "ink" })}>엔진이 &quot;믿어도 됨&quot;이라 고른 것만 믿으면</b> {dot(SERIES.hi.color)}
        <b className={css({ color: "ink" })}>{hiPct}%</b>, 반대로 <b className={css({ color: "ink" })}>엔진이 &quot;위험&quot; 경고한 값</b>은 {dot(SERIES.warn.color)}
        <b className={css({ color: "ink" })}>{warnPct}%</b>만 살아남았습니다 — 경고가 진짜 지뢰를 가리킨다는 뜻입니다.
      </p>

      {points.length >= 3 && <LiveChart points={points} cutoffMs={cutoffMs} lastPollMs={lastMs} />}

      <p className={smallStyle}>
        {allPct}%가 높아 보여도 <b>20분당</b> 유지율입니다 — 나머지 {100 - (allPct ?? 0)}%는 전국 기준{" "}
        <b>하루 약 {Math.round(h.bigBreaks / (data.windowHours / 24)).toLocaleString()}건의 &quot;{data.theta}석 이상 거짓&quot;</b>이고,
        값이 조금이라도 바뀌는 건 관측당 절반이 넘습니다. 문제는 그 거짓이 어디서 날지 E-Gen 스스로는 모른다는 것 — 엔진이 그걸 분리합니다 ·
        문장의 숫자는 48시간 집계, 선 끝 숫자는 가장 최근 폴링 기준 · 경고선은 폴링당 표본이 적어 6시간 이동평균 ·
        신뢰도 구간별 실제 유지율 {data.calibration.bins.map((bin) => (bin.actualPct == null ? "—" : Math.round(bin.actualPct))).join(" → ")}%로
        단조 · 크게 어긋난 {h.bigBreaks.toLocaleString()}건 중 {h.warnedBreaks.toLocaleString()}건은 깨지기 전에 이미 경고 상태였습니다
      </p>

      {data.regions && <RegionGaps regions={data.regions} windowHours={data.windowHours} />}

      <div className={css({ display: "grid", gridTemplateColumns: { base: "1fr", lg: "5fr 7fr" }, gap: "5", borderTopWidth: "1px", borderColor: "line", paddingTop: "4" })}>
        {/* 지금 가장 못 믿을 값 — 초 단위 감쇠 */}
        <div className={css({ display: "flex", flexDirection: "column", gap: "1", minWidth: "0" })}>
          <h3 className={css({ fontSize: "sm", fontWeight: "semibold", color: "ink" })}>
            지금 가장 못 믿을 값 <span className={css({ fontSize: "xs", fontWeight: "normal", color: "ink3" })}>확률이 초 단위로 떨어지는 실시간 값</span>
          </h3>
          {data.board.slice(0, 10).map((row) => {
            const p = liveP(row, nowMs);
            const ageMin = Math.max((nowMs - Date.parse(row.bornAt)) / 60000, 0);
            return (
              <div key={row.hpid} className={css({ display: "flex", alignItems: "center", gap: "2", fontSize: "sm", paddingY: "1", borderBottomWidth: "1px", borderColor: "line", _last: { borderBottomWidth: "0" }, _hover: { backgroundColor: "bg" } })}>
                <span className={css({ fontWeight: "semibold", color: "ink", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", minWidth: "0", flex: "1" })}>
                  {row.name}
                </span>
                <span className={css({ color: "ink2", flexShrink: "0", fontVariantNumeric: "tabular-nums" })}>{bedLabel(row.value)}</span>
                <span className={css({ fontSize: "xs", color: "ink3", flexShrink: "0", fontVariantNumeric: "tabular-nums" })}>{Math.round(ageMin).toLocaleString()}분 전 값</span>
                <span className={css({ fontWeight: "bold", flexShrink: "0", fontVariantNumeric: "tabular-nums", minWidth: "44px", textAlign: "right" })} style={{ color: pColor(p) }}>
                  {Math.round(p * 100)}%
                </span>
              </div>
            );
          })}
        </div>

        {/* 채점 기록 / 리플레이 */}
        <div className={css({ display: "flex", flexDirection: "column", gap: "2", minWidth: "0" })}>
          <div className={css({ display: "flex", alignItems: "center", gap: "2", flexWrap: "wrap" })}>
            <h3 className={css({ fontSize: "sm", fontWeight: "semibold", color: "ink" })}>
              {replaying ? "리플레이 — 지난 24시간을 90초로" : "채점 기록 — E-Gen 값이 거짓으로 판명된 순간들"}
            </h3>
            <button
              type="button"
              onClick={replaying ? stopReplay : startReplay}
              className={css({ fontSize: "xs", fontWeight: "semibold", color: "ink2", backgroundColor: "surface", borderWidth: "1px", borderColor: "line", paddingX: "2.5", paddingY: "1", borderRadius: "chip", cursor: "pointer", _hover: { borderColor: "ink3", color: "ink" } })}
            >
              {replaying ? "리플레이 종료" : "지난 24시간 90초 재생"}
            </button>
            {replaying && cutoffMs != null && (
              <span className={css({ fontSize: "sm", fontWeight: "bold", color: "ink", fontVariantNumeric: "tabular-nums" })}>
                {kstTime(cutoffMs)} — 어긋남 {replayShown.length}건, 미리 경고한 것 {replayWarned}건
              </span>
            )}
          </div>
          {!replaying && (
            <p className={smallStyle}>
              20분마다 새 실측이 도착해 기존 값을 채점합니다. 한 줄 = 신고값이 {data.theta}석 이상 어긋난 순간이고,
              오른쪽 %는 깨지기 <b>직전</b>까지 엔진이 그 값에 매겨둔 신뢰도 — 50% 미만이면 엔진이 미리 경고하고 있었다는 뜻입니다.
            </p>
          )}
          {replaying && (
            <div className={css({ height: "4px", backgroundColor: "line", borderRadius: "full", overflow: "hidden" })}>
              <div
                className={css({ height: "100%", width: "100%", backgroundColor: "mint", transformOrigin: "left", transition: "transform 0.1s linear" })}
                style={{ transform: `scaleX(${replayPos as number})` }}
              />
            </div>
          )}
          <div className={scrollStyle} style={{ maxHeight: 332 }}>
            {feedToShow.map((item) => (
              <FeedRow key={`${item.ts}-${item.hpid}`} item={item} />
            ))}
          </div>
        </div>
      </div>

      <p className={smallStyle}>
        채점 대상은 &quot;신고값이 유효한가&quot;({data.theta}석 기준)이지 실제 수용 여부가 아닙니다 · 리플레이는 실데이터 고속 재생(연출 아님) ·
        확률은 AI(XGBoost AFT 생존모델) 산출, 채점 규칙은 규칙 기반
      </p>
    </section>
  );
}
