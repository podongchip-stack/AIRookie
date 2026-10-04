"use client";

import { useEffect, useRef, useState } from "react";
import { css, cx } from "styled-system/css";
import { thinScrollbarStyle } from "@/components/ui/scrollbar-style";
import { FollowupCallBox } from "@/components/panels/FollowupCallBox";
import type { PatientInfo, TransportAssessment, TransportTier, VitalObservationIn } from "@/types/dashboard";

const SOURCE_LABEL: Record<string, string> = { voice: "2차 통화", demo: "가상", manual: "수기", monitor: "모니터" };

// 이송 중 모니터링 패널 (2.5단계, 2026-10-04). 이송 확정 뒤에 뜬다.
//
// 활력징후 "입력 구멍"의 데모 어댑터다 — 실제 기기는 사지 않으므로(설계 원칙),
// 시연에서는 미리 만든 가상 시나리오 5종 중 하나를 골라 측정값 흐름을 hub로
// 흘려보낸다(transport_vitals, demo: true). 판정(NEWS2 + 규칙표, 규칙 기반)은
// 전부 hub의 transport_triage.py가 하고, 이 패널은 결과(transport_assessment)를
// 표시만 한다 — 같은 시나리오는 항상 같은 결과가 나온다(엔진이 결정적).
//
// 시나리오 걸음 수·수치는 hub/test_transport_triage.py의 픽스처와 같다 —
// 화면에서 트는 시연과 테스트가 같은 입력을 쓰도록 한 곳(여기)과 테스트가
// 서로를 검증한다. 바꿀 땐 같이 바꾼다.

type ScenarioStep = Omit<VitalObservationIn, "measuredAt" | "source">;

// 시연 통제 콘솔(/control)도 같은 시나리오를 재생하므로 export — 수치를 바꿀 땐
// hub/test_transport_triage.py 픽스처와 함께 바꾼다.
export const SCENARIOS: { key: string; label: string; expects: string; steps: ScenarioStep[] }[] = [
  {
    key: "stable",
    label: "① 안정적인 경증",
    expects: "기록만 — 쓸데없이 알리지 않음",
    steps: [
      { rr: 16, spo2: 98, sbp: 120, hr: 80, bt: 36.5, avpu: "A" },
      { rr: 15, spo2: 98, sbp: 118, hr: 82, bt: 36.6, avpu: "A" },
      { rr: 16, spo2: 97, sbp: 121, hr: 79, bt: 36.5, avpu: "A" },
    ],
  },
  {
    key: "shock",
    label: "② 이송 중 쇼크 진행",
    expects: "연속 2회 확인 뒤 도착 병원에 자동 전달",
    steps: [
      { rr: 18, spo2: 97, sbp: 115, hr: 95, avpu: "A" },
      { rr: 20, spo2: 96, sbp: 100, hr: 115, avpu: "A" },
      { rr: 20, spo2: 96, sbp: 98, hr: 118, avpu: "A" },
    ],
  },
  {
    key: "mismatch",
    label: "③ 흉통 악화 — 목적지 부적합",
    expects: "대체 병원 후보 제안 (결정은 사람)",
    steps: [
      { rr: 22, spo2: 94, sbp: 100, hr: 105, avpu: "A" },
      { rr: 24, spo2: 92, sbp: 95, hr: 130, avpu: "A" },
    ],
  },
  {
    key: "consciousness",
    label: "④ 의식 저하",
    expects: "NEWS2 응급 수준 — 1회로 즉시 (대체 없으면 헬기 권고)",
    steps: [
      { rr: 14, spo2: 96, sbp: 125, hr: 88, avpu: "A" },
      { rr: 8, spo2: 90, sbp: 125, hr: 88, avpu: "P" },
    ],
  },
  {
    key: "spike",
    label: "⑤ 측정값 일시적 튐",
    expects: "경보 안 함 — 오경보를 걸러냄",
    steps: [
      { rr: 16, spo2: 97, sbp: 120, hr: 85, avpu: "A" },
      { rr: 16, spo2: 97, sbp: 110, hr: 116, avpu: "A" },
      { rr: 16, spo2: 97, sbp: 120, hr: 85, avpu: "A" },
    ],
  },
];

//: 시나리오 걸음 간격(ms) — 시연에서 측정이 들어오는 리듬
export const STEP_INTERVAL_MS = 4000;

