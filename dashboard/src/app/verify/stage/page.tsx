"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { css } from "styled-system/css";
import {
  type LiveBoard,
  SERIES,
  HourlyBars,
  LiveChart,
  ageLabel,
  bedLabel,
  buildPoints,
  liveP,
} from "@/components/verify/LiveBoardSection";

// 스테이지 모드(2026-10-03, 10장 재구성) — 부스 대형 화면용 자동 순환 발표.
// 라이브 채점(hub /verification/live)과 검증 집계(/verification)를 함께 불러,
// 문제 → 크기 → 숨은 구멍 → 해법 → 라이브 증명 → 한계 고백 → 대량사고 확장 → 지금,
// 의 완결 서사로 돈다. 모든 장은 좌·우를 함께 쓴다(반쪽짜리 장 금지).
// 다크는 사용 장면의 선택(전시장 대형 화면·원거리 관객). ←→ 이동, 스페이스 정지, 클릭 다음 장.

const SLIDE_SEC = [11, 12, 12, 12, 14, 12, 14, 20, 14, 12];

// 대량사고 시뮬레이션(sim/out/results_ilsan.json, 2026-10-03 커밋본) — 라이브가 아니라
// 고정 실험 결과라 상수로 둔다. 숫자를 바꾸려면 sim/run.py --scene ilsan 재실행 후 여기 갱신.
const MCI = {
  caption: "2019 일산 여성병원 화재와 같은 요일·시각대 실측 스냅샷 · 사상자 138명 · 병원 19곳(가용 200병상) · 시드 20회 평균",
  arms: [
    { label: "골든링크 (동시 전달 + 배정 공유)", min: 14.7, color: "#199e70", note: "재이송 0 · 거절 전화 0" },
    { label: "최근접 집중 (정보 없음 — 이태원 당시)", min: 19.6, color: "#8a8984", note: "재이송 134건 · 쏠림 8.5배" },
    { label: "순차 전화 (평시 뺑뺑이)", min: 22.0, color: "#d95926", note: "거절 전화 288통" },
  ],
};

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
  backgroundColor: "#0d0d0d", color: "#f4f4f0", fontFamily: "inherit",
  "& ::selection": { backgroundColor: "rgba(27,175,122,0.3)" },
});
const slideBase = css({
  position: "absolute", inset: "0", display: "flex", flexDirection: "column",
  justifyContent: "center", paddingX: "clamp(32px, 6vw, 110px)", paddingTop: "48px", gap: "clamp(12px, 2.2vh, 26px)",
  transition: "opacity 0.65s cubic-bezier(0.16, 1, 0.3, 1), transform 0.65s cubic-bezier(0.16, 1, 0.3, 1)",
});
const twoColStyle = css({ display: "grid", gridTemplateColumns: "7fr 5fr", gap: "clamp(28px, 4vw, 70px)", alignItems: "center" });
const titleStyle = css({ fontSize: "clamp(26px, 2.8vw, 46px)", fontWeight: "bold", letterSpacing: "-0.02em", lineHeight: "1.3" });
const leadStyle = css({ fontSize: "clamp(18px, 1.9vw, 28px)", fontWeight: "semibold", color: "#c3c2b7", lineHeight: "1.55" });
const noteStyle = css({ fontSize: "clamp(12px, 1vw, 16px)", color: "#8a8984", lineHeight: "1.6" });
const railHeadStyle = css({ fontSize: "clamp(13px, 1.1vw, 17px)", fontWeight: "semibold", color: "#8a8984", marginBottom: "10px" });

const kstTime = (iso: string | number) =>
  new Date(iso).toLocaleTimeString("ko-KR", { timeZone: "Asia/Seoul", hour: "2-digit", minute: "2-digit" });
const kstDay = (iso: string) =>
  new Date(iso).toLocaleDateString("ko-KR", { timeZone: "Asia/Seoul", month: "numeric", day: "numeric" });

// /verification(검증 집계)에서 쓰는 부분만 — verify/page.tsx 타입의 축소판
type Summary = {
  replay?: {
    count: number;
    change?: {
      same: number; changedSmall: number; changedBig: number; becameFull: number;
      meanTravelMin: number | null;
      examples: { name: string; requestAt: string; bedsAtRequest: number; bedsAtArrival: number; travelMin: number; bedRArriveAtRequest: number }[];
    };
  } | null;
  crosscheck?: {
    hospitals: number;
    staleBeds: { name: string; days: number; beds: number | null }[];
    severeCells: number; severeUnknown: number;
    specialty: { field: string; notShown: number; hospitals: { name: string }[] }[];
  } | null;
};

