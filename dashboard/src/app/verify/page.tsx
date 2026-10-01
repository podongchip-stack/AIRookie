"use client";

import { useCallback, useEffect, useState } from "react";
import { css } from "styled-system/css";

// 시연용 신뢰도 검증 화면(2026-10-02). 대시보드 상단바 [신뢰도 검증] 모달과 시연장 큰 화면(직접 /verify)이 같이 쓴다.
// 가상 요청을 실제 E-Gen 스냅샷으로 채점한 결과(info reliability.replay_demo)를 hub GET /verification으로 받는다.
// 실제 운영 기록이 아니므로 "시연용 예시"를 항상 화면에 붙인다.

type Bin = { from: number; to: number; count: number; predicted: number | null; observed: number | null };
type Swing = { name: string; requestAt: string; arrivalSnapshotAt: string; bedsAtRequest: number; bedsAtArrival: number };
type Replay = {
  count: number;
  hospitals: number;
  period: [string, string] | null;
  validRate: number | null;
  bedsFullAtArrival: number;
  calibrationError: number | null;
  bins: Bin[];
  biggestSwing: Swing | null;
  theta: number;
  generatedAt: string | null;
};
type Reason = { code: string; axis: string; label: string; count: number };
type Verification = {
  replay: Replay | null;
  replayError?: string;
  rejections: { count: number; demoCount: number; byReason: Reason[] };
};

const AXIS_LABEL: Record<string, string> = {
  structural: "구조적",
  periodic: "주기적",
  momentary: "순간적",
  patient: "환자 요인",
  unknown: "기타",
};

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

function Stat({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className={cardStyle}>
      <span className={css({ fontSize: "xs", color: "ink3", fontWeight: "semibold" })}>{label}</span>
      <span className={css({ fontSize: "2xl", fontWeight: "bold", color: "ink" })}>{value}</span>
      {sub && <span className={css({ fontSize: "xs", color: "ink3" })}>{sub}</span>}
    </div>
  );
}

function Bar({ value, color, label }: { value: number | null; color: string; label: string }) {
  return (
    <div className={css({ display: "flex", alignItems: "center", gap: "2" })}>
      <span className={css({ width: "64px", flexShrink: "0", fontSize: "xs", color: "ink3" })}>{label}</span>
      <div className={css({ flex: "1", height: "14px", backgroundColor: "surfaceSub", borderRadius: "chip", overflow: "hidden" })}>
        <div style={{ width: `${Math.round((value ?? 0) * 100)}%`, height: "100%", backgroundColor: color }} />
      </div>
      <span className={css({ width: "40px", textAlign: "right", fontSize: "xs", fontWeight: "semibold", color: "ink" })}>{pct(value)}</span>
    </div>
  );
}

function calibrationVerdict(bins: Bin[]): string {
  const filled = bins.filter((b) => b.count >= 5 && b.predicted != null && b.observed != null);
  if (filled.length < 2) return "아직 구간별로 비교할 만큼 쌓이지 않았습니다.";
  const rising = filled.every((b, i) => i === 0 || (b.observed ?? 0) >= (filled[i - 1].observed ?? 0) - 0.02);
  const under = filled.filter((b) => (b.observed ?? 0) > (b.predicted ?? 0) + 0.05).length;
  const over = filled.filter((b) => (b.observed ?? 0) < (b.predicted ?? 0) - 0.05).length;
  const order = rising
    ? "AI가 높게 본 구간일수록 실제로도 더 자주 맞았습니다(순서는 맞음)."
    : "구간별 순서가 고르지 않습니다 — 더 쌓이면 다시 보세요.";
  const level =
    under > over
      ? " 다만 AI가 말한 확률보다 실제로 더 자주 맞았습니다 — 지금 모델은 보수적으로(낮게) 경고하는 편입니다."
      : over > under
        ? " 다만 AI가 말한 확률보다 실제로 덜 맞았습니다 — 지금 모델은 과신하는 편입니다."
        : " 확률의 크기도 실제와 비슷합니다.";
  return order + level;
}