export const TIER_LABEL: Record<TransportTier, string> = {
  record: "기록",
  hold: "보류 · 지속 확인 중",
  notify: "상태 변화 전달됨",
  review: "대체 병원 제안",
  heli_advisory: "헬기 대기 권고",
};

// 티어 톤: 기록·보류는 조용히(회색), 전달은 amber, 재검토·헬기는 coral.
const tierChipStyle = (tier: TransportTier) =>
  css({
    display: "inline-flex",
    alignItems: "center",
    fontSize: "xs",
    fontWeight: "bold",
    paddingX: "2",
    paddingY: "0.5",
    borderRadius: "chip",
    color: tier === "record" || tier === "hold" ? "ink2" : tier === "notify" ? "severity.medium" : "coral",
    backgroundColor:
      tier === "record" || tier === "hold" ? "surfaceSub" : tier === "notify" ? "severity.medium.subtle" : "coralSoft",
  });

const panelStyle = css({
  display: "flex",
  flexDirection: "column",
  gap: "2.5",
  padding: "4",
  borderRadius: "panel",
  borderWidth: "1px",
  borderColor: "line",
  backgroundColor: "surface",
});

const scenarioButtonStyle = css({
  textAlign: "left",
  fontSize: "xs",
  fontWeight: "semibold",
  color: "ink",
  paddingX: "2.5",
  paddingY: "1.5",
  borderRadius: "field",
  borderWidth: "1px",
  borderColor: "line",
  backgroundColor: "surfaceSub",
  cursor: "pointer",
  _hover: { borderColor: "navy" },
  _disabled: { opacity: 0.5, cursor: "not-allowed" },
});