function usePerSecond(): number {
  const [nowMs, setNowMs] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setNowMs(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);
  return nowMs;
}

// 10×10 와플 — 출발→도착 사이 바뀐 비율(요약 집계에서 셀 수를 비례 배분)
function WaffleMini({ change }: { change: NonNullable<NonNullable<Summary["replay"]>["change"]> }) {
  const parts = [
    { key: "same", color: "#3a3a3c", n: change.same },
    { key: "small", color: "#8a6d1a", n: change.changedSmall },
    { key: "big", color: "#c84a42", n: change.changedBig },
    { key: "full", color: "#7a1f1a", n: change.becameFull },
  ];
  const total = parts.reduce((s, p) => s + p.n, 0) || 1;
  const cells: string[] = [];
  parts.forEach((p) => {
    const want = Math.max(Math.round((p.n / total) * 100), p.n > 0 ? 1 : 0);
    for (let i = 0; i < want && cells.length < 100; i++) cells.push(p.color);
  });
  while (cells.length < 100) cells.push(parts[0].color);
  return (
    <div className={css({ display: "grid", gridTemplateColumns: "repeat(10, 1fr)", gap: "5px", width: "100%", maxWidth: "380px" })}>
      {cells.map((color, i) => (
        <div key={i} className={css({ aspectRatio: "1", borderRadius: "4px" })} style={{ backgroundColor: color }} />
      ))}
    </div>
  );
}

