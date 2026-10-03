"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { css } from "styled-system/css";
import { liveBedReliability } from "@/lib/bedReliability";
import type { BedReliabilityMatch } from "@/types/dashboard";

// 라이브 채점 보드(2026-10-03). hub GET /verification/live — info의 reliability.live_board가
// 실제 서빙 엔진으로 창(48시간) 안의 모든 병원 × 폴링을 재생·채점한 결과다.
// /verify의 나머지(가상 요청 표본, "시연용 예시")와 달리 이 섹션은 실측 전수 채점이라
// 배지가 다르다. 세 부분: ① 지금 못 믿을 값 보드(초 단위 감쇠) ② 판명 피드·적중 집계
// ③ 지난 24시간 90초 리플레이(실데이터 고속 재생 — 부스에서 20분 폴링 주기를 기다리지 않기 위함).

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
type CalBin = { range: string; total: number; predictedPct: number | null; actualPct: number | null };
type LiveBoard = {
  generatedAt: string;
  windowHours: number;
  theta: number;
  polls: number;
  lastPollTs: string;
  board: BoardRow[];
  feed: FeedItem[];
  calibration: { bins: CalBin[] };
  headline: { valueChanges: number; bigBreaks: number; warnedBreaks: number; missedBreaks: number };
};

const REFRESH_MS = 5 * 60 * 1000; // hub 쪽 캐시가 20분이라 5분이면 충분히 신선
const REPLAY_SEC = 90;

const cardStyle = css({
  display: "flex", flexDirection: "column", gap: "3", padding: "5",
  borderWidth: "1px", borderColor: "line", borderRadius: "panel", backgroundColor: "surface",
});
const headingStyle = css({ fontSize: "md", fontWeight: "bold", color: "ink" });
const smallStyle = css({ fontSize: "xs", color: "ink3", lineHeight: "1.5" });
const statStyle = css({ display: "flex", flexDirection: "column", gap: "0.5", minWidth: "0" });
const statValueStyle = css({ fontSize: "2xl", fontWeight: "bold", color: "ink", lineHeight: "1.1" });
const statLabelStyle = css({ fontSize: "xs", color: "ink3" });

const kstTime = (iso: string) =>
  new Date(iso).toLocaleTimeString("ko-KR", { timeZone: "Asia/Seoul", hour: "2-digit", minute: "2-digit" });

// hvec 음수는 과밀(만실 + 초과 n명, 2026-10-01 합의)이다 — 날것(-17석)으로 보여주지 않는다.
const bedLabel = (v: number) => (v > 0 ? `${v}석` : v === 0 ? "만실" : `과밀 ${-v}명`);

