"use client";

import { css } from "styled-system/css";

// 검증 화면의 "우리 병원" 칸(2026-10-02). 병원 대시보드에서 열면(/verify?hpid=) 맨 위에 뜬다.
// info hospital_score.hospital_view(그 병원 스냅샷 전부·신고·심평원·거절 로그) + hub(의사결정 로그·지금 신뢰도).

export type HospitalView = {
  hospitalId: string;
  name: string | null;
  emergencyLevel: string | null;
  snapshots: number;
  period: [string, string] | null;
  chart: { t: string; v: number }[];
  departures: {
    travelMin: number;
    theta: number;
    same: number;
    changedSmall: number;
    changedBig: number;
    becameFull: number;
    worst: { requestAt: string; arrivalAt: string; bedsAtRequest: number; bedsAtArrival: number } | null;
  } | null;
  rhythm: { updates: number; fullShare: number; minBeds: number; maxBeds: number; lastValue: number; lastAt: string; lastUpdateAgeMin: number | null } | null;
  severe: { group: string; egen: string }[];
  designated: { field: string; egen: string }[];
  specialists: { department: string; count: number }[];
  rejections: { count: number; byReason: { code: string; label: string; count: number }[]; recent: { timestamp: string; code: string; label: string }[] };
};
export type HospitalHub = {
  selfInfo: { availableBedCount: number; bedCountUnknown: boolean; bedReliability?: { authority: number } | null } | null;
  activity: {
    requestedCases: number;
    counts: { kind: string; label: string; count: number }[];
    recent: { timestamp: string; kind: string; label: string }[];
  };
};

const RED = "#D93F35";
const DARK = "#7A1F1A";
const AMBER = "#F0C36D";
const GRAY = "#CBD5E1";
const GREEN = "#0E9F6E";
const GAP_MS = 60 * 60 * 1000;