async function fetchVerification(): Promise<{ data?: Verification; error?: string }> {
  const httpUrl = process.env.NEXT_PUBLIC_HUB_HTTP_URL;
  if (!httpUrl) return { error: "hub 주소가 없어 불러올 수 없습니다(목데이터 모드)" };
  try {
    const response = await fetch(`${httpUrl}/verification`);
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
  const maxReason = Math.max(1, ...(data?.rejections.byReason.map((r) => r.count) ?? [1]));

  return (
    <main className={css({ height: "100dvh", overflowY: "auto", backgroundColor: "bg", paddingX: "4", paddingY: "6" })}>
      <div className={css({ display: "flex", flexDirection: "column", gap: "4", maxWidth: "1200px", marginX: "auto" })}>
        <header className={css({ display: "flex", alignItems: "center", justifyContent: "space-between", gap: "3", flexWrap: "wrap" })}>
          <div className={css({ display: "flex", flexDirection: "column", gap: "1" })}>
            <div className={css({ display: "flex", alignItems: "center", gap: "2", flexWrap: "wrap" })}>
              <h1 className={css({ fontSize: "xl", fontWeight: "bold", color: "ink" })}>병상 정보 신뢰도 검증</h1>
              <span className={css({ fontSize: "xs", fontWeight: "semibold", color: "coral", backgroundColor: "coralSoft", paddingX: "2", paddingY: "0.5", borderRadius: "chip" })}>
                시연용 예시 데이터
              </span>
            </div>
            <p className={noteStyle}>
              응급실이 신고한 &quot;빈 병상 수&quot;가 구급차가 도착할 때까지도 맞을지 AI가 확률로 알려줍니다. 그 확률이 실제로 맞았는지를
              가상의 이송 요청으로 채점했습니다. 요청은 가상이지만 <b>결과는 실제 응급실 병상 기록(E-Gen)</b>으로 매겼습니다.
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

        {replay && (
          <>
            <section className={css({ display: "grid", gridTemplateColumns: { base: "repeat(2, minmax(0, 1fr))", md: "repeat(4, minmax(0, 1fr))" }, gap: "3" })}>
              <Stat label="가상 이송 요청" value={`${replay.count.toLocaleString()}건`} sub={`병원 ${replay.hospitals}곳`} />
              <Stat label="채점 기간 (실제 기록)" value={replay.period ? `${kst(replay.period[0])}` : "—"} sub={replay.period ? `~ ${kst(replay.period[1])}` : undefined} />
              <Stat label="도착 때도 병상 정보가 맞음" value={pct(replay.validRate)} sub={`${replay.theta}석 이상 바뀌면 '틀림'`} />
              <Stat label="도착해 보니 만실" value={`${replay.bedsFullAtArrival}건`} sub="요청 때는 빈 병상이 있었음" />
            </section>

            <section className={cardStyle}>
              <h2 className={headingStyle}>AI가 말한 확률 vs 실제로 맞은 비율</h2>
              <p className={noteStyle}>
                AI가 &quot;도착 때도 맞을 확률 70%&quot;라고 한 요청들을 모으면, 실제로도 70% 정도가 맞아야 잘 맞춘 확률입니다.
              </p>
              <div className={css({ display: "flex", flexDirection: "column", gap: "4" })}>
                {replay.bins.map((bin) => (
                  <div key={bin.from} className={css({ display: "flex", flexDirection: "column", gap: "1.5" })}>
                    <span className={css({ fontSize: "sm", fontWeight: "semibold", color: "ink" })}>
                      AI 예측 {Math.round(bin.from * 100)}~{Math.round(bin.to * 100)}%
                      <span className={css({ fontWeight: "normal", color: "ink3", marginLeft: "2" })}>{bin.count}건</span>
                    </span>
                    {bin.count > 0 ? (
                      <>
                        <Bar label="AI 예측" value={bin.predicted} color="#1E5FA8" />
                        <Bar label="실제" value={bin.observed} color="#0E9F6E" />
                      </>
                    ) : (
                      <span className={css({ fontSize: "xs", color: "ink3" })}>이 구간에 해당하는 요청이 없습니다</span>
                    )}
                  </div>
                ))}
              </div>
              <p className={css({ fontSize: "sm", color: "ink", fontWeight: "semibold" })}>{calibrationVerdict(replay.bins)}</p>
              <p className={css({ fontSize: "xs", color: "ink3" })}>
                평균 오차 {pct(replay.calibrationError)} · 서버가 켜져 있는 동안 병상 기록이 20분마다 쌓이고, 채점은 1시간마다 다시 합니다
                {replay.generatedAt && ` (마지막 ${kst(replay.generatedAt)})`}
              </p>
            </section>

            <div className={css({ display: "grid", gridTemplateColumns: { base: "1fr", md: "repeat(2, minmax(0, 1fr))" }, gap: "3" })}>
              {replay.biggestSwing && (
                <section className={cardStyle}>
                  <h2 className={headingStyle}>왜 확률이 필요한가 — 실제 기록 한 장면</h2>
                  <p className={css({ fontSize: "2xl", fontWeight: "bold", color: "ink" })}>
                    {replay.biggestSwing.bedsAtRequest}석 → {replay.biggestSwing.bedsAtArrival}석
                  </p>
                  <p className={noteStyle}>
                    {replay.biggestSwing.name} 응급실은 {kst(replay.biggestSwing.requestAt)}에서{" "}
                    {kst(replay.biggestSwing.arrivalSnapshotAt)} 사이에 빈 병상 수가 이만큼 바뀌었습니다. 신고된 숫자만 보고 출발하면
                    도착했을 때 상황이 다를 수 있습니다.
                  </p>
                </section>
              )}
              <section className={cardStyle}>
                <h2 className={headingStyle}>병원이 수용을 거절한 이유</h2>
                <p className={noteStyle}>
                  대시보드에서 병원이 [수용 불가]를 누를 때 고른 이유입니다. 이유의 종류에 따라 다음에 무엇을 고칠지가 달라집니다.
                </p>
                {data.rejections.byReason.length === 0 ? (
                  <span className={css({ fontSize: "xs", color: "ink3" })}>아직 기록이 없습니다</span>
                ) : (
                  data.rejections.byReason.map((reason) => (
                    <div key={reason.code} className={css({ display: "flex", alignItems: "center", gap: "2" })}>
                      <span className={css({ width: "132px", flexShrink: "0", fontSize: "xs", color: "ink" })}>
                        {reason.label}
                        <span className={css({ color: "ink3" })}> · {AXIS_LABEL[reason.axis] ?? reason.axis}</span>
                      </span>
                      <div className={css({ flex: "1", height: "12px", backgroundColor: "surfaceSub", borderRadius: "chip", overflow: "hidden" })}>
                        <div style={{ width: `${(reason.count / maxReason) * 100}%`, height: "100%", backgroundColor: "#B87514" }} />
                      </div>
                      <span className={css({ width: "32px", textAlign: "right", fontSize: "xs", fontWeight: "semibold" })}>{reason.count}</span>
                    </div>
                  ))
                )}
                <span className={css({ fontSize: "xs", color: "ink3" })}>
                  총 {data.rejections.count}건 (시연·테스트 기록 포함, 그중 예시 표시 {data.rejections.demoCount}건)
                </span>
              </section>
            </div>

            <section className={cardStyle}>
              <h2 className={headingStyle}>어떻게 채점했나</h2>
              <ol className={css({ display: "flex", flexDirection: "column", gap: "1.5", paddingLeft: "5", listStyleType: "decimal" })}>
                <li className={noteStyle}>실제 응급실 병상 기록 중 아무 시각을 골라, 빈 병상이 있던 병원에 가상의 구급차 요청을 보냅니다(이동 5~25분).</li>
                <li className={noteStyle}>그 순간 AI가 &quot;도착 때도 이 숫자가 맞을 확률&quot;을 냅니다. AI는 그 뒤의 기록을 보지 못합니다.</li>
                <li className={noteStyle}>
                  도착 시각의 실제 기록을 봅니다. 빈 병상 수가 {replay.theta}석 이상 바뀌지 않았으면 &quot;맞음&quot;입니다.
                </li>
              </ol>
              <p className={css({ fontSize: "xs", color: "ink3" })}>
                가상 요청이라 &quot;병원이 실제로 환자를 받았는가&quot;는 이 화면으로 알 수 없습니다. 그건 실제 운영 기록이 쌓여야 검증됩니다.
                병상 신뢰도 AI는 순위를 바꾸지 않고 설명으로만 쓰입니다.
              </p>
            </section>
          </>
        )}
      </div>
    </main>
  );
}
