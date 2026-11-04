"use client";

import { C, GLASS, ST_TEXT, fmtClock, reqLabel, shortAmb, shortHospital, type Incident } from "@/lib/control-map";
import { CaseStatusSummary } from "@/components/map/CaseStatusSummary";
import { CaseTimeline } from "@/components/map/CaseTimeline";
import { rejectionReasonLabel } from "@/lib/rejection";
import type { AssignmentGroup, MonitorCase } from "@/types/dashboard";

// 관제 사건 상세(2026-11-04) — 진행 중인 사건을 누르면 왼쪽에 뜬다.
// ① 환자 정보(구급대원 휴대폰의 온디바이스 AI가 정리해 보낸 것 — 통화 전문·활력징후는 관제로 오지 않는다)
// ② 지금 진행 상황 ③ AI 에이전트 활동(인식 → 판단 → 행동 → 학습, 단계마다 AI/규칙 구분) ④ 병원 응답과 관제 조치
// ⑤ 기록(진행 과정). 새 계산 없이 hub가 이미 보낸 사건 요약(case_overview)·배정 묶음에서만 만든다.

const MOMENTARY = new Set(["BEDS_FULL", "OR_OCCUPIED", "STAFF_BUSY"]);
const STRUCTURAL = new Set(["NO_WARD", "NO_DEPARTMENT", "NO_EQUIPMENT"]);
const OMIT_LABEL: Record<string, string> = { recent_severe_block: "최근 차단 공지(첫 전송 보류)" };
const STAGE_COLOR: Record<string, string> = { 인식: "#5AA9E6", 판단: "#6B5BD2", 행동: "#F5B942", 학습: "#1E9E6A" };

interface Step { stage: "인식" | "판단" | "행동" | "학습"; source: "ai" | "rule"; where?: string; text: string }

function agentSteps(inc: Incident, mc: MonitorCase | undefined, group: AssignmentGroup | undefined): Step[] {
  const steps: Step[] = [];
  const hs = mc?.hospitals ?? [];
  if (mc?.ktasLevel != null || mc?.expectedDiagnosis) {
    steps.push({ stage: "인식", source: "ai", where: "구급대원 휴대폰", text:
      `통화를 환자 정보로 정리해 수신 — 원본 음성은 휴대폰 밖으로 나가지 않음 · ${mc?.confirmedBy === "paramedic" ? "구급대원 확인 완료" : "구급대원 확인 전"}` });
  }
  const withRisk = hs.filter((h) => h.bedReliability);
  if (withRisk.length) {
    const high = withRisk.filter((h) => h.bedReliability?.riskLevel === "high").length;
    steps.push({ stage: "인식", source: "ai", where: "서버", text:
      `후보 병원 ${withRisk.length}곳의 병상 정보가 도착까지 유지될지 계산(정보 생존 모델)${high ? ` · 변동 위험 높음 ${high}곳` : ""}` });
  }
  const policy = mc?.dispatchPolicy as { consideredCount?: number; targetCount?: number; omitted?: { reason: string | null }[] } | null | undefined;
  if (policy?.consideredCount != null) {
    const omitted = (policy.omitted ?? []).reduce<Record<string, number>>((acc, o) => {
      const k = (o.reason && (OMIT_LABEL[o.reason] ?? o.reason)) || "기타";
      acc[k] = (acc[k] ?? 0) + 1;
      return acc;
    }, {});
    const omittedText = Object.entries(omitted).map(([k, n]) => `${k} ${n}곳`).join(", ");
    steps.push({ stage: "판단", source: "rule", text:
      `후보 ${policy.consideredCount}곳 → 필수 조건 통과 ${policy.targetCount}곳${omittedText ? ` (제외: ${omittedText})` : ""} · 정보가 없거나 역량이 모자라면 빼지 않고 뒤로` });
  }
  const top = hs.find((h) => h.status === "approved" && !h.notSelected) ?? hs[0];
  if (top) steps.push({ stage: "판단", source: "rule", text: `줄 길이(분 = 이동 − 역량 이득 + 부하) 최단: ${shortHospital(top.name)}` });
  if (group) {
    steps.push({ stage: "판단", source: "rule", text:
      `충돌 감지 — ${group.hospitalName ?? "같은 병원"}이(가) 환자 ${group.caseIds.length}명의 1순위인데 여력 ${group.capacityKnown ? `${group.capacity}석` : "미상"} → 배분 안을 상황실에 제출` });
  }
  if (inc.matched) {
    const a = inc.hospitals.filter((h) => h.st === "a" || h.st === "t").length;
    const r = inc.hospitals.filter((h) => h.st === "r").length;
    const w = inc.hospitals.filter((h) => h.st === "w").length;
    steps.push({ stage: "행동", source: "rule", text: `${inc.hospitals.length}곳에 동시 수용 요청 · 수용 ${a} · 곤란 ${r} · 대기 ${w}${inc.zone > 1 ? ` · 범위 존 1~${inc.zone}로 확장` : ""}` });
  }
  if (group) steps.push({ stage: "행동", source: "rule", text: "구급대 이송 승인을 잠그고 관제 판단 대기 — 결정은 상황실" });
  for (const h of hs) {
    if (h.status === "rejected" && h.rejectReason && MOMENTARY.has(h.rejectReason)) {
      steps.push({ stage: "학습", source: "rule", text: `${shortHospital(h.name)} ${rejectionReasonLabel(h.rejectReason)} → 다른 사건 배정에 30분 반영(+15분)` });
    } else if (h.status === "rejected" && h.rejectReason && STRUCTURAL.has(h.rejectReason)) {
      steps.push({ stage: "학습", source: "rule", text: `${shortHospital(h.name)} ${rejectionReasonLabel(h.rejectReason)} → 같은 질환군 환자에게 24시간 뒤로` });
    }
    for (const reason of h.refusalReasons ?? []) {
      steps.push({ stage: "학습", source: "rule", text: `${shortHospital(h.name)}: ${reason}` });
    }
  }
  return steps;
}

