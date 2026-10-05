"use client";

import { useCallback, useEffect, useState } from "react";
import { css } from "styled-system/css";
import { type HospitalHub, type HospitalView, HospitalVerifySection } from "@/components/verify/HospitalVerifySection";
import { LiveBoardSection } from "@/components/verify/LiveBoardSection";

// 시연용 신뢰도 검증 화면(2026-10-02). 대시보드 상단바 [신뢰도 검증] 모달과 시연장 큰 화면(직접 /verify)이 같이 쓴다.
// 한눈에 보여줄 것: "API(E-Gen)가 알려준 값"과 "실제"가 다르다 — 실제의 근거는 둘뿐이다.
//   ① 도착 시각의 E-Gen 자신(가상 요청을 실제 스냅샷으로 채점, info reliability.replay_demo)
//   ② 병원 신고가 아닌 공식 지정(심평원 전문병원, info hospital_score.crosscheck)
// hub GET /verification으로 받는다. 요청은 가상이라 "시연용 예시"를 항상 붙인다.

type Example = {
  name: string;
  requestAt: string;
  arrivalSnapshotAt: string;
  bedsAtRequest: number;
  bedsAtArrival: number;
  travelMin: number;
  bedRArriveAtRequest: number;
};
type Change = {
  same: number;
  changedSmall: number;
  changedBig: number;
  becameFull: number;
  meanTravelMin: number | null;
  rArriveMeanBig: number | null;
  rArriveMeanStable: number | null;
  examples: Example[];
};
type Bin = { from: number; to: number; count: number; predicted: number | null; observed: number | null };
type Replay = {
  count: number;
  hospitals: number;
  period: [string, string] | null;
  validRate: number | null;
  calibrationError: number | null;
  bins: Bin[];
  theta: number;
  generatedAt: string | null;
  change?: Change;
};
type Crosscheck = {
  asOf: string;
  hospitals: number;
  staleCount: number;
  staleBeds: { name: string; days: number; beds: number | null }[];
  severeCells: number;
  severeUnknown: number;
  specialty: { field: string; notShown: number; hospitals: { name: string; egen: string }[] }[];
};
type Verification = {
  replay: Replay | null;
  replayError?: string;
  crosscheck?: Crosscheck | null;
  hospital?: HospitalView | null;
  hospitalHub?: HospitalHub | null;
};

const COLORS = { same: "#CBD5E1", changedSmall: "#F0C36D", changedBig: "#D93F35", becameFull: "#7A1F1A" } as const;
const KIND_LABEL: Record<keyof typeof COLORS, string> = {
  same: "그대로",
  changedSmall: "1~2석 바뀜",
  changedBig: "3석 이상 바뀜",
  becameFull: "도착하니 만실",
};
const KINDS = Object.keys(COLORS) as (keyof typeof COLORS)[];