const pct = (value: number | null | undefined) => (value == null ? "—" : `${Math.round(value * 100)}%`);
const kst = (iso: string) =>
  new Date(iso).toLocaleString("ko-KR", { timeZone: "Asia/Seoul", month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" });

const cardStyle = css({ display: "flex", flexDirection: "column", gap: "3", padding: "5", borderWidth: "1px", borderColor: "line", borderRadius: "panel", backgroundColor: "surface" });
const headingStyle = css({ fontSize: "md", fontWeight: "bold", color: "ink" });
const noteStyle = css({ fontSize: "sm", color: "ink2", lineHeight: "1.6" });
const smallStyle = css({ fontSize: "xs", color: "ink3", lineHeight: "1.5" });

// 응급실 빈 병상 수의 실제 기록. 0 아래(만실·과밀)는 붉게 칠한다.
function BedChart({ points }: { points: { t: string; v: number }[] }) {
  if (points.length < 2) return <span className={smallStyle}>기록이 아직 적습니다</span>;
  const W = 600;
  const H = 150;
  const t0 = Date.parse(points[0].t);
  const t1 = Date.parse(points[points.length - 1].t);
  const lo = Math.min(0, ...points.map((p) => p.v));
  const hi = Math.max(1, ...points.map((p) => p.v));
  const x = (t: string) => ((Date.parse(t) - t0) / Math.max(t1 - t0, 1)) * W;
  const y = (v: number) => H - ((v - lo) / (hi - lo)) * H;
  // 수집이 GAP_MS 넘게 끊긴 곳(맥이 잠든 동안 등)은 선을 끊는다 — 이어 그리면 그동안 그대로였던 것처럼 보인다
  const segments: string[] = [];
  let current: string[] = [];
  points.forEach((p, i) => {
    if (i > 0 && Date.parse(p.t) - Date.parse(points[i - 1].t) > GAP_MS) {
      segments.push(current.join(" "));
      current = [];
    }
    current.push(`${x(p.t).toFixed(1)},${y(p.v).toFixed(1)}`);
  });
  segments.push(current.join(" "));
  const zero = y(0);
  return (
    <svg viewBox={`0 0 ${W} ${H + 18}`} className={css({ width: "100%", height: "auto" })} role="img" aria-label="응급실 빈 병상 수 기록">
      <defs>
        <clipPath id="below-zero">
          <rect x="0" y={zero} width={W} height={H - zero} />
        </clipPath>
      </defs>
      <rect x="0" y={zero} width={W} height={Math.max(H - zero, 0)} fill="#FDECEA" />
      <line x1="0" x2={W} y1={zero} y2={zero} stroke={RED} strokeDasharray="4 3" strokeWidth="1" />
      {segments.map((seg, i) => (
        <g key={i}>
          <polyline points={seg} fill="none" stroke="#1E5FA8" strokeWidth="2" />
          <polyline points={seg} fill="none" stroke={RED} strokeWidth="2.5" clipPath="url(#below-zero)" />
        </g>
      ))}
      <text x={W - 4} y={zero + 13} fontSize="11" fill={RED} textAnchor="end">0석 아래 = 만실·과밀</text>
      <text x="4" y="12" fontSize="11" fill="#55697C">{hi}석</text>
      <text x="0" y={H + 15} fontSize="11" fill="#66778A">{kst(points[0].t)}</text>
      <text x={W} y={H + 15} fontSize="11" fill="#66778A" textAnchor="end">{kst(points[points.length - 1].t)}</text>
    </svg>
  );
}

function StackedBar({ parts }: { parts: { label: string; value: number; color: string }[] }) {
  const total = parts.reduce((s, p) => s + p.value, 0) || 1;
  return (
    <div className={css({ display: "flex", flexDirection: "column", gap: "1.5" })}>
      <div className={css({ display: "flex", height: "18px", borderRadius: "chip", overflow: "hidden" })}>
        {parts.map((p) => (p.value ? <div key={p.label} title={`${p.label} ${p.value}`} style={{ width: `${(p.value / total) * 100}%`, backgroundColor: p.color }} /> : null))}
      </div>
      <div className={css({ display: "flex", flexWrap: "wrap", gap: "3" })}>
        {parts.map((p) => (
          <span key={p.label} className={css({ display: "inline-flex", alignItems: "center", gap: "1.5", fontSize: "xs", color: "ink" })}>
            <span style={{ width: 10, height: 10, borderRadius: 2, backgroundColor: p.color }} />
            {p.label} <b>{p.value}번</b>
          </span>
        ))}
      </div>
    </div>
  );
}

const SEVERE_STYLE: Record<string, { color: string; backgroundColor: string; borderColor: string }> = {
  가능: { color: GREEN, backgroundColor: "#E6F6F0", borderColor: GREEN },
  불가능: { color: RED, backgroundColor: "#FDECEA", borderColor: "#F3B4AF" },
  "정보 없음": { color: "#66778A", backgroundColor: "#F8FAFC", borderColor: "#E2E8EF" },
};

export function HospitalVerifySection({ view, hub }: { view: HospitalView; hub?: HospitalHub | null }) {
  const d = view.departures;
  const departures = d ? d.same + d.changedSmall + d.changedBig + d.becameFull : 0;
  const bad = d ? d.changedBig + d.becameFull : 0;
  const self = hub?.selfInfo;
  const activity = hub?.activity;
  const unknownCount = view.severe.filter((s) => s.egen === "정보 없음").length;

  return (
    <section className={css({ display: "flex", flexDirection: "column", gap: "3" })}>
      <div className={css({ display: "flex", alignItems: "baseline", gap: "2", flexWrap: "wrap" })}>
        <h2 className={css({ fontSize: "lg", fontWeight: "bold", color: "ink" })}>우리 병원 — {view.name ?? view.hospitalId}</h2>
        <span className={smallStyle}>
          {view.emergencyLevel ?? ""} · E-Gen 기록 {view.snapshots}번{view.period && ` (${kst(view.period[0])} ~ ${kst(view.period[1])})`}
        </span>
      </div>

      <div className={css({ display: "grid", gridTemplateColumns: { base: "1fr", lg: "minmax(0, 2fr) minmax(0, 3fr)" }, gap: "3" })}>
        <div className={cardStyle}>
          <span className={css({ fontSize: "sm", fontWeight: "semibold", color: "ink2" })}>
            우리 병원 병상 숫자를 보고 구급차가 출발했다면 ({d?.travelMin ?? 15}분 이동)
          </span>
          {d && departures > 0 ? (
            <>
              <div className={css({ display: "flex", alignItems: "baseline", gap: "2", flexWrap: "wrap" })}>
                <span className={css({ fontSize: "5xl", fontWeight: "bold", lineHeight: "1" })} style={{ color: bad ? RED : GREEN }}>
                  {bad}/{departures}번
                </span>
                <span className={css({ fontSize: "md", fontWeight: "bold", color: "ink" })}>도착 때 {d.theta}석 이상 바뀌었거나 만실</span>
              </div>
              <StackedBar
                parts={[
                  { label: "그대로", value: d.same, color: GRAY },
                  { label: "1~2석", value: d.changedSmall, color: AMBER },
                  { label: `${d.theta}석 이상`, value: d.changedBig, color: RED },
                  { label: "만실", value: d.becameFull, color: DARK },
                ]}
              />
              {d.worst && (
                <span className={noteStyle}>
                  가장 크게 줄어든 때: {kst(d.worst.requestAt)} <b>{d.worst.bedsAtRequest}석</b> → {kst(d.worst.arrivalAt)}{" "}
                  <b style={{ color: d.worst.bedsAtArrival <= 0 ? DARK : RED }}>{d.worst.bedsAtArrival <= 0 ? "만실" : `${d.worst.bedsAtArrival}석`}</b>
                </span>
              )}
              <span className={smallStyle}>빈 병상이 1석 이상 보였던 모든 기록 시각에 출발했다고 치고, 도착 시각의 실제 기록과 비교했습니다.</span>
            </>
          ) : (
            <span className={noteStyle}>빈 병상이 보였던 기록이 아직 없습니다.</span>
          )}
        </div>

        <div className={cardStyle}>
          <span className={headingStyle}>응급실 빈 병상 수 — 실제 기록</span>
          <BedChart points={view.chart} />
          <span className={smallStyle}>선이 끊긴 곳은 수집이 멈췄던 시간입니다.</span>
          {view.rhythm && (
            <span className={noteStyle}>
              기록한 시간의 <b style={{ color: RED }}>{pct(view.rhythm.fullShare)}</b>는 만실이거나 정원보다 환자가 많았습니다(최저 {view.rhythm.minBeds}석 ~ 최고{" "}
              {view.rhythm.maxBeds}석). 수집 {view.snapshots}번 중 {view.rhythm.updates}번 병원이 숫자를 새로 고쳐 두었습니다.
            </span>
          )}
        </div>
      </div>

      <div className={css({ display: "grid", gridTemplateColumns: { base: "1fr", md: "repeat(3, minmax(0, 1fr))" }, gap: "3" })}>
        <div className={cardStyle}>
          <span className={headingStyle}>지금 API에 나가는 우리 병원</span>
          <span className={css({ fontSize: "3xl", fontWeight: "bold", color: "ink" })}>
            {self ? (self.bedCountUnknown ? "미상" : `${self.availableBedCount}석`) : "—"}
          </span>
          <span className={noteStyle}>
            AI가 본 &quot;이 숫자를 지금 믿어도 될 확률&quot; <b>{pct(self?.bedReliability?.authority)}</b>
          </span>
          {view.rhythm?.lastUpdateAgeMin != null && <span className={smallStyle}>마지막 갱신 {Math.round(view.rhythm.lastUpdateAgeMin)}분 전(마지막 수집 기준)</span>}
          <span className={smallStyle}>병원 대시보드 위쪽의 [현재 정보가 맞습니다]를 누르면 이 확률이 다시 올라갑니다.</span>
        </div>

        <div className={cardStyle}>
          <span className={headingStyle}>E-Gen 중증질환 수용 신고</span>
          <div className={css({ display: "flex", flexWrap: "wrap", gap: "1.5" })}>
            {view.severe.map((s) => (
              <span key={s.group} className={css({ fontSize: "xs", paddingX: "1.5", paddingY: "0.5", borderRadius: "chip", borderWidth: "1px" })} style={SEVERE_STYLE[s.egen] ?? SEVERE_STYLE["정보 없음"]}>
                {s.group}
              </span>
            ))}
          </div>
          <span className={smallStyle}>
            초록 가능 · 빨강 불가 · 회색 정보 없음({unknownCount}/{view.severe.length}칸)
          </span>
          {view.designated.length > 0 && (
            <span className={noteStyle}>
              심평원 전문병원 지정:{" "}
              {view.designated.map((x) => (
                <b key={x.field} style={{ color: x.egen === "가능" ? GREEN : RED }}>
                  {x.field}({x.egen === "가능" ? "API에도 가능" : "API엔 안 보임"}){" "}
                </b>
              ))}
            </span>
          )}
          {view.specialists.length > 0 && (
            <span className={smallStyle}>심평원 전문의: {view.specialists.map((s) => `${s.department} ${s.count}명`).join(" · ")}</span>
          )}
        </div>

        <div className={cardStyle}>
          <span className={headingStyle}>골든링크 운영 기록</span>
          {activity ? (
            <span className={noteStyle}>
              이송 요청을 받은 사건 <b>{activity.requestedCases}건</b>
              {activity.counts.map((c) => ` · ${c.label} ${c.count}`).join("")}
            </span>
          ) : (
            <span className={smallStyle}>hub 기록을 불러오지 못했습니다</span>
          )}
          {view.rejections.count > 0 ? (
            <span className={noteStyle}>
              거절·무응답 기록 {view.rejections.count}건: {view.rejections.byReason.map((r) => `${r.label} ${r.count}`).join(" · ")}
            </span>
          ) : (
            <span className={smallStyle}>거절 기록이 아직 없습니다</span>
          )}
          {activity && activity.recent.length > 0 && (
            <div className={css({ display: "flex", flexDirection: "column", gap: "0.5" })}>
              {activity.recent
                .slice()
                .reverse()
                .slice(0, 5)
                .map((r, i) => (
                  <span key={`${r.timestamp}${i}`} className={smallStyle}>
                    {kst(r.timestamp)} · {r.label}
                  </span>
                ))}
            </div>
          )}
          <span className={smallStyle}>시연 중 대시보드에서 누른 기록입니다(시험 기록 포함).</span>
        </div>
      </div>
    </section>
  );
}