function pColor(p: number): string {
  if (p >= 0.8) return "var(--colors-mint, #1baf7a)";
  if (p >= 0.5) return "var(--colors-ink2, #52514e)";
  return "var(--colors-coral, #d03b3b)";
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

function FeedRow({ item }: { item: FeedItem }) {
  const warned = item.pValid < 0.5;
  const missed = item.pValid >= 0.8;
  return (
    <div className={css({ display: "flex", alignItems: "center", gap: "2", paddingY: "1.5", borderBottomWidth: "1px", borderColor: "line", _last: { borderBottomWidth: "0" }, fontSize: "sm" })}>
      <span className={css({ color: "ink3", fontVariantNumeric: "tabular-nums", flexShrink: "0" })}>{kstTime(item.ts)}</span>
      <span className={css({ fontWeight: "semibold", color: "ink", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", minWidth: "0", flex: "1" })}>
        {item.name}
      </span>
      <span className={css({ fontVariantNumeric: "tabular-nums", flexShrink: "0", color: "ink2" })}>
        {bedLabel(item.claimValue)} → {bedLabel(item.newValue)}
      </span>
      <span className={css({ fontSize: "xs", color: "ink3", flexShrink: "0" })}>{Math.round(item.ageMin)}분 묵음</span>
      <span
        className={css({ fontSize: "xs", fontWeight: "semibold", paddingX: "1.5", paddingY: "0.5", borderRadius: "chip", flexShrink: "0" })}
        style={{
          color: warned ? "#1baf7a" : missed ? "#d03b3b" : "var(--colors-ink2, #52514e)",
          backgroundColor: warned ? "rgba(27,175,122,0.12)" : missed ? "rgba(208,59,59,0.12)" : "rgba(128,128,128,0.10)",
        }}
      >
        직전 신뢰도 {Math.round(item.pValid * 100)}%{warned ? " · 미리 경고했음 ✓" : missed ? " · 못 맞힘 ✕" : ""}
      </span>
    </div>
  );
}

export function LiveBoardSection() {
  const [data, setData] = useState<LiveBoard | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [nowMs, setNowMs] = useState(() => Date.now());
  // 리플레이: 진행도 0~1, null이면 꺼짐(라이브 피드 표시)
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

  const h = data.headline;
  const warnedShare = h.bigBreaks ? Math.round((h.warnedBreaks / h.bigBreaks) * 100) : 0;

  // 리플레이 창: 마지막 폴링 기준 24시간. 피드는 최신순이라 뒤집어서 시간순으로 재생한다.
  const lastMs = Date.parse(data.lastPollTs);
  const windowStartMs = lastMs - 24 * 3600 * 1000;
  const replayFeed = [...data.feed].reverse().filter((f) => Date.parse(f.ts) >= windowStartMs);
  const replaying = replayPos != null;
  const cutoffMs = replaying ? windowStartMs + (lastMs - windowStartMs) * replayPos : null;
  const replayShown = replaying ? replayFeed.filter((f) => Date.parse(f.ts) <= (cutoffMs as number)) : [];
  const replayWarned = replayShown.filter((f) => f.pValid < 0.5).length;
  const feedToShow = replaying ? replayShown.slice(-8).reverse() : data.feed.slice(0, 8);

  return (
    <section className={cardStyle}>
      <div className={css({ display: "flex", alignItems: "center", gap: "2", flexWrap: "wrap" })}>
        <h2 className={headingStyle}>라이브 — 엔진이 지금 뭐라고 하고 있나</h2>
        <span className={css({ fontSize: "xs", fontWeight: "semibold", color: "mint", backgroundColor: "mintSoft", paddingX: "2", paddingY: "0.5", borderRadius: "chip" })}>
          실측 전수 채점 · 최근 {data.windowHours}시간 · 폴링 {data.polls}회
        </span>
        <span className={smallStyle}>마지막 폴링 {kstTime(data.lastPollTs)} · 실제 서빙 엔진 재생(시뮬 아님) · {data.theta}석 이상 어긋나면 &quot;깨짐&quot;</span>
      </div>

      {/* 적중 집계 — 핵심 숫자 4개 */}
      <div className={css({ display: "flex", gap: "6", flexWrap: "wrap" })}>
        <div className={statStyle}>
          <span className={statValueStyle}>{h.bigBreaks.toLocaleString()}</span>
          <span className={statLabelStyle}>크게 어긋남 ({data.theta}석↑, 값 변화 {h.valueChanges.toLocaleString()}건 중)</span>
        </div>
        <div className={statStyle}>
          <span className={statValueStyle} style={{ color: "#1baf7a" }}>{h.warnedBreaks.toLocaleString()}</span>
          <span className={statLabelStyle}>깨지기 전 이미 &quot;확률 50% 미만&quot; 경고 ({warnedShare}%)</span>
        </div>
        <div className={statStyle}>
          <span className={statValueStyle} style={{ color: "#d03b3b" }}>{h.missedBreaks.toLocaleString()}</span>
          <span className={statLabelStyle}>고신뢰(80%↑)였는데 깨짐</span>
        </div>
        <div className={statStyle}>
          <span className={statValueStyle}>
            {data.calibration.bins.map((b) => (b.actualPct == null ? "—" : Math.round(b.actualPct))).join(" / ")}
          </span>
          <span className={statLabelStyle}>구간별 실제 유지율(%) — 예측 {data.calibration.bins.map((b) => (b.predictedPct == null ? "—" : Math.round(b.predictedPct))).join("/")}% (단조 유지 = 순서가 맞는 확률)</span>
        </div>
      </div>

      <div className={css({ display: "grid", gridTemplateColumns: { base: "1fr", lg: "5fr 7fr" }, gap: "4" })}>
        {/* ① 지금 가장 못 믿을 값 — 초 단위 감쇠 */}
        <div className={css({ display: "flex", flexDirection: "column", gap: "1", minWidth: "0" })}>
          <h3 className={css({ fontSize: "sm", fontWeight: "semibold", color: "ink" })}>
            지금 가장 못 믿을 값 <span className={smallStyle}>(확률은 초 단위로 떨어지는 실시간 값)</span>
          </h3>
          {data.board.slice(0, 10).map((row) => {
            const p = liveP(row, nowMs);
            const ageMin = Math.max((nowMs - Date.parse(row.bornAt)) / 60000, 0);
            return (
              <div key={row.hpid} className={css({ display: "flex", alignItems: "center", gap: "2", fontSize: "sm", paddingY: "1", borderBottomWidth: "1px", borderColor: "line", _last: { borderBottomWidth: "0" } })}>
                <span className={css({ fontWeight: "semibold", color: "ink", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", minWidth: "0", flex: "1" })}>
                  {row.name}
                </span>
                <span className={css({ color: "ink2", flexShrink: "0", fontVariantNumeric: "tabular-nums" })}>{bedLabel(row.value)}</span>
                <span className={css({ fontSize: "xs", color: "ink3", flexShrink: "0" })}>{Math.round(ageMin)}분 전 값</span>
                <span className={css({ fontWeight: "bold", flexShrink: "0", fontVariantNumeric: "tabular-nums" })} style={{ color: pColor(p) }}>
                  {Math.round(p * 100)}%
                </span>
              </div>
            );
          })}
        </div>

        {/* ② 판명 피드 / ③ 리플레이 */}
        <div className={css({ display: "flex", flexDirection: "column", gap: "2", minWidth: "0" })}>
          <div className={css({ display: "flex", alignItems: "center", gap: "2", flexWrap: "wrap" })}>
            <h3 className={css({ fontSize: "sm", fontWeight: "semibold", color: "ink" })}>
              {replaying ? "리플레이 — 지난 24시간을 90초로" : "채점 기록 — E-Gen 값이 거짓으로 판명된 순간들"}
            </h3>
            <button
              type="button"
              onClick={replaying ? stopReplay : startReplay}
              className={css({ fontSize: "xs", fontWeight: "semibold", color: "ink2", backgroundColor: "surface", borderWidth: "1px", borderColor: "line", paddingX: "2.5", paddingY: "1", borderRadius: "chip", cursor: "pointer" })}
            >
              {replaying ? "■ 리플레이 종료" : "▶ 지난 24시간 90초 재생"}
            </button>
            {replaying && cutoffMs != null && (
              <span className={css({ fontSize: "sm", fontWeight: "bold", color: "ink", fontVariantNumeric: "tabular-nums" })}>
                {kstTime(new Date(cutoffMs).toISOString())} — 어긋남 {replayShown.length}건, 사전 경고 적중 {replayWarned}건
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
              <div className={css({ height: "100%", backgroundColor: "mint" })} style={{ width: `${Math.round((replayPos as number) * 100)}%` }} />
            </div>
          )}
          <div>
            {feedToShow.map((item) => (
              <FeedRow key={`${item.ts}-${item.hpid}`} item={item} />
            ))}
          </div>
        </div>
      </div>

      <p className={smallStyle}>
        채점 대상은 &quot;신고값이 유효한가&quot;이지 실제 수용 여부가 아닙니다 · 리플레이는 실데이터 고속 재생(연출 아님) · AI(XGBoost AFT 생존모델) 산출은 % 표기, 채점 규칙은 규칙 기반
      </p>
    </section>
  );
}