const pct = (value: number | null | undefined) => (value == null ? "—" : `${Math.round(value * 100)}%`);
const kst = (iso: string) =>
  new Date(iso).toLocaleString("ko-KR", { timeZone: "Asia/Seoul", month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" });

const cardStyle = css({
  display: "flex",
  flexDirection: "column",
  gap: "3",
  padding: "5",
  borderWidth: "1px",
  borderColor: "line",
  borderRadius: "panel",
  backgroundColor: "surface",
});
const headingStyle = css({ fontSize: "md", fontWeight: "bold", color: "ink" });
const noteStyle = css({ fontSize: "sm", color: "ink2", lineHeight: "1.6" });
const smallStyle = css({ fontSize: "xs", color: "ink3", lineHeight: "1.5" });

// 100칸에 비율대로 나눈다(최대 나머지 방식 — 합이 정확히 100). 0건이 아니면 최소 1칸은 보이게 한다.
function waffleCells(change: Change): (keyof typeof COLORS)[] {
  const total = KINDS.reduce((sum, k) => sum + change[k], 0) || 1;
  const raw = KINDS.map((k) => (change[k] / total) * 100);
  const cells = raw.map(Math.floor);
  const order = raw.map((r, i) => [r - Math.floor(r), i] as const).sort((a, b) => b[0] - a[0]);
  for (let i = 0; cells.reduce((s, c) => s + c, 0) < 100; i++) cells[order[i % KINDS.length][1]] += 1;
  KINDS.forEach((k, i) => {
    if (change[k] > 0 && cells[i] === 0) {
      cells[i] = 1;
      cells[cells.indexOf(Math.max(...cells))] -= 1;
    }
  });
  return KINDS.flatMap((k, i) => Array<keyof typeof COLORS>(cells[i]).fill(k));
}

function BedChange({ example }: { example: Example }) {
  const full = example.bedsAtArrival <= 0;
  return (
    <div className={css({ display: "flex", alignItems: "center", gap: "3", paddingY: "2", borderBottomWidth: "1px", borderColor: "line", _last: { borderBottomWidth: "0" } })}>
      <div className={css({ display: "flex", flexDirection: "column", minWidth: "0", flex: "1" })}>
        <span className={css({ fontSize: "sm", fontWeight: "semibold", color: "ink", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" })}>
          {example.name}
        </span>
        <span className={smallStyle}>
          {kst(example.requestAt)} 출발 · 이동 {Math.round(example.travelMin)}분 · AI 예측 {pct(example.bedRArriveAtRequest)}
        </span>
      </div>
      <div className={css({ display: "flex", alignItems: "baseline", gap: "2", flexShrink: "0" })}>
        <span className={css({ fontSize: "lg", fontWeight: "bold", color: "ink2" })}>{example.bedsAtRequest}석</span>
        <span className={css({ fontSize: "md", color: "ink3" })}>→</span>
        <span className={css({ fontSize: "xl", fontWeight: "bold" })} style={{ color: full ? COLORS.becameFull : COLORS.changedBig }}>
          {full ? "만실" : `${example.bedsAtArrival}석`}
        </span>
      </div>
    </div>
  );
}

async function fetchVerification(): Promise<{ data?: Verification; error?: string }> {
  const httpUrl = process.env.NEXT_PUBLIC_HUB_HTTP_URL;
  if (!httpUrl) return { error: "hub 주소가 없어 불러올 수 없습니다(목데이터 모드)" };
  try {
    // 병원 대시보드에서 열면 ?hpid=가 붙는다 — 그 병원 기록을 같이 받는다
    const hpid = new URLSearchParams(window.location.search).get("hpid");
    const response = await fetch(`${httpUrl}/verification${hpid ? `?hpid=${encodeURIComponent(hpid)}` : ""}`);
    const body = await response.json();
    if (!response.ok) return { error: body.error ?? `HTTP ${response.status}` };
    return { data: body as Verification };
  } catch (e) {
    return { error: e instanceof Error ? e.message : "불러오지 못했습니다" };
  }
}

export default function VerifyPage() {
  const [data, setData] = useState<Verification | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const apply = useCallback((result: { data?: Verification; error?: string }) => {
    if (result.data) setData(result.data);
    setError(result.error ?? null);
    setLoading(false);
  }, []);

  useEffect(() => {
    let alive = true;
    void fetchVerification().then((result) => alive && apply(result));
    return () => {
      alive = false;
    };
  }, [apply]);

  const load = () => {
    setLoading(true);
    void fetchVerification().then(apply);
  };

  const replay = data?.replay;
  const change = replay?.change;
  const cross = data?.crosscheck;
  const changedShare = change && replay ? (replay.count - change.same) / replay.count : null;
  const specialtyNotShown = cross?.specialty.reduce((s, f) => s + f.notShown, 0) ?? 0;
  const specialtyTotal = cross?.specialty.reduce((s, f) => s + f.hospitals.length, 0) ?? 0;

  return (
    <main className={css({ height: "100dvh", overflowY: "auto", backgroundColor: "bg", paddingX: "4", paddingY: "6" })}>
      <div className={css({ display: "flex", flexDirection: "column", gap: "4", maxWidth: "1200px", marginX: "auto" })}>
        <header className={css({ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: "3", flexWrap: "wrap" })}>
          <div className={css({ display: "flex", flexDirection: "column", gap: "1" })}>
            <div className={css({ display: "flex", alignItems: "center", gap: "2", flexWrap: "wrap" })}>
              <h1 className={css({ fontSize: "xl", fontWeight: "bold", color: "ink" })}>API가 알려준 병상, 도착하면 맞을까?</h1>
              <span className={css({ fontSize: "xs", fontWeight: "semibold", color: "coral", backgroundColor: "coralSoft", paddingX: "2", paddingY: "0.5", borderRadius: "chip" })}>
                시연용 예시 · 실제 E-Gen 기록으로 채점
              </span>
            </div>
            <p className={noteStyle}>
              응급실 병상 정보(E-Gen API)는 병원이 스스로 입력한 값입니다. 출발할 때 받은 숫자를, 도착 시각의 <b>실제 기록</b>과 비교했습니다.
            </p>
          </div>
          <button
            type="button"
            onClick={load}
            disabled={loading}
            className={css({ fontSize: "xs", fontWeight: "semibold", color: "ink2", backgroundColor: "surface", borderWidth: "1px", borderColor: "line", paddingX: "3", paddingY: "1.5", borderRadius: "chip", cursor: "pointer" })}
          >
            {loading ? "불러오는 중" : "새로고침"}
          </button>
        </header>

        {error && <p className={css({ fontSize: "sm", color: "coral" })}>{error}</p>}
        {data && !replay && (
          <p className={css({ fontSize: "sm", color: "coral" })}>재생 채점 결과를 만들지 못했습니다: {data.replayError ?? "알 수 없음"}</p>
        )}

        {/* 라이브 채점 보드(2026-10-03) — 아래의 가상 요청 표본("시연용 예시")과 달리 실측 전수 채점.
            hub GET /verification/live. hub가 없거나 수신구(5003)가 꺼져 있으면 한 줄 안내만 남는다. */}
        <LiveBoardSection />

        {data?.hospital && (
          <>
            <HospitalVerifySection view={data.hospital} hub={data.hospitalHub} />
            <h2 className={css({ fontSize: "lg", fontWeight: "bold", color: "ink", marginTop: "4", paddingTop: "4", borderTopWidth: "1px", borderColor: "lineStrong" })}>
              전국 전체
            </h2>
          </>
        )}

        {replay && change && changedShare != null && (
          <section className={css({ display: "grid", gridTemplateColumns: { base: "1fr", lg: "minmax(0, 1fr) minmax(0, 1fr)" }, gap: "3" })}>
            {/* ① 한눈에: 출발 때 숫자가 도착 때 얼마나 달라졌나 */}
            <div className={cardStyle}>
              <span className={css({ fontSize: "sm", fontWeight: "semibold", color: "ink2" })}>출발할 때 본 빈 병상 수가 도착했을 때는</span>
              <div className={css({ display: "flex", alignItems: "baseline", gap: "2", flexWrap: "wrap" })}>
                <span className={css({ fontSize: "5xl", fontWeight: "bold", lineHeight: "1" })} style={{ color: COLORS.changedBig }}>
                  {pct(changedShare)}
                </span>
                <span className={css({ fontSize: "lg", fontWeight: "bold", color: "ink" })}>이미 달라져 있었습니다</span>
              </div>
              <span className={smallStyle}>
                가상 이송 요청 {replay.count.toLocaleString()}건 · 병원 {replay.hospitals}곳 · 평균 이동 {change.meanTravelMin}분
                {replay.period && ` · ${kst(replay.period[0])} ~ ${kst(replay.period[1])} 실제 기록`}
              </span>
              <div aria-label="100칸 비율 그림" className={css({ display: "grid", gridTemplateColumns: "repeat(20, 1fr)", gap: "3px", marginTop: "1" })}>
                {waffleCells(change).map((kind, i) => (
                  <span key={i} title={KIND_LABEL[kind]} style={{ aspectRatio: "1", borderRadius: "3px", backgroundColor: COLORS[kind] }} />
                ))}
              </div>
              <div className={css({ display: "flex", flexWrap: "wrap", gap: "3" })}>
                {KINDS.map((kind) => (
                  <span key={kind} className={css({ display: "inline-flex", alignItems: "center", gap: "1.5", fontSize: "xs", color: "ink" })}>
                    <span style={{ width: 10, height: 10, borderRadius: 2, backgroundColor: COLORS[kind] }} />
                    {KIND_LABEL[kind]} <b>{change[kind].toLocaleString()}건</b>
                  </span>
                ))}
              </div>
            </div>

            {/* 실제 사례 */}
            <div className={cardStyle}>
              <span className={headingStyle}>실제 기록 — 출발 때 숫자 → 도착 때 숫자</span>
              <div className={css({ display: "flex", flexDirection: "column" })}>
                {change.examples.map((example) => (
                  <BedChange key={`${example.name}${example.requestAt}`} example={example} />
                ))}
              </div>
              <span className={smallStyle}>가장 크게 줄어든 경우들입니다. 숫자만 믿고 출발했다면 도착해서 다시 병원을 찾아야 했습니다.</span>
            </div>
          </section>
        )}

        {/* ② 병원 신고가 아닌 공식 기록과 대조 */}
        {cross && (
          <section className={cardStyle}>
            <div className={css({ display: "flex", alignItems: "baseline", gap: "2", flexWrap: "wrap" })}>
              <span className={headingStyle}>공식 기록에는 있는데 API에는 안 보이는 역량</span>
              <span className={smallStyle}>보건복지부 전문병원 지정(심평원) ↔ E-Gen 중증질환 수용 신고</span>
            </div>
            <div className={css({ display: "grid", gridTemplateColumns: { base: "1fr", md: "repeat(2, minmax(0, 1fr))" }, gap: "4" })}>
              <div className={css({ display: "flex", flexDirection: "column", gap: "1" })}>
                <span className={css({ fontSize: "4xl", fontWeight: "bold", lineHeight: "1" })} style={{ color: COLORS.changedBig }}>
                  {specialtyNotShown}/{specialtyTotal}곳
                </span>
                <span className={noteStyle}>전문병원으로 지정된 응급의료기관 중, E-Gen에는 그 분야를 &quot;가능&quot;으로 신고하지 않은 곳</span>
                <span className={css({ fontSize: "4xl", fontWeight: "bold", lineHeight: "1", marginTop: "3" })} style={{ color: "#B87514" }}>
                  {pct(cross.severeUnknown / Math.max(cross.severeCells, 1))}
                </span>
                <span className={noteStyle}>
                  전국 {cross.hospitals}곳의 중증질환 수용 신고 {cross.severeCells.toLocaleString()}칸 중 &quot;정보 없음&quot;
                </span>
                {cross.staleCount > 0 && (
                  <span className={noteStyle}>
                    하루 넘게 갱신 안 된 병상 값을 실시간으로 내보내는 병원 <b>{cross.staleCount}곳</b>
                    {cross.staleBeds[0] && ` (가장 오래된 곳 ${cross.staleBeds[0].days}일)`}
                  </span>
                )}
              </div>
              <div className={css({ display: "flex", flexDirection: "column", gap: "2.5" })}>
                {cross.specialty.map((field) => (
                  <div key={field.field} className={css({ display: "flex", flexDirection: "column", gap: "1" })}>
                    <span className={css({ fontSize: "sm", fontWeight: "semibold", color: "ink" })}>
                      {field.field} 전문병원 <span className={css({ color: "ink3", fontWeight: "normal" })}>{field.hospitals.length}곳</span>
                    </span>
                    <div className={css({ display: "flex", flexWrap: "wrap", gap: "1.5" })}>
                      {field.hospitals.map((h) => (
                        <span
                          key={h.name}
                          className={css({ fontSize: "xs", paddingX: "2", paddingY: "0.5", borderRadius: "chip", borderWidth: "1px" })}
                          style={
                            h.egen === "가능"
                              ? { color: "#0E9F6E", borderColor: "#0E9F6E", backgroundColor: "#E6F6F0" }
                              : { color: "#D93F35", borderColor: "#F3B4AF", backgroundColor: "#FDECEA" }
                          }
                        >
                          {h.name} · API {h.egen}
                        </span>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </div>
            <span className={smallStyle}>
              전문병원 지정은 &quot;그 분야 전문성을 인정받았다&quot;는 뜻이지 &quot;지금 받을 수 있다&quot;는 뜻은 아닙니다. 다만 API만 보는 시스템은 이 병원들을 후보로
              떠올리지 못합니다. {kst(cross.asOf)} 기준.
            </span>
          </section>
        )}

        {/* ③ 그래서 AI가 확률로 알려준다 */}
        {replay && change && (
          <section className={cardStyle}>
            <span className={headingStyle}>그래서 AI가 &quot;이 숫자, 도착할 때도 맞을 확률&quot;을 함께 보여줍니다</span>
            <div className={css({ display: "grid", gridTemplateColumns: { base: "1fr", md: "repeat(2, minmax(0, 1fr))" }, gap: "3" })}>
              {[
                { label: "실제로 3석 이상 바뀐 곳에 AI가 준 확률", value: change.rArriveMeanBig, color: COLORS.changedBig },
                { label: "거의 그대로였던 곳에 AI가 준 확률", value: change.rArriveMeanStable, color: "#0E9F6E" },
              ].map((row) => (
                <div key={row.label} className={css({ display: "flex", flexDirection: "column", gap: "1.5" })}>
                  <span className={css({ fontSize: "sm", color: "ink" })}>{row.label}</span>
                  <div className={css({ display: "flex", alignItems: "center", gap: "2" })}>
                    <div className={css({ flex: "1", height: "16px", backgroundColor: "surfaceSub", borderRadius: "chip", overflow: "hidden" })}>
                      <div style={{ width: `${Math.round((row.value ?? 0) * 100)}%`, height: "100%", backgroundColor: row.color }} />
                    </div>
                    <span className={css({ width: "44px", textAlign: "right", fontSize: "md", fontWeight: "bold" })}>{pct(row.value)}</span>
                  </div>
                </div>
              ))}
            </div>
            <span className={noteStyle}>
              AI는 그 뒤의 기록을 보지 못한 채 확률을 냈는데, 실제로 크게 바뀐 병원일수록 확률을 더 낮게 주었습니다. 확률이 낮은 병원은 출발 전에 전화로 한 번 더 확인하면 됩니다.
            </span>
            <details>
              <summary className={css({ fontSize: "xs", color: "ink2", cursor: "pointer" })}>자세히 — 확률 구간별 채점</summary>
              <div className={css({ display: "flex", flexDirection: "column", gap: "1", marginTop: "2" })}>
                {replay.bins
                  .filter((b) => b.count > 0)
                  .map((b) => (
                    <span key={b.from} className={smallStyle}>
                      AI 예측 {Math.round(b.from * 100)}~{Math.round(b.to * 100)}% ({b.count}건): 실제로 맞은 비율 {pct(b.observed)}
                    </span>
                  ))}
                <span className={smallStyle}>
                  &quot;맞음&quot; = 도착 때 병상 수가 {replay.theta}석 이상 바뀌지 않음. 지금 모델은 실제보다 확률을 낮게 말하는 편(보수적)입니다. 평균 오차 {pct(replay.calibrationError)}.
                </span>
              </div>
            </details>
          </section>
        )}

        {replay && (
          <p className={smallStyle}>
            어떻게 만들었나: 실제 응급실 병상 기록(E-Gen, 20분마다 수집) 중 아무 시각을 골라 빈 병상이 있던 병원에 가상의 구급차 요청을 보내고(이동 5~25분),
            도착 시각의 실제 기록과 비교했습니다. 요청은 가상이라 &quot;병원이 실제로 환자를 받았는가&quot;는 이 화면으로 알 수 없습니다. 서버가 켜져 있는 동안 기록이
            쌓이고 1시간마다 다시 채점합니다{replay.generatedAt && ` (마지막 ${kst(replay.generatedAt)})`}.
          </p>
        )}
      </div>
    </main>
  );
}
