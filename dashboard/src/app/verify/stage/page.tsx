"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { css } from "styled-system/css";
import {
  type LiveBoard,
  SERIES,
  LiveChart,
  ageLabel,
  bedLabel,
  buildPoints,
  liveP,
} from "@/components/verify/LiveBoardSection";

// 스테이지 모드(2026-10-03) — 부스 대형 화면용 자동 순환 슬라이드. /verify와 같은
// 라이브 데이터(hub GET /verification/live)를 발표 서사 6장으로 돌린다.
// 다크는 취향이 아니라 사용 장면의 선택이다: 전시장 대형 화면, 몇 미터 밖의 관객,
// 밝은 홀 조명 — 어두운 바탕 위의 큰 숫자가 유일하게 멀리서 읽힌다.
// 조작: ←/→ 슬라이드 이동, 스페이스 일시정지, 클릭 다음 장. 85초에 한 바퀴.

const SLIDE_SEC = [9, 12, 16, 14, 24, 12]; // 슬라이드별 체류 시간(초)

// panda 토큰(CSS 변수)을 이 페이지 범위에서만 다크로 덮는다 — LiveChart가 쓰는
// var(--colors-*)가 그대로 다크 값을 받아, 차트 코드를 복제하지 않는다.
const DARK_VARS: Record<string, string> = {
  "--colors-bg": "#0d0d0d",
  "--colors-surface": "#17171a",
  "--colors-ink": "#f4f4f0",
  "--colors-ink2": "#c3c2b7",
  "--colors-ink3": "#8a8984",
  "--colors-line": "#2c2c2e",
  "--colors-mint": "#1baf7a",
  "--colors-mint-soft": "rgba(27,175,122,0.16)",
  "--colors-coral": "#e66767",
};

const stageStyle = css({
  position: "fixed", inset: "0", overflow: "hidden",
  backgroundColor: "#0d0d0d", color: "#f4f4f0",
  fontFamily: "inherit",
  "& ::selection": { backgroundColor: "rgba(27,175,122,0.3)" },
});
const slideBase = css({
  position: "absolute", inset: "0", display: "flex", flexDirection: "column",
  justifyContent: "center", paddingX: "clamp(32px, 7vw, 120px)", gap: "clamp(12px, 2.4vh, 28px)",
  transition: "opacity 0.65s cubic-bezier(0.16, 1, 0.3, 1), transform 0.65s cubic-bezier(0.16, 1, 0.3, 1)",
});
const eyebrowless = css({ fontSize: "clamp(20px, 2.4vw, 34px)", fontWeight: "semibold", color: "#c3c2b7", lineHeight: "1.5" });
const bigStyle = css({ fontSize: "clamp(40px, 5.2vw, 84px)", fontWeight: "bold", letterSpacing: "-0.03em", lineHeight: "1.2", color: "#f4f4f0" });
const noteStyle = css({ fontSize: "clamp(13px, 1.1vw, 17px)", color: "#8a8984", lineHeight: "1.6" });

const kstTime = (iso: string | number) =>
  new Date(iso).toLocaleTimeString("ko-KR", { timeZone: "Asia/Seoul", hour: "2-digit", minute: "2-digit" });

function usePerSecond(): number {
  const [nowMs, setNowMs] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setNowMs(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);
  return nowMs;
}