export function CaseDetailPanel({ inc, mc, group, now, onConfirmRequest, onZoneExpand, onDesignate, onOpenHospital }: {
  inc: Incident;
  mc: MonitorCase | undefined;
  group: AssignmentGroup | undefined;
  now: number;
  onConfirmRequest: (caseId: string) => void;
  onZoneExpand: (caseId: string) => void;
  onDesignate: (caseId: string, hospitalId: string) => void;
  onOpenHospital?: (hospitalId: string) => void;
}) {
  const confirmed = inc.hospitals.some((h) => h.st === "t");
  const waiting = inc.hospitals.filter((h) => h.st === "w").length;
  const RANK = { t: 0, a: 1, w: 2, r: 3 } as const;
  const rows = [...inc.hospitals].sort((x, y) => RANK[x.st] - RANK[y.st] || x.km - y.km);
  const explain = new Map((mc?.hospitals ?? []).map((h) => [h.hospitalId, h]));
  const steps = agentSteps(inc, mc, group);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12, minHeight: 0, whiteSpace: "normal" }}>
      {/* 환자 정보 */}
      <section style={secStyle}>
        <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
          <span style={{ fontSize: 15, fontWeight: 900, color: C.navy }}>#{inc.num} {shortAmb(inc.name)}</span>
          {mc?.ktasLevel != null && <span style={{ ...pill, color: "#fff", background: mc.ktasLevel <= 2 ? "#D9434B" : mc.ktasLevel === 3 ? "#F26B1D" : "#1E9E6A" }}>Pre-KTAS {mc.ktasLevel}</span>}
          {group && <span style={{ ...pill, color: "#fff", background: "#D9434B" }}>관제 판단 대기</span>}
          <span style={{ marginLeft: "auto", ...pill, color: C.blue, background: GLASS.tint }} title="구급대원 휴대폰 안의 AI가 통화에서 정리한 값 — 관제는 결과만 받는다">휴대폰 AI 정리</span>
        </div>
        <dl style={{ display: "grid", gridTemplateColumns: "76px 1fr", gap: "4px 8px", margin: 0, fontSize: 12.5 }}>
          <dt style={dt}>주 호소</dt><dd style={dd}>{mc?.chiefComplaint ?? inc.sym ?? "-"}</dd>
          <dt style={dt}>예상 병명</dt><dd style={dd}>{mc?.expectedDiagnosis ?? "-"}</dd>
          <dt style={dt}>환자</dt><dd style={dd}>{mc?.patient ?? "-"}</dd>
          <dt style={dt}>필요 진료과</dt><dd style={dd}>{mc?.requiredDepartment ?? "-"}</dd>
          <dt style={dt}>확인</dt>
          <dd style={{ ...dd, color: mc?.confirmedBy === "paramedic" ? "#1E9E6A" : "#B7791F", fontWeight: 700 }}>
            {mc?.confirmedBy === "paramedic" ? "✓ 구급대원 확인" : "AI 요약 · 구급대원 확인 전"}
          </dd>
        </dl>
        <div style={{ fontSize: 11, color: C.muted }}>통화 전문·활력징후는 관제로 보내지 않습니다(요청받은 병원만 봅니다).</div>
      </section>

      {/* 지금 진행 상황 */}
      <CaseStatusSummary inc={inc} now={now} />

      {/* AI 에이전트 활동 */}
      <section style={secStyle}>
        <div style={{ display: "flex", alignItems: "baseline", gap: 6 }}>
          <span style={{ fontSize: 13.5, fontWeight: 900, color: C.navy }}>AI 에이전트 활동</span>
          <span style={{ fontSize: 11, color: C.sub }}>인식 → 판단 → 행동 → 학습</span>
        </div>
        <ol style={{ listStyle: "none", margin: 0, padding: 0, display: "flex", flexDirection: "column", gap: 5 }}>
          {steps.map((s, i) => (
            <li key={i} style={{ display: "grid", gridTemplateColumns: "40px 1fr", gap: 8, alignItems: "start", fontSize: 12, color: C.ink2 }}>
              <span style={{ ...pill, textAlign: "center", color: "#fff", background: STAGE_COLOR[s.stage] }}>{s.stage}</span>
              <span>
                {s.text}{" "}
                <span style={{ fontSize: 10.5, fontWeight: 700, color: s.source === "ai" ? C.blue : C.muted }}>
                  {s.source === "ai" ? `AI${s.where ? `·${s.where}` : ""}` : "규칙"}
                </span>
              </span>
            </li>
          ))}
          {steps.length === 0 && <li style={{ fontSize: 12, color: C.muted }}>통화 요약이 오면 에이전트가 일을 시작합니다.</li>}
        </ol>
      </section>

      {/* 병원 응답 · 관제 조치 */}
      <section style={secStyle}>
        <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
          <span style={{ fontSize: 13.5, fontWeight: 900, color: C.navy }}>병원 응답 {inc.hospitals.length}곳</span>
          {!confirmed && inc.matched && (
            <span style={{ marginLeft: "auto", display: "flex", gap: 6 }}>
              {waiting > 0 && <button type="button" onClick={() => onConfirmRequest(inc.caseId)} style={actBtn}>수용 확인 요청 · {waiting}곳</button>}
              <button type="button" onClick={() => onZoneExpand(inc.caseId)} style={actBtn}>범위 넓히기</button>
            </span>
          )}
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          {rows.map((h) => {
            const ex = explain.get(h.hospitalId);
            const risk = ex?.bedReliability?.riskLevel;
            return (
              <div key={h.hospitalId} style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12, padding: "5px 8px", borderRadius: GLASS.radiusSm, background: "rgba(255,255,255,.62)", border: `1px solid ${C.line2}` }}>
                <span style={{ flex: 1, minWidth: 0 }}>
                  <button type="button" onClick={() => onOpenHospital?.(h.hospitalId)} title={`${h.name} — 눌러서 병원 상세`}
                    style={{ fontFamily: "inherit", fontSize: 12, fontWeight: 700, color: C.navy, background: "none", border: 0, padding: 0, cursor: "pointer", textDecoration: "underline", textDecorationColor: C.line, textUnderlineOffset: 3 }}>
                    {shortHospital(h.name)}
                  </button>
                  <span style={{ color: C.sub }}> · {h.km.toFixed(1)}km</span>
                  {risk && <span style={{ color: risk === "high" ? "#D9434B" : risk === "medium" ? "#B7791F" : "#1E9E6A" }}> · 병상 변동 {risk === "high" ? "높음" : risk === "medium" ? "보통" : "낮음"}</span>}
                  {h.reason && <div style={{ fontSize: 11, color: "#D9434B" }}>사유 · {h.reason}</div>}
                </span>
                <span style={{ flex: "none", fontWeight: 700, color: ST_TEXT[h.st] }}>{reqLabel(h)}</span>
                <span style={{ flex: "none", width: 40, textAlign: "right", color: C.muted }}>{h.respondedAt ? fmtClock(Date.parse(h.respondedAt)) : ""}</span>
                {!confirmed && (h.st === "a" || (h.st === "w" && !h.bedsFull)) && (
                  <button type="button" onClick={() => onDesignate(inc.caseId, h.hospitalId)}
                    title={h.st === "w" ? "수용 회신 전 — 상황실 지정으로 확정하고 병원에 통보합니다" : "이 병원으로 이송을 확정합니다"}
                    style={{ ...actBtn, padding: "1px 8px", fontSize: 11 }}>{h.st === "w" ? "상황실 지정" : "지정"}</button>
                )}
              </div>
            );
          })}
          {!inc.matched && <div style={{ fontSize: 12, color: C.muted }}>현장 확인이 끝나면 인근 병원에 수용 요청이 나갑니다.</div>}
        </div>
      </section>

      {/* 기록 */}
      <CaseTimeline inc={inc} now={now} />
    </div>
  );
}

const secStyle: React.CSSProperties = {
  display: "flex", flexDirection: "column", gap: 8, padding: "10px 12px", borderRadius: 14,
  background: "rgba(255,255,255,.62)", border: GLASS.border,
};
const pill: React.CSSProperties = { fontSize: 11, fontWeight: 700, borderRadius: 999, padding: "1px 8px", lineHeight: "17px" };
const dt: React.CSSProperties = { color: C.sub };
const dd: React.CSSProperties = { margin: 0, color: C.ink, fontWeight: 600 };
const actBtn: React.CSSProperties = {
  fontFamily: "inherit", fontSize: 11.5, fontWeight: 700, color: C.blue, background: "#fff", border: `1px solid ${C.blue}`,
  borderRadius: 999, padding: "2px 10px", cursor: "pointer",
};