export function TransportMonitorPanel({
  caseId,
  apid,
  assessments,
  live,
  onSendVitals,
  patientInfo = null,
}: {
  // 이송 중 2차 통화로 갱신된 환자 정보(2026-10-05) — 있으면 패널 위쪽에 바뀐 점을 보여준다
  patientInfo?: PatientInfo | null;
  caseId: string;
  apid: string;
  assessments: TransportAssessment[];
  // hub 실시간 연결 여부 — mock 모드엔 판정 엔진이 없어 안내만 띄운다
  live: boolean;
  onSendVitals: (
    caseId: string,
    apid: string,
    observation: VitalObservationIn,
    extra?: { demo?: boolean; scenario?: string },
  ) => boolean;
}) {
  const [playing, setPlaying] = useState<string | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const stepRef = useRef(0);

  // 사건이 바뀌면(재선택·새 출동) 진행 중이던 시나리오를 멈춘다
  useEffect(() => stop, [caseId]); // eslint-disable-line react-hooks/exhaustive-deps

  function stop() {
    if (timerRef.current) clearInterval(timerRef.current);
    timerRef.current = null;
    stepRef.current = 0;
    setPlaying(null);
  }

  function play(key: string) {
    const scenario = SCENARIOS.find((s) => s.key === key);
    if (!scenario) return;
    stop();
    setPlaying(key);
    const send = () => {
      const step = scenario.steps[stepRef.current];
      if (!step) {
        stop();
        return;
      }
      stepRef.current += 1;
      onSendVitals(
        caseId,
        apid,
        { ...step, measuredAt: new Date().toISOString(), source: "demo" },
        { demo: true, scenario: scenario.key },
      );
    };
    send(); // 첫 측정은 바로
    timerRef.current = setInterval(send, STEP_INTERVAL_MS);
  }

  const latest = assessments[assessments.length - 1] ?? null;

  return (
    <section className={panelStyle}>
      <header className={css({ display: "flex", alignItems: "center", gap: "2", flexWrap: "wrap" })}>
        <h2 className={css({ fontSize: "sm", fontWeight: "bold", color: "ink" })}>이송 중 모니터링</h2>
        <span className={css({ fontSize: "xs", color: "ink2" })}>규칙 기반 · NEWS2 + 규칙표</span>
        <span
          className={css({
            marginLeft: "auto",
            fontSize: "xs",
            fontWeight: "bold",
            color: "severity.medium",
            backgroundColor: "severity.medium.subtle",
            paddingX: "2",
            paddingY: "0.5",
            borderRadius: "chip",
          })}
        >
          가상 시나리오
        </span>
      </header>

      {/* 이송 중 2차 통화 — 통화로 읽은 활력징후는 hub가 이 모니터링(NEWS2)에 측정 1회(출처: 2차 통화)로 넣는다 */}
      <FollowupCallBox patientInfo={patientInfo} compact />

      {/* 시나리오 선택 — 활력징후 입력 구멍의 데모 어댑터. 실제 운영에선 이 자리에
          재통화·차량 내 음성·구급차 모니터가 같은 형식으로 꽂힌다. */}
      <div className={css({ display: "flex", flexDirection: "column", gap: "1" })}>
        {SCENARIOS.map((s) => (
          <button
            key={s.key}
            type="button"
            className={scenarioButtonStyle}
            disabled={playing !== null && playing !== s.key}
            onClick={() => (playing === s.key ? stop() : play(s.key))}
          >
            {playing === s.key ? "⏹ " : "▶ "}
            {s.label}
            <span className={css({ display: "block", fontWeight: "normal", color: "ink2" })}>{s.expects}</span>
          </button>
        ))}
      </div>

      {!live && (
        <p className={css({ fontSize: "xs", color: "ink2" })}>
          판정 결과는 hub 연결(실시간 연동) 상태에서 표시됩니다 — 목데이터 모드에는 규칙 엔진이 없습니다.
        </p>
      )}

      {latest && (
        <div className={css({ display: "flex", flexDirection: "column", gap: "1.5" })}>
          <div className={css({ display: "flex", alignItems: "center", gap: "2", flexWrap: "wrap" })}>
            <span className={tierChipStyle(latest.tier)}>{TIER_LABEL[latest.tier]}</span>
            <span className={css({ fontSize: "sm", fontWeight: "bold", color: "ink" })}>NEWS2 {latest.news2}</span>
            <span className={css({ fontSize: "xs", color: "ink2" })}>측정 출처: {SOURCE_LABEL[latest.observation.source] ?? latest.observation.source}</span>
            {latest.si != null && (
              <span className={css({ fontSize: "xs", color: "ink2" })}>쇼크지수 {latest.si}</span>
            )}
          </div>
          {latest.reasons.length > 0 && (
            <ul className={css({ fontSize: "xs", color: "ink2", paddingLeft: "4", listStyleType: "disc" })}>
              {latest.reasons.map((reason) => (
                <li key={reason}>{reason}</li>
              ))}
            </ul>
          )}
          {latest.alternatives.length > 0 && (
            <div
              className={css({
                borderWidth: "1px",
                borderColor: "coral",
                borderRadius: "field",
                padding: "2.5",
                display: "flex",
                flexDirection: "column",
                gap: "1",
              })}
            >
              <p className={css({ fontSize: "xs", fontWeight: "bold", color: "coral" })}>
                대체 병원 후보 — 제안일 뿐, 변경 결정은 구급대원·관제가 합니다
              </p>
              {latest.alternatives.map((alt) => (
                <p key={alt.hospitalId} className={css({ fontSize: "xs", color: "ink" })}>
                  {alt.name} · {alt.travelMin != null ? `${alt.travelMin}분` : "시간 미상"} ·{" "}
                  {alt.bedCountUnknown ? "병상 미상" : `병상 ${alt.availableBedCount}석`}
                  {alt.rArrive != null ? ` · 도착 시 유효 ${Math.round(alt.rArrive * 100)}%` : ""}
                </p>
              ))}
            </div>
          )}
        </div>
      )}

      {/* 측정 이력 — 시간순 추세. 모든 변동은 이송 후(3단계) 기록과 이어진다. */}
      {assessments.length > 1 && (
        <div
          className={cx(
            css({ maxHeight: "120px", overflowY: "auto", display: "flex", flexDirection: "column", gap: "0.5" }),
            thinScrollbarStyle,
          )}
        >
          {assessments.map((a, i) => (
            <p key={`${a.timestamp}-${i}`} className={css({ fontSize: "xs", color: "ink2" })}>
              {a.observation.measuredAt.slice(11, 19)} · NEWS2 {a.news2}
              {a.si != null ? ` · SI ${a.si}` : ""} · {TIER_LABEL[a.tier]} · {SOURCE_LABEL[a.observation.source] ?? a.observation.source}
            </p>
          ))}
        </div>
      )}
    </section>
  );
}