export default function StagePage() {
  const [data, setData] = useState<LiveBoard | null>(null);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [slide, setSlide] = useState(0);
  const [paused, setPaused] = useState(false);
  const nowMs = usePerSecond();
  const [slideStartMs, setSlideStartMs] = useState<number | null>(null);

  const load = useCallback(async () => {
    const httpUrl = process.env.NEXT_PUBLIC_HUB_HTTP_URL;
    if (!httpUrl) {
      setError("hub 주소가 없습니다 (NEXT_PUBLIC_HUB_HTTP_URL)");
      return;
    }
    try {
      const live = await fetch(`${httpUrl}/verification/live`);
      const liveBody = await live.json();
      if (!live.ok) throw new Error(liveBody.error ?? `HTTP ${live.status}`);
      setData(liveBody as LiveBoard);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "라이브 데이터를 불러오지 못했습니다");
    }
    try {
      const sum = await fetch(`${httpUrl}/verification`);
      if (sum.ok) setSummary((await sum.json()) as Summary);
    } catch {
      // 요약은 보조 — 실패해도 라이브 장들만으로 돈다
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

  const agg = useMemo(() => {
    const ts = data?.timeseries ?? [];
    const sum = (k: "n" | "held" | "hiN" | "hiHeld" | "warnN" | "warnHeld") => ts.reduce((a, p) => a + p[k], 0);
    return {
      allPct: sum("n") ? Math.round((sum("held") / sum("n")) * 100) : 0,
      hiPct: sum("hiN") ? Math.round((sum("hiHeld") / sum("hiN")) * 1000) / 10 : 0,
      warnPct: sum("warnN") ? Math.round((sum("warnHeld") / sum("warnN")) * 100) : 0,
    };
  }, [data]);

  // 리플레이 장(8번, index 7): 머무는 동안 지난 24시간을 20초 주기로 반복 재생
  const replay = useMemo(() => {
    if (!data || slide !== 7) return null;
    const lastMs = Date.parse(data.lastPollTs);
    const startMs = lastMs - 24 * 3600 * 1000;
    const pos = ((nowMs - (slideStartMs ?? nowMs)) / 1000 % 20) / 20;
    const cutoff = startMs + (lastMs - startMs) * pos;
    const events = [...data.feed].reverse().filter((f) => {
      const t = Date.parse(f.ts);
      return t >= startMs && t <= cutoff;
    });
    return { cutoff, events, warned: events.filter((f) => f.pValid < 0.5).length };
  }, [data, slide, nowMs, slideStartMs]);

  if (error) return <main className={stageStyle} style={DARK_VARS as React.CSSProperties}><p className={css({ margin: "auto", color: "#c3c2b7" })}>{error}</p></main>;
  if (!data) return <main className={stageStyle} style={DARK_VARS as React.CSSProperties}><p className={css({ margin: "auto", color: "#c3c2b7" })}>라이브 데이터 불러오는 중…</p></main>;

  const h = data.headline;
  const perDay = Math.round(h.bigBreaks / (data.windowHours / 24));
  const change = summary?.replay?.change;
  const changedShare = change && summary?.replay
    ? Math.round(((summary.replay.count - change.same) / Math.max(summary.replay.count, 1)) * 100)
    : null;
  const cross = summary?.crosscheck;
  const burn = cross?.specialty.find((s) => s.field.includes("화상")) ?? cross?.specialty[0];
  const specialtyNotShown = cross?.specialty.reduce((s, f) => s + f.notShown, 0) ?? 0;
  const specialtyTotal = cross?.specialty.reduce((s, f) => s + f.hospitals.length, 0) ?? 0;
  const stalest = cross?.staleBeds?.[0];
  const regions = (data.regions ?? []).filter((r) => r.label !== "기타" && r.allPct != null && r.hiPct != null);
  const minRegion = regions.length ? Math.floor(Math.min(...regions.map((r) => r.allPct as number))) - 1 : 88;
  const regionPos = (v: number) => `${((v - minRegion) / (100 - minRegion)) * 100}%`;
  const surging = (data.regime?.current.level ?? 0) >= 1;
  const mciMax = Math.max(...MCI.arms.map((a) => a.min));

  const slideProps = (index: number) => ({
    className: slideBase,
    style: {
      opacity: slide === index ? 1 : 0,
      transform: slide === index ? "translateY(0)" : "translateY(26px)",
      pointerEvents: slide === index ? ("auto" as const) : ("none" as const),
    },
  });

  // 우측 레일 공용 — 지금 가장 의심스러운 신고값 (라이브 감쇠).
  // 렌더 중 컴포넌트 생성 금지(lint) — 컴포넌트가 아니라 조각을 돌려주는 함수로 둔다.
  const suspectRail = (count: number) => (
    <div>
      <p className={railHeadStyle}>지금 가장 의심스러운 신고값 — 라이브</p>
      <div className={css({ display: "flex", flexDirection: "column", gap: "clamp(6px, 1vh, 12px)" })}>
        {data.board.slice(0, count).map((row) => {
          const p = liveP(row, nowMs);
          return (
            <div key={row.hpid} className={css({ display: "flex", alignItems: "baseline", gap: "12px", fontSize: "clamp(14px, 1.25vw, 19px)" })}>
              <span className={css({ fontWeight: "semibold", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", minWidth: "0", flex: "1" })}>{row.name}</span>
              <span className={css({ color: "#8a8984", flexShrink: "0", fontSize: "0.85em" })}>{bedLabel(row.value)} · {ageLabel(Math.max((nowMs - Date.parse(row.bornAt)) / 60000, 0))}</span>
              <span className={css({ fontWeight: "bold", fontVariantNumeric: "tabular-nums", flexShrink: "0", width: "64px", textAlign: "right", color: "#e66767" })}>{Math.round(p * 100)}%</span>
            </div>
          );
        })}
      </div>
    </div>
  );

  return (
    <main className={stageStyle} style={DARK_VARS as React.CSSProperties} onClick={() => go(1)}>
      <div className={css({ position: "absolute", top: "0", left: "0", right: "0", display: "flex", alignItems: "center", gap: "14px", paddingX: "clamp(32px, 6vw, 110px)", paddingY: "16px", fontSize: "clamp(12px, 1vw, 15px)", color: "#8a8984", zIndex: "10" })}>
        <span className={css({ display: "inline-flex", alignItems: "center", gap: "7px", color: "#1baf7a", fontWeight: "semibold" })}>
          <span className={css({ width: "8px", height: "8px", borderRadius: "full", backgroundColor: "#1baf7a", animation: "pulse 2.2s ease-out infinite" })} />
          라이브 — 실제 E-Gen 기록, 골든링크 모델을 20분마다 채점
        </span>
        <span>마지막 폴링 {kstTime(data.lastPollTs)}</span>
        {surging && <span className={css({ color: "#e66767", fontWeight: "semibold" })}>전국 변동 {data.regime!.current.level >= 2 ? "급증" : "주의"} · 평시의 {data.regime!.current.ratio}배</span>}
        <span className={css({ marginLeft: "auto" })}>{paused ? "일시정지 (스페이스)" : "←→ 이동 · 스페이스 정지"}</span>
      </div>
      <style>{`@keyframes pulse { 0% { box-shadow: 0 0 0 0 rgba(27,175,122,0.6); } 100% { box-shadow: 0 0 0 14px rgba(27,175,122,0); } }`}</style>

      {/* 1 — 훅: 좌 선언 / 우 라이브 의심 신고값 */}
      <section {...slideProps(0)}>
        <div className={twoColStyle}>
          <div className={css({ display: "flex", flexDirection: "column", gap: "clamp(12px, 2vh, 24px)" })}>
            <p className={leadStyle}>응급실 병상 숫자는 국가 API(E-Gen)가 알려줍니다. 그런데 —</p>
            <h1 className={css({ fontSize: "clamp(36px, 4.4vw, 72px)", fontWeight: "bold", letterSpacing: "-0.03em", lineHeight: "1.2" })}>
              그 숫자, 하루 <span className={css({ color: "#e66767" })}>{perDay.toLocaleString()}번</span><br />크게 어긋납니다.
            </h1>
            <p className={leadStyle}>그래서 골든링크의 모델은 <b className={css({ color: "#f4f4f0" })}>API의 숫자를 그대로 믿지 않습니다</b> — 값마다 의심하고, 20분마다 실측으로 검증받습니다.</p>
          </div>
          {suspectRail(6)}
        </div>
        <p className={noteStyle}>지난 {data.windowHours}시간, 전국 병원 {h.valueChanges.toLocaleString()}번의 실측 값 변화로 직접 센 숫자입니다</p>
      </section>

      {/* 2 — 문제의 크기: 좌 53% 와플 / 우 실제 추락 사례 */}
      <section {...slideProps(1)}>
        <h1 className={titleStyle}>출발할 때 본 빈 병상, 도착하면 {changedShare != null ? <span className={css({ color: "#e66767" })}>{changedShare}%</span> : "절반 넘게"}가 이미 달라져 있습니다</h1>
        <div className={twoColStyle}>
          <div className={css({ display: "flex", gap: "clamp(20px, 2.6vw, 44px)", alignItems: "center" })}>
            {change && <WaffleMini change={change} />}
            <div className={css({ display: "flex", flexDirection: "column", gap: "10px", fontSize: "clamp(14px, 1.3vw, 20px)", color: "#c3c2b7" })}>
              <span><span className={css({ display: "inline-block", width: "12px", height: "12px", borderRadius: "3px", backgroundColor: "#3a3a3c", marginRight: "8px" })} />그대로 {change?.same.toLocaleString()}건</span>
              <span><span className={css({ display: "inline-block", width: "12px", height: "12px", borderRadius: "3px", backgroundColor: "#8a6d1a", marginRight: "8px" })} />1~2석 바뀜 {change?.changedSmall.toLocaleString()}건</span>
              <span><span className={css({ display: "inline-block", width: "12px", height: "12px", borderRadius: "3px", backgroundColor: "#c84a42", marginRight: "8px" })} />3석 이상 {change?.changedBig.toLocaleString()}건</span>
              <span><span className={css({ display: "inline-block", width: "12px", height: "12px", borderRadius: "3px", backgroundColor: "#7a1f1a", marginRight: "8px" })} />도착하니 만실 {change?.becameFull.toLocaleString()}건</span>
            </div>
          </div>
          <div>
            <p className={railHeadStyle}>가장 크게 추락한 실제 기록 — 출발 때 → 도착 때</p>
            <div className={css({ display: "flex", flexDirection: "column", gap: "clamp(8px, 1.3vh, 14px)" })}>
              {(change?.examples ?? []).slice(0, 4).map((ex) => (
                <div key={`${ex.name}-${ex.requestAt}`} className={css({ display: "flex", alignItems: "baseline", gap: "12px", fontSize: "clamp(14px, 1.3vw, 20px)" })}>
                  <span className={css({ fontWeight: "semibold", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", minWidth: "0", flex: "1" })}>{ex.name}</span>
                  <span className={css({ color: "#8a8984", fontSize: "0.8em", flexShrink: "0" })}>{kstDay(ex.requestAt)} · 이동 {Math.round(ex.travelMin)}분</span>
                  <span className={css({ fontVariantNumeric: "tabular-nums", flexShrink: "0" })}>
                    {ex.bedsAtRequest}석 → <b className={css({ color: "#e66767" })}>{ex.bedsAtArrival <= 0 ? "만실" : `${ex.bedsAtArrival}석`}</b>
                  </span>
                </div>
              ))}
            </div>
          </div>
        </div>
        <p className={noteStyle}>가상 이송 요청 {summary?.replay?.count.toLocaleString() ?? "—"}건을 실제 E-Gen 다음 기록으로 채점(시연용 예시) · 숫자만 믿고 출발했다면 도착해서 다시 병원을 찾아야 했습니다</p>
      </section>

      {/* 3 — 숨은 구멍: 공식 기록 vs API */}
      <section {...slideProps(2)}>
        <h1 className={titleStyle}>어긋나는 것만이 문제가 아닙니다 — <span className={css({ color: "#e66767" })}>아예 안 보이는 것</span>도 있습니다</h1>
        <div className={twoColStyle}>
          <div className={css({ display: "flex", flexDirection: "column", gap: "clamp(14px, 2.2vh, 26px)" })}>
            <div>
              <span className={css({ fontSize: "clamp(44px, 5vw, 80px)", fontWeight: "bold", letterSpacing: "-0.03em", color: "#e66767", fontVariantNumeric: "tabular-nums" })}>
                {specialtyNotShown}/{specialtyTotal}곳
              </span>
              <p className={leadStyle}>보건복지부가 지정한 전문병원인데, E-Gen에는 해당 수용 신고가 없는 곳</p>
            </div>
            {burn && burn.notShown > 0 && (
              <p className={css({ fontSize: "clamp(15px, 1.4vw, 22px)", color: "#c3c2b7" })}>
                예: {burn.field} — 지정 {burn.hospitals.length}곳 중 <b className={css({ color: "#e66767" })}>{burn.notShown}곳</b>이 API에 역량이 보이지 않습니다
              </p>
            )}
            <p className={css({ fontSize: "clamp(15px, 1.4vw, 22px)", color: "#c3c2b7" })}>
              중증질환 수용 신고 칸 {cross?.severeCells.toLocaleString() ?? "—"}개 중 <b className={css({ color: "#f4f4f0" })}>{cross ? Math.round((cross.severeUnknown / Math.max(cross.severeCells, 1)) * 100) : "—"}%가 &quot;정보 없음&quot;</b>
            </p>
          </div>
          <div>
            <p className={railHeadStyle}>지금도 송출 중인, 가장 오래 그대로인 병상 신고 — 라이브</p>
            <div className={css({ display: "flex", flexDirection: "column", gap: "clamp(8px, 1.3vh, 14px)" })}>
              {/* crosscheck(hvidate 기준)가 잡은 게 있으면 우선, 없으면 라이브 보드에서
                  "값이 그대로인 채 가장 오래된 신고"를 뽑는다 — hvidate는 시스템이 자동
                  갱신해 값이 안 변해도 새로 찍히므로 crosscheck가 0건인 시점이 많다. */}
              {(cross?.staleBeds?.length
                ? cross.staleBeds.slice(0, 5).map((row) => ({
                    key: row.name, name: row.name,
                    right: `${row.days.toLocaleString()}일째 그대로`, sub: null as string | null,
                  }))
                : [...data.board]
                    .sort((a, b) => Date.parse(a.bornAt) - Date.parse(b.bornAt))
                    .slice(0, 5)
                    .map((row) => ({
                      key: row.hpid, name: row.name,
                      right: ageLabel(Math.max((nowMs - Date.parse(row.bornAt)) / 60000, 0)).replace(" 전 신고", "째 같은 값"),
                      sub: `${bedLabel(row.value)} · 신뢰도 ${Math.round(liveP(row, nowMs) * 100)}%`,
                    }))
              ).map((row) => (
                <div key={row.key} className={css({ display: "flex", alignItems: "baseline", gap: "12px", fontSize: "clamp(14px, 1.3vw, 20px)" })}>
                  <span className={css({ fontWeight: "semibold", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", minWidth: "0", flex: "1" })}>{row.name}</span>
                  {row.sub && <span className={css({ color: "#8a8984", fontSize: "0.8em", flexShrink: "0" })}>{row.sub}</span>}
                  <span className={css({ fontVariantNumeric: "tabular-nums", color: "#e66767", fontWeight: "bold", flexShrink: "0" })}>{row.right}</span>
                </div>
              ))}
            </div>
            <p className={css({ marginTop: "12px", fontSize: "clamp(13px, 1.1vw, 17px)", color: "#8a8984" })}>
              {stalest
                ? `최고 기록 ${Math.round((stalest.days / 365) * 10) / 10}년 — 같은 소스 안에서는 이걸 걸러낼 방법이 없습니다`
                : "역대 실측 최고 기록은 2,457일(6.7년) 묵은 값이 전국 가용병상 1위로 떠 있던 사례였습니다"}
            </p>
          </div>
        </div>
        <p className={noteStyle}>심평원(전문병원 지정·전문의 수) 공식 기록과 E-Gen을 좌표로 교차검증한 결과 — 골든링크가 두 소스를 함께 쓰는 이유</p>
      </section>

      {/* 4 — 해법: 세 숫자 + 캘리브레이션 */}
      <section {...slideProps(3)}>
        <h1 className={titleStyle}>같은 숫자, 믿는 방법만 바꿨습니다</h1>
        <div className={css({ display: "grid", gridTemplateColumns: "8fr 4fr", gap: "clamp(28px, 4vw, 70px)", alignItems: "center" })}>
          <div className={css({ display: "flex", gap: "clamp(24px, 3.6vw, 70px)", flexWrap: "wrap", alignItems: "flex-end" })}>
            {[
              { label: "모든 신고값을 그대로 믿으면", pct: `${agg.allPct}%`, color: SERIES.all.color },
              { label: "골든링크 모델이 “믿어도 됨”으로 고른 값만 믿으면", pct: `${agg.hiPct}%`, color: "#3987e5" },
              { label: "모델이 “위험”으로 경고한 값은", pct: `${agg.warnPct}%`, color: "#d95926" },
            ].map((item, i) => (
              <div key={item.label} className={css({ display: "flex", flexDirection: "column", gap: "6px", transition: "opacity 0.5s ease-out" })}
                style={{ opacity: slide === 3 ? 1 : 0, transitionDelay: `${i * 0.45}s` }}>
                <span className={css({ fontSize: "clamp(13px, 1.2vw, 18px)", color: "#c3c2b7", maxWidth: "26ch" })}>{item.label}</span>
                <span className={css({ fontSize: "clamp(48px, 6vw, 88px)", fontWeight: "bold", letterSpacing: "-0.035em", lineHeight: "1", fontVariantNumeric: "tabular-nums" })} style={{ color: item.color }}>
                  {item.pct}
                </span>
              </div>
            ))}
          </div>
          <div>
            <p className={railHeadStyle}>모델이 말한 확률 순서대로, 실제도 그 순서였나</p>
            <div className={css({ display: "flex", flexDirection: "column", gap: "10px" })}>
              {data.calibration.bins.map((bin) => (
                <div key={bin.range} className={css({ display: "flex", alignItems: "center", gap: "10px", fontSize: "clamp(12px, 1.05vw, 16px)" })}>
                  <span className={css({ width: "76px", color: "#8a8984", flexShrink: "0", fontVariantNumeric: "tabular-nums" })}>{bin.range}</span>
                  <div className={css({ flex: "1", position: "relative", height: "14px", backgroundColor: "#1f1f21", borderRadius: "full", overflow: "hidden" })}>
                    <div className={css({ position: "absolute", top: "0", bottom: "0", left: "0", borderRadius: "full", backgroundColor: "#3987e5" })} style={{ width: `${bin.actualPct ?? 0}%` }} />
                  </div>
                  <span className={css({ width: "52px", textAlign: "right", fontWeight: "semibold", fontVariantNumeric: "tabular-nums", flexShrink: "0" })}>{bin.actualPct == null ? "—" : `${Math.round(bin.actualPct)}%`}</span>
                </div>
              ))}
            </div>
            <p className={css({ marginTop: "10px", fontSize: "clamp(12px, 1vw, 15px)", color: "#8a8984" })}>신뢰도 구간별 실제 유지율 — 순서가 지켜지는 확률(단조)</p>
          </div>
        </div>
        <p className={noteStyle}>유지율 = 다음 실측(20분 뒤)에서 3석 이상 어긋나지 않은 비율 · 48시간 전수 채점 · 경고는 장식이 아닙니다</p>
      </section>

      {/* 5 — 라이브 차트 */}
      <section {...slideProps(4)}>
        <h1 className={titleStyle}>20분마다 점이 하나씩 — <span className={css({ color: "#3987e5" })}>모델이 고른 값</span>은 늘 위에 있습니다</h1>
        {points.length >= 3 && (
          <div className={css({ "& text": { fontSize: "13px" } })}>
            <LiveChart points={points} cutoffMs={null} lastPollMs={Date.parse(data.lastPollTs)} />
          </div>
        )}
        <p className={noteStyle}>붉은 띠 = 전국이 동시에 움직인 공통충격(평시 3배 이상) — 개별 예측이 아니라 감지 대상이라 시스템이 스스로 표시합니다</p>
      </section>

      {/* 6 — 하루의 리듬 */}
      <section {...slideProps(5)}>
        <h1 className={titleStyle}>어긋남에는 <span className={css({ color: "#d95926" })}>하루의 리듬</span>이 있습니다</h1>
        {data.timeseries && data.timeseries.length >= 24 && (
          <div className={css({ "& text": { fontSize: "15px" } })}>
            <HourlyBars timeseries={data.timeseries} tall />
          </div>
        )}
        <p className={noteStyle}>시간대별(KST) 폴링당 평균 어긋남 — 아침 병상 정리 러시가 가장 위험한 시간입니다. 모델이 아침 신고값의 신뢰도를 깎는 이유.</p>
      </section>

      {/* 7 — 지역 격차 (2열 전폭) */}
      <section {...slideProps(6)}>
        <h1 className={titleStyle}>신고값 품질은 지역 복불복 — 모델을 거치면 <span className={css({ color: "#3987e5" })}>어디서나 96% 이상</span></h1>
        <div className={css({ display: "grid", gridTemplateColumns: "1fr 1fr", columnGap: "clamp(40px, 5vw, 90px)", rowGap: "clamp(8px, 1.4vh, 16px)" })}>
          {regions.map((region, i) => (
            <div key={region.label} className={css({ display: "flex", alignItems: "center", gap: "16px", fontSize: "clamp(13px, 1.2vw, 19px)", transition: "opacity 0.4s ease-out" })}
              style={{ opacity: slide === 6 ? 1 : 0, transitionDelay: `${i * 0.07}s` }}>
              <span className={css({ width: "46px", fontWeight: "semibold", flexShrink: "0" })}>{region.label}</span>
              <div className={css({ position: "relative", flex: "1", height: "20px" })}>
                <div className={css({ position: "absolute", top: "50%", left: "0", right: "0", height: "1px", backgroundColor: "#2c2c2e" })} />
                <div className={css({ position: "absolute", top: "50%", height: "6px", transform: "translateY(-50%)", borderRadius: "full", backgroundColor: "rgba(57,135,229,0.3)" })}
                  style={{ left: regionPos(region.allPct as number), width: `calc(${regionPos(region.hiPct as number)} - ${regionPos(region.allPct as number)})` }} />
                <span className={css({ position: "absolute", top: "50%", width: "10px", height: "10px", borderRadius: "full", transform: "translate(-50%,-50%)", backgroundColor: "#8a8984" })} style={{ left: regionPos(region.allPct as number) }} />
                <span className={css({ position: "absolute", top: "50%", width: "10px", height: "10px", borderRadius: "full", transform: "translate(-50%,-50%)", backgroundColor: "#3987e5" })} style={{ left: regionPos(region.hiPct as number) }} />
              </div>
              <span className={css({ flexShrink: "0", fontVariantNumeric: "tabular-nums", color: "#c3c2b7", width: "132px", textAlign: "right" })}>
                {region.allPct} → <b className={css({ color: "#f4f4f0" })}>{region.hiPct}%</b>
              </span>
            </div>
          ))}
        </div>
        <p className={noteStyle}>회색 = 모든 신고값 · 파랑 = 모델이 고른 값 · 띠 길이 = 모델이 끌어올린 폭 — 원값이 나쁜 지역일수록 이득이 큽니다 (서울·경기가 하위권인 건 수도권 응급실의 회전 속도)</p>
      </section>

      {/* 8 — 24시간 자동 리플레이 */}
      <section {...slideProps(7)}>
        <h1 className={titleStyle}>
          지난 24시간을 20초로 — {replay ? kstTime(replay.cutoff) : ""}
        </h1>
        <div className={twoColStyle}>
          <div className={css({ display: "flex", flexDirection: "column", gap: "clamp(6px, 1vh, 12px)", fontSize: "clamp(14px, 1.3vw, 20px)" })}>
            {(replay?.events.slice(-7).reverse() ?? []).map((f) => (
              <div key={`${f.ts}-${f.hpid}`} className={css({ display: "flex", alignItems: "baseline", gap: "14px" })}>
                <span className={css({ color: "#8a8984", fontVariantNumeric: "tabular-nums", flexShrink: "0" })}>{kstTime(f.ts)}</span>
                <span className={css({ fontWeight: "semibold", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", minWidth: "0", flex: "1" })}>{f.name}</span>
                <span className={css({ color: "#c3c2b7", fontVariantNumeric: "tabular-nums", flexShrink: "0" })}>{bedLabel(f.claimValue)} → {bedLabel(f.newValue)}</span>
                <span className={css({ flexShrink: "0", fontVariantNumeric: "tabular-nums" })} style={{ color: f.pValid < 0.5 ? "#1baf7a" : f.pValid >= 0.8 ? "#e66767" : "#8a8984" }}>
                  {Math.round(f.pValid * 100)}%{f.pValid < 0.5 ? " · 사전 경고" : ""}
                </span>
              </div>
            ))}
          </div>
          <div className={css({ display: "flex", flexDirection: "column", gap: "clamp(14px, 2.4vh, 30px)" })}>
            <div>
              <span className={css({ fontSize: "clamp(44px, 5vw, 80px)", fontWeight: "bold", letterSpacing: "-0.03em", fontVariantNumeric: "tabular-nums" })}>{replay?.events.length.toLocaleString() ?? 0}</span>
              <p className={leadStyle}>어긋남</p>
            </div>
            <div>
              <span className={css({ fontSize: "clamp(44px, 5vw, 80px)", fontWeight: "bold", letterSpacing: "-0.03em", color: "#1baf7a", fontVariantNumeric: "tabular-nums" })}>{replay?.warned.toLocaleString() ?? 0}</span>
              <p className={leadStyle}>모델이 미리 경고했던 것</p>
            </div>
          </div>
        </div>
        <p className={noteStyle}>실데이터 재생입니다(연출 아님) — 신고값이 3석 이상 어긋난 순간과, 어긋나기 직전 모델이 매긴 신뢰도</p>
      </section>

      {/* 9 — 대량사고 시뮬레이션 */}
      <section {...slideProps(8)}>
        <h1 className={titleStyle}>대량사고에서는 이 차이가 <span className={css({ color: "#199e70" })}>골든타임</span>이 됩니다</h1>
        <div className={css({ display: "flex", flexDirection: "column", gap: "clamp(12px, 2vh, 22px)", maxWidth: "1250px" })}>
          {MCI.arms.map((arm, i) => (
            <div key={arm.label} className={css({ display: "flex", alignItems: "center", gap: "18px", transition: "opacity 0.45s ease-out" })}
              style={{ opacity: slide === 8 ? 1 : 0, transitionDelay: `${i * 0.3}s` }}>
              <span className={css({ width: "min(34vw, 420px)", fontSize: "clamp(14px, 1.35vw, 21px)", fontWeight: "semibold", flexShrink: "0" })}>{arm.label}</span>
              <div className={css({ flex: "1", position: "relative", height: "clamp(26px, 3.6vh, 40px)" })}>
                <div className={css({ position: "absolute", inset: "0", borderRadius: "8px", backgroundColor: "#1f1f21" })} />
                <div className={css({ position: "absolute", top: "0", bottom: "0", left: "0", borderRadius: "8px" })}
                  style={{ width: `${(arm.min / mciMax) * 100}%`, backgroundColor: arm.color }} />
                <span className={css({ position: "absolute", top: "50%", transform: "translateY(-50%)", fontWeight: "bold", fontSize: "clamp(15px, 1.5vw, 23px)", fontVariantNumeric: "tabular-nums", color: "#0d0d0d" })}
                  style={{ left: `calc(${(arm.min / mciMax) * 100}% - 86px)` }}>
                  {arm.min}분
                </span>
              </div>
              <span className={css({ width: "190px", fontSize: "clamp(12px, 1.05vw, 16px)", color: "#8a8984", flexShrink: "0" })}>{arm.note}</span>
            </div>
          ))}
        </div>
        <p className={leadStyle}>사상자 한 명이 수용되기까지 중앙값 — 순차 전화 대비 <b className={css({ color: "#199e70" })}>7분 이상</b> 빠르고, 쏠림과 재이송이 사라집니다</p>
        <p className={noteStyle}>{MCI.caption} · 세 방식은 같은 환자·같은 병상에서 출발, 차이는 정보 전달 방식뿐 · 상수 민감도 전 구간에서 순서 유지 (sim/)</p>
      </section>

      {/* 10 — 마무리: 지금 이 순간 */}
      <section {...slideProps(9)}>
        <div className={twoColStyle}>
          <div className={css({ display: "flex", flexDirection: "column", gap: "clamp(12px, 2vh, 24px)" })}>
            <h1 className={css({ fontSize: "clamp(34px, 4vw, 64px)", fontWeight: "bold", letterSpacing: "-0.03em", lineHeight: "1.25" })}>
              의심하고, 검증받는<br />데이터만이<br /><span className={css({ color: "#1baf7a" })}>생명을 나릅니다.</span>
            </h1>
            <p className={leadStyle}>골든링크 — 전화 한 통의 내용이 존 전체 병원에 동시에 닿고, 모든 숫자가 신뢰도와 함께 전달되는 응급이송 플랫폼</p>
          </div>
          {suspectRail(6)}
        </div>
        <p className={noteStyle}>이 화면의 모든 숫자는 실제 국가 API 기록과 실제 서빙 모델에서 나왔습니다 · 지금도 20분마다 다시 채점되고 있습니다</p>
      </section>

      <div className={css({ position: "absolute", bottom: "20px", left: "0", right: "0", display: "flex", justifyContent: "center", gap: "9px", zIndex: "10" })}>
        {SLIDE_SEC.map((_, i) => (
          <button
            key={i}
            type="button"
            aria-label={`${i + 1}번 슬라이드`}
            onClick={(e) => { e.stopPropagation(); setSlide(i); setSlideStartMs(Date.now()); }}
            className={css({ width: "30px", height: "4px", borderRadius: "full", cursor: "pointer", borderWidth: "0", transition: "background-color 0.3s" })}
            style={{ backgroundColor: i === slide ? "#f4f4f0" : "#2c2c2e" }}
          />
        ))}
      </div>
    </main>
  );
}