export default function StagePage() {
  const [data, setData] = useState<LiveBoard | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [slide, setSlide] = useState(0);
  const [paused, setPaused] = useState(false);
  const nowMs = usePerSecond();
  // 렌더 중 Date.now()/ref 접근을 피하려고 state로 둔다(마운트 효과에서 초기화)
  const [slideStartMs, setSlideStartMs] = useState<number | null>(null);

  const load = useCallback(async () => {
    const httpUrl = process.env.NEXT_PUBLIC_HUB_HTTP_URL;
    if (!httpUrl) {
      setError("hub 주소가 없습니다 (NEXT_PUBLIC_HUB_HTTP_URL)");
      return;
    }
    try {
      const response = await fetch(`${httpUrl}/verification/live`);
      const body = await response.json();
      if (!response.ok) throw new Error(body.error ?? `HTTP ${response.status}`);
      setData(body as LiveBoard);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "라이브 데이터를 불러오지 못했습니다");
    }
  }, []);

  useEffect(() => {
    const kick = setTimeout(() => void load(), 0);
    const refresh = setInterval(() => void load(), 5 * 60 * 1000);
    return () => { clearTimeout(kick); clearInterval(refresh); };
  }, [load]);

  const go = useCallback((dir: number) => {
    setSlide((s) => (s + dir + SLIDE_SEC.length) % SLIDE_SEC.length);
    setSlideStartMs(Date.now());
  }, []);

  // 자동 진행 + 키보드
  useEffect(() => {
    const init = slideStartMs == null ? setTimeout(() => setSlideStartMs(Date.now()), 0) : null;
    const timer = setInterval(() => {
      if (!paused && slideStartMs != null && Date.now() - slideStartMs > SLIDE_SEC[slide] * 1000) go(1);
    }, 250);
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "ArrowRight") go(1);
      else if (e.key === "ArrowLeft") go(-1);
      else if (e.key === " ") { e.preventDefault(); setPaused((p) => !p); }
    };
    window.addEventListener("keydown", onKey);
    return () => { if (init) clearTimeout(init); clearInterval(timer); window.removeEventListener("keydown", onKey); };
  }, [slide, paused, go, slideStartMs]);

  const points = useMemo(() => (data?.timeseries ? buildPoints(data.timeseries) : []), [data]);

  // 창 전체 집계
  const agg = useMemo(() => {
    const ts = data?.timeseries ?? [];
    const sum = (k: "n" | "held" | "hiN" | "hiHeld" | "warnN" | "warnHeld") => ts.reduce((a, p) => a + p[k], 0);
    return {
      allPct: sum("n") ? Math.round((sum("held") / sum("n")) * 100) : 0,
      hiPct: sum("hiN") ? Math.round((sum("hiHeld") / sum("hiN")) * 1000) / 10 : 0,
      warnPct: sum("warnN") ? Math.round((sum("warnHeld") / sum("warnN")) * 100) : 0,
    };
  }, [data]);

  // 슬라이드 5(리플레이): 슬라이드에 머무는 동안 지난 24시간을 20초에 재생하고 반복
  const replay = useMemo(() => {
    if (!data || slide !== 4) return null;
    const lastMs = Date.parse(data.lastPollTs);
    const startMs = lastMs - 24 * 3600 * 1000;
    const loopSec = 20;
    const pos = ((nowMs - (slideStartMs ?? nowMs)) / 1000 % loopSec) / loopSec;
    const cutoff = startMs + (lastMs - startMs) * pos;
    const events = [...data.feed].reverse().filter((f) => {
      const t = Date.parse(f.ts);
      return t >= startMs && t <= cutoff;
    });
    return { cutoff, events, warned: events.filter((f) => f.pValid < 0.5).length };
  }, [data, slide, nowMs, slideStartMs]);

  if (error) {
    return <main className={stageStyle} style={DARK_VARS as React.CSSProperties}><p className={css({ margin: "auto", color: "#c3c2b7" })}>{error}</p></main>;
  }
  if (!data) {
    return <main className={stageStyle} style={DARK_VARS as React.CSSProperties}><p className={css({ margin: "auto", color: "#c3c2b7" })}>라이브 데이터 불러오는 중…</p></main>;
  }

  const h = data.headline;
  const perDay = Math.round(h.bigBreaks / (data.windowHours / 24));
  const regions = (data.regions ?? []).filter((r) => r.label !== "기타" && r.allPct != null && r.hiPct != null).slice(0, 8);
  const minRegion = regions.length ? Math.floor(Math.min(...regions.map((r) => r.allPct as number))) - 1 : 88;
  const pos = (v: number) => `${((v - minRegion) / (100 - minRegion)) * 100}%`;
  const surging = (data.regime?.current.level ?? 0) >= 1;

  const slideProps = (index: number) => ({
    className: slideBase,
    style: {
      opacity: slide === index ? 1 : 0,
      transform: slide === index ? "translateY(0)" : "translateY(26px)",
      pointerEvents: slide === index ? ("auto" as const) : ("none" as const),
    },
  });

  return (
    <main className={stageStyle} style={DARK_VARS as React.CSSProperties} onClick={() => go(1)}>
      {/* 상단 상태줄 — 모든 슬라이드 공통 */}
      <div className={css({ position: "absolute", top: "0", left: "0", right: "0", display: "flex", alignItems: "center", gap: "14px", paddingX: "clamp(32px, 7vw, 120px)", paddingY: "18px", fontSize: "clamp(12px, 1vw, 15px)", color: "#8a8984", zIndex: "10" })}>
        <span className={css({ display: "inline-flex", alignItems: "center", gap: "7px", color: "#1baf7a", fontWeight: "semibold" })}>
          <span className={css({ width: "8px", height: "8px", borderRadius: "full", backgroundColor: "#1baf7a", animation: "pulse 2.2s ease-out infinite" })} />
          라이브 — 실제 E-Gen 기록, 20분마다 채점
        </span>
        <span>마지막 폴링 {kstTime(data.lastPollTs)}</span>
        {surging && <span className={css({ color: "#e66767", fontWeight: "semibold" })}>전국 변동 {data.regime!.current.level >= 2 ? "급증" : "주의"} · 평시의 {data.regime!.current.ratio}배</span>}
        <span className={css({ marginLeft: "auto" })}>{paused ? "일시정지 (스페이스)" : "←→ 이동 · 스페이스 정지"}</span>
      </div>
      <style>{`@keyframes pulse { 0% { box-shadow: 0 0 0 0 rgba(27,175,122,0.6); } 100% { box-shadow: 0 0 0 14px rgba(27,175,122,0); } }`}</style>

      {/* 1 — 훅 */}
      <section {...slideProps(0)}>
        <p className={eyebrowless}>응급실 병상 숫자는 국가 API(E-Gen)가 알려줍니다. 그런데 —</p>
        <h1 className={bigStyle}>
          그 숫자, 하루 <span className={css({ color: "#e66767" })}>{perDay.toLocaleString()}번</span> 크게 어긋납니다.
        </h1>
        <p className={eyebrowless}>지난 {data.windowHours}시간, 전국 병원 실측 {h.valueChanges.toLocaleString()}번의 값 변화로 직접 센 숫자입니다.</p>
      </section>

      {/* 2 — 세 숫자 비교 */}
      <section {...slideProps(1)}>
        <h1 className={css({ fontSize: "clamp(26px, 2.8vw, 44px)", fontWeight: "bold", letterSpacing: "-0.02em" })}>같은 숫자, 믿는 방법만 바꿨습니다</h1>
        <div className={css({ display: "flex", gap: "clamp(28px, 5vw, 90px)", flexWrap: "wrap", alignItems: "flex-end" })}>
          {[
            { label: "모든 신고값을 그대로 믿으면", pct: `${agg.allPct}%`, color: SERIES.all.color },
            { label: "엔진이 “믿어도 됨”으로 고른 값만 믿으면", pct: `${agg.hiPct}%`, color: "#3987e5" },
            { label: "엔진이 “위험”으로 경고한 값은", pct: `${agg.warnPct}%`, color: "#d95926" },
          ].map((item, i) => (
            <div key={item.label} className={css({ display: "flex", flexDirection: "column", gap: "6px", transition: "opacity 0.5s ease-out", transitionDelay: `${i * 0.45}s` })}
              style={{ opacity: slide === 1 ? 1 : 0 }}>
              <span className={css({ fontSize: "clamp(14px, 1.3vw, 20px)", color: "#c3c2b7", maxWidth: "30ch" })}>{item.label}</span>
              <span className={css({ fontSize: "clamp(56px, 7vw, 96px)", fontWeight: "bold", letterSpacing: "-0.035em", lineHeight: "1", fontVariantNumeric: "tabular-nums" })} style={{ color: item.color }}>
                {item.pct}
              </span>
            </div>
          ))}
        </div>
        <p className={noteStyle}>유지율 = 다음 실측(20분 뒤)에서 3석 이상 어긋나지 않은 비율 · 48시간 전수 채점 · 경고는 장식이 아닙니다</p>
      </section>

      {/* 3 — 라이브 차트 */}
      <section {...slideProps(2)}>
        <h1 className={css({ fontSize: "clamp(26px, 2.8vw, 44px)", fontWeight: "bold", letterSpacing: "-0.02em" })}>
          20분마다 점이 하나씩 — <span className={css({ color: "#3987e5" })}>엔진이 고른 값</span>은 늘 위에 있습니다
        </h1>
        {points.length >= 3 && (
          <div className={css({ "& text": { fontSize: "13px" } })}>
            <LiveChart points={points} cutoffMs={null} lastPollMs={Date.parse(data.lastPollTs)} />
          </div>
        )}
        <p className={noteStyle}>붉은 띠 = 전국이 동시에 움직인 공통충격(평시 3배 이상) — 개별 예측이 아니라 감지 대상이라 시스템이 스스로 표시합니다</p>
      </section>

      {/* 4 — 지역 격차 */}
      <section {...slideProps(3)}>
        <h1 className={css({ fontSize: "clamp(26px, 2.8vw, 44px)", fontWeight: "bold", letterSpacing: "-0.02em" })}>
          신고값 품질은 지역 복불복 — 엔진을 거치면 <span className={css({ color: "#3987e5" })}>어디서나 96% 이상</span>
        </h1>
        <div className={css({ display: "flex", flexDirection: "column", gap: "clamp(8px, 1.4vh, 16px)", maxWidth: "1100px" })}>
          {regions.map((region, i) => (
            <div key={region.label} className={css({ display: "flex", alignItems: "center", gap: "18px", fontSize: "clamp(14px, 1.3vw, 20px)", transition: "opacity 0.4s ease-out" })}
              style={{ opacity: slide === 3 ? 1 : 0, transitionDelay: `${i * 0.12}s` }}>
              <span className={css({ width: "54px", fontWeight: "semibold", flexShrink: "0" })}>{region.label}</span>
              <div className={css({ position: "relative", flex: "1", height: "22px" })}>
                <div className={css({ position: "absolute", top: "50%", left: "0", right: "0", height: "1px", backgroundColor: "#2c2c2e" })} />
                <div className={css({ position: "absolute", top: "50%", height: "6px", transform: "translateY(-50%)", borderRadius: "full", backgroundColor: "rgba(57,135,229,0.3)" })}
                  style={{ left: pos(region.allPct as number), width: `calc(${pos(region.hiPct as number)} - ${pos(region.allPct as number)})` }} />
                <span className={css({ position: "absolute", top: "50%", width: "11px", height: "11px", borderRadius: "full", transform: "translate(-50%,-50%)", backgroundColor: "#8a8984" })} style={{ left: pos(region.allPct as number) }} />
                <span className={css({ position: "absolute", top: "50%", width: "11px", height: "11px", borderRadius: "full", transform: "translate(-50%,-50%)", backgroundColor: "#3987e5" })} style={{ left: pos(region.hiPct as number) }} />
              </div>
              <span className={css({ flexShrink: "0", fontVariantNumeric: "tabular-nums", color: "#c3c2b7", width: "150px", textAlign: "right" })}>
                {region.allPct} → <b className={css({ color: "#f4f4f0" })}>{region.hiPct}%</b>
              </span>
            </div>
          ))}
        </div>
        <p className={noteStyle}>회색 = 모든 신고값 · 파랑 = 엔진이 고른 값 · 띠 길이 = 엔진이 끌어올린 폭 — 원값이 나쁜 지역일수록 이득이 큽니다</p>
      </section>

      {/* 5 — 24시간 자동 리플레이 */}
      <section {...slideProps(4)}>
        <h1 className={css({ fontSize: "clamp(26px, 2.8vw, 44px)", fontWeight: "bold", letterSpacing: "-0.02em" })}>
          지난 24시간을 20초로 — {replay ? kstTime(replay.cutoff) : ""}
          {replay && (
            <span className={css({ marginLeft: "22px", fontSize: "clamp(18px, 1.8vw, 28px)", color: "#c3c2b7", fontVariantNumeric: "tabular-nums" })}>
              어긋남 {replay.events.length.toLocaleString()}건 · <span className={css({ color: "#1baf7a" })}>사전 경고 {replay.warned.toLocaleString()}건</span>
            </span>
          )}
        </h1>
        <div className={css({ display: "flex", flexDirection: "column", gap: "clamp(6px, 1vh, 12px)", fontSize: "clamp(15px, 1.4vw, 22px)" })}>
          {(replay?.events.slice(-7).reverse() ?? []).map((f) => (
            <div key={`${f.ts}-${f.hpid}`} className={css({ display: "flex", alignItems: "baseline", gap: "16px" })}>
              <span className={css({ color: "#8a8984", fontVariantNumeric: "tabular-nums", flexShrink: "0" })}>{kstTime(f.ts)}</span>
              <span className={css({ fontWeight: "semibold", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" })}>{f.name}</span>
              <span className={css({ color: "#c3c2b7", fontVariantNumeric: "tabular-nums", flexShrink: "0" })}>{bedLabel(f.claimValue)} → {bedLabel(f.newValue)}</span>
              <span className={css({ flexShrink: "0", fontVariantNumeric: "tabular-nums" })} style={{ color: f.pValid < 0.5 ? "#1baf7a" : f.pValid >= 0.8 ? "#e66767" : "#8a8984" }}>
                직전 신뢰도 {Math.round(f.pValid * 100)}%{f.pValid < 0.5 ? " · 사전 경고" : ""}
              </span>
            </div>
          ))}
        </div>
        <p className={noteStyle}>실데이터 재생입니다(연출 아님) — 신고값이 3석 이상 어긋난 순간과, 어긋나기 직전 엔진이 매긴 신뢰도</p>
      </section>

      {/* 6 — 지금 가장 의심스러운 신고값 */}
      <section {...slideProps(5)}>
        <h1 className={css({ fontSize: "clamp(26px, 2.8vw, 44px)", fontWeight: "bold", letterSpacing: "-0.02em" })}>지금 이 순간, 가장 의심스러운 신고값</h1>
        <div className={css({ display: "flex", flexDirection: "column", gap: "clamp(10px, 1.6vh, 18px)" })}>
          {data.board.slice(0, 5).map((row) => {
            const p = liveP(row, nowMs);
            return (
              <div key={row.hpid} className={css({ display: "flex", alignItems: "baseline", gap: "20px", fontSize: "clamp(17px, 1.7vw, 26px)" })}>
                <span className={css({ fontWeight: "semibold", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", minWidth: "0", flex: "1" })}>{row.name}</span>
                <span className={css({ color: "#c3c2b7", flexShrink: "0" })}>{bedLabel(row.value)} · {ageLabel(Math.max((nowMs - Date.parse(row.bornAt)) / 60000, 0))}</span>
                <span className={css({ fontWeight: "bold", fontVariantNumeric: "tabular-nums", flexShrink: "0", width: "120px", textAlign: "right", fontSize: "clamp(26px, 2.6vw, 42px)", color: "#e66767" })}>
                  {Math.round(p * 100)}%
                </span>
              </div>
            );
          })}
        </div>
        <p className={noteStyle}>신뢰도는 지금 이 화면에서 초 단위로 내려가고 있습니다 — 20분 뒤 다음 실측이 이 값들을 채점합니다</p>
      </section>

      {/* 하단 진행 표시 */}
      <div className={css({ position: "absolute", bottom: "22px", left: "0", right: "0", display: "flex", justifyContent: "center", gap: "10px", zIndex: "10" })}>
        {SLIDE_SEC.map((_, i) => (
          <button
            key={i}
            type="button"
            aria-label={`${i + 1}번 슬라이드`}
            onClick={(e) => { e.stopPropagation(); setSlide(i); setSlideStartMs(Date.now()); }}
            className={css({ width: "34px", height: "4px", borderRadius: "full", cursor: "pointer", borderWidth: "0", transition: "background-color 0.3s" })}
            style={{ backgroundColor: i === slide ? "#f4f4f0" : "#2c2c2e" }}
          />
        ))}
      </div>
    </main>
  );
}
