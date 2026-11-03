"use client";

import { useMemo, useState } from "react";
import { C, GLASS } from "@/lib/control-map";
import type { AssignmentCase, AssignmentEvidence, AssignmentGroup } from "@/types/dashboard";

// 상황실 배정 요청 모달(2026-11-04). 여러 사건의 1순위 수용 병원이 같은데 여력이 모자라면 hub(assignment_agent.py)가
// 사건을 묶고 배분 안과 근거를 보낸다. 그동안 구급대원 이송 승인은 hub가 막고, 여기서 관제가 지정한다(dispatcher
// final_approval). 근거는 "환자에게 필요한 것 ↔ 병원이 가진 것"(장비·전문의·등급·병상)이 주인공이고, 줄 길이(분)는
// 순서를 정한 계산으로 함께 보인다. 모두 규칙·공공데이터 값이며 전문의 검토 전 초안이다 — 결정은 관제가 한다.

const EQUIP_LABEL: Record<string, string> = { CT: "CT", ANGIO: "혈관조영", MRI: "MRI", ECMO: "ECMO" };
const LEVEL_SHORT: Record<string, string> = {
  권역응급의료센터: "권역센터", 지역응급의료센터: "지역센터", 지역응급의료기관: "지역기관", 응급실운영신고기관: "신고기관",
};
const STATUS_TEXT: Record<string, [string, string]> = {
  approved: ["수용", "#4E8B1F"], pending: ["판단 대기", "#C75B00"], rejected: ["수용 곤란", "#D93025"], confirmed: ["이송 확정", "#168A55"],
};

const fmtMin = (v: number | null | undefined) => (v == null ? "-" : `${Math.round(v)}분`);
const RISK: Record<string, [string, string]> = { low: ["변동 위험 낮음", "#1E9E6A"], medium: ["변동 위험 보통", "#B7791F"], high: ["변동 위험 높음", "#D9434B"] };
const agoText = (iso: string | null | undefined, now: number) => {
  if (!iso) return null;
  const min = Math.max(0, Math.round((now - Date.parse(iso)) / 60_000));
  return min < 1 ? "방금 확인" : min < 60 ? `${min}분 전 확인` : `${Math.floor(min / 60)}시간 전 확인`;
};
/** 관제가 고를 수 있는 병원 — 수용한 병원, 또는 상황실 지정(수용 회신 전, 확인된 처치 불가 아님) */
const selectableOf = (h: AssignmentEvidence) => h.status === "approved" || (h.status === "pending" && !h.confirmedBlock);

function equipText(v: string | null | undefined) {
  if (v === "Y") return { text: "운영", color: "#4E8B1F" };
  if (v === "N" || v === "N1") return { text: "미운영", color: "#D93025" };
  return { text: "정보 없음", color: C.faint };
}

function Evidence({ h, now }: { h: AssignmentEvidence; now: number }) {
  const beds = h.bedCountUnknown ? "미상" : h.availableBedCount == null ? "-" : `${h.availableBedCount}${h.erBedCapacity ? `/${h.erBedCapacity}` : ""}석`;
  return (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(4, minmax(0, 1fr))", gap: "4px 12px", fontSize: 12, color: C.ink2 }}>
      <span>등급 <b style={{ color: C.navy }}>{(h.emergencyLevel && LEVEL_SHORT[h.emergencyLevel]) ?? h.emergencyLevel ?? "정보 없음"}</b></span>
      <span>응급의학과 <b style={{ color: C.navy }}>{h.emDoctors ?? "-"}명</b></span>
      <span>{h.requiredDepartment ?? "필요 진료과"} <b style={{ color: C.navy }}>{h.requiredDepartment ? `${h.deptDoctors ?? 0}명` : "-"}</b></span>
      <span>응급실 <b style={{ color: C.navy }}>{beds}</b>{h.inFlightCount > 0 ? <span style={{ color: C.orange }}> · 이송 중 {h.inFlightCount}</span> : null}</span>
      {Object.entries(h.equipment).map(([key, v]) => {
        const e = equipText(v);
        return <span key={key}>{EQUIP_LABEL[key] ?? key} <b style={{ color: e.color }}>{e.text}</b></span>;
      })}
      {h.bedRisk && (
        <span style={{ gridColumn: "span 2" }} title="정보 생존 모델(AI)이 본 '이 병상 숫자가 도착까지 유지될지'의 위험 — 수용 확률이 아닙니다">
          병상 정보 <b style={{ color: RISK[h.bedRisk][1] }}>{RISK[h.bedRisk][0]}</b>
          {agoText(h.bedCheckedAt, now) && <span style={{ color: C.sub }}> · {agoText(h.bedCheckedAt, now)}</span>}
          <span style={{ marginLeft: 4, fontSize: 10.5, color: C.blue, fontWeight: 700 }}>AI</span>
        </span>
      )}
      {h.refusalReasons.map((r) => (
        <span key={r} style={{ gridColumn: "1 / -1", color: "#B7791F" }}>학습 반영 · {r}</span>
      ))}
    </div>
  );
}

function LineFormula({ h }: { h: AssignmentEvidence }) {
  if (h.lineMin == null) {
    return <span style={{ color: C.muted }}>줄 없음 · {h.confirmedBlock ?? h.lineBlocked ?? "역량 정보 부족"} → 맨 뒤</span>;
  }
  const gain = h.gainMin ?? 0;
  return (
    <span title="줄 길이(분) = 도로 이동 − 역량 이득 + 부하(이송 중·응급실 포화)">
      <b style={{ color: C.navy }}>{fmtMin(h.lineMin)}</b>
      <span style={{ color: C.sub }}> = 이동 {fmtMin(h.travelMin)} {gain >= 0 ? "−" : "+"} 역량 {fmtMin(Math.abs(gain))} + 부하 {fmtMin(h.loadMin)}</span>
    </span>
  );
}

function CaseCard({ c, chosen, onChoose, onConfirmRequest, now }: {
  c: AssignmentCase; chosen: string | null; onChoose: (hid: string) => void; onConfirmRequest: () => void; now: number;
}) {
  const waiting = c.candidates.filter((h) => h.status === "pending" && !h.confirmedBlock);
  const asked = waiting.filter((h) => h.confirmRequestedAt).length;
  return (
    <section style={{ border: GLASS.border, borderRadius: 14, padding: "14px 16px", background: "#fff", boxShadow: "0 2px 10px rgba(91,75,138,.08)", display: "flex", flexDirection: "column", gap: 8 }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 8, flexWrap: "wrap" }}>
        <span style={{ fontSize: 14, fontWeight: 900, color: C.navy }}>{c.ambulanceName ?? c.caseId}</span>
        {c.ktasLevel != null && <span style={{ fontSize: 12, fontWeight: 700, color: "#fff", background: c.ktasLevel <= 2 ? "#D93025" : c.ktasLevel === 3 ? "#F26B1D" : "#4E8B1F", borderRadius: 3, padding: "0 6px" }}>Pre-KTAS {c.ktasLevel}</span>}
        <span style={{ fontSize: 13, color: C.ink2 }}>{c.chiefComplaint ?? c.expectedDiagnosis ?? ""}</span>
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 10, fontSize: 12.5, color: c.proposedHospitalId ? C.navy : "#B3261E", background: GLASS.tint, borderRadius: GLASS.radiusSm, padding: "7px 12px" }}>
        <span style={{ flex: 1, whiteSpace: "normal" }}>에이전트 제안 · {c.reason}</span>
        {waiting.length > 0 && (
          <button type="button" onClick={onConfirmRequest} title="수용 회신이 없는 병원 화면에 '상황실 수용 확인 요청'을 다시 띄웁니다"
            style={{ flex: "none", fontFamily: "inherit", fontSize: 12, fontWeight: 700, color: C.blue, background: "#fff", border: `1px solid ${C.blue}`, borderRadius: 999, padding: "3px 12px", cursor: "pointer" }}>
            수용 확인 요청 {asked > 0 ? `(${asked}/${waiting.length} 요청함)` : `· ${waiting.length}곳`}
          </button>
        )}
      </div>
      <div role="radiogroup" aria-label={`${c.ambulanceName ?? c.caseId} 배정 병원`} style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        {c.candidates.map((h) => {
          const selectable = selectableOf(h);
          const designation = h.status === "pending";
          const on = chosen === h.hospitalId;
          const [stText, stColor] = STATUS_TEXT[h.status] ?? [h.status, C.sub];
          return (
            <label key={h.hospitalId} style={{
              display: "flex", gap: 10, alignItems: "flex-start", border: `1px solid ${on ? C.blue : C.line2}`, background: on ? GLASS.tint : "#fff",
              borderRadius: GLASS.radiusSm, padding: "9px 12px", cursor: selectable ? "pointer" : "default", opacity: selectable ? 1 : 0.7,
            }}>
              <input type="radio" name={`assign-${c.caseId}`} checked={on} disabled={!selectable} onChange={() => onChoose(h.hospitalId)} style={{ marginTop: 3 }} />
              <div style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column", gap: 5 }}>
                <div style={{ display: "flex", alignItems: "baseline", gap: 8, flexWrap: "wrap" }}>
                  <span style={{ fontSize: 13.5, fontWeight: 700, color: C.navy }}>{h.name}</span>
                  {c.proposedHospitalId === h.hospitalId && <span style={{ fontSize: 11, fontWeight: 900, color: "#fff", background: C.blue, borderRadius: 3, padding: "0 6px" }}>추천</span>}
                  <span style={{ fontSize: 12, fontWeight: 700, color: stColor }}>{stText}{h.rejectReason ? ` · ${h.rejectReason}` : ""}</span>
                  <span style={{ marginLeft: "auto", fontSize: 12 }}><LineFormula h={h} /></span>
                </div>
                <Evidence h={h} now={now} />
                {designation && selectable && (
                  <div style={{ fontSize: 11.5, color: "#B7791F" }}>
                    수용 회신 전 — 고르면 <b>상황실 지정</b>으로 확정되고 병원에 지정 통보가 갑니다{h.confirmRequestedAt ? ` · 수용 확인 요청함(${agoText(h.confirmRequestedAt, now)?.replace(" 확인", "")})` : ""}
                  </div>
                )}
              </div>
            </label>
          );
        })}
      </div>
    </section>
  );
}

export function AssignmentModal({ groups, onClose, onDispatch, onConfirmRequest, now }: {
  groups: AssignmentGroup[];
  onClose: () => void;
  onDispatch: (caseId: string, hospitalId: string) => void;
  onConfirmRequest: (caseId: string) => void;
  now: number;
}) {
  // 사건별 관제 선택 — 기본은 에이전트 제안. 고른 병원이 더는 수용 상태가 아니면(수용 곤란으로 번복 등) 새 제안으로 돌아간다.
  const [picked, setPicked] = useState<Record<string, string>>({});
  const cases = useMemo(() => groups.flatMap((g) => g.proposal.cases), [groups]);
  const choiceOf = (c: AssignmentCase) => {
    const mine = picked[c.caseId];
    return mine && c.candidates.some((h) => h.hospitalId === mine && selectableOf(h)) ? mine : c.proposedHospitalId;
  };
  const ready = cases.filter((c) => choiceOf(c));
  const followed = ready.filter((c) => choiceOf(c) === c.proposedHospitalId).length;
  const designations = ready.filter((c) => c.candidates.find((h) => h.hospitalId === choiceOf(c))?.status === "pending").length;
  const opened = groups.map((g) => g.openedAt).filter(Boolean).sort()[0];
  const waitMin = opened ? Math.max(0, Math.floor((now - Date.parse(opened)) / 60_000)) : null;

  return (
    <div role="dialog" aria-modal="true" aria-label="상황실 배정 요청" style={{ position: "absolute", inset: 0, zIndex: 320, background: "rgba(28,31,42,.32)", backdropFilter: "blur(6px)", display: "flex", alignItems: "center", justifyContent: "center" }}>
      <button type="button" aria-label="나중에" onClick={onClose} style={{ position: "absolute", inset: 0, border: 0, background: "transparent", cursor: "default" }} />
      <div style={{ position: "relative", width: 860, maxHeight: "calc(100% - 48px)", maxWidth: "calc(100% - 32px)", background: GLASS.solid, border: GLASS.border, borderRadius: GLASS.radius, boxShadow: "0 24px 60px rgba(91,75,138,.28)", fontFamily: GLASS.font, display: "flex", flexDirection: "column", overflow: "hidden" }}>
        <div style={{ flex: "none", display: "flex", alignItems: "center", gap: 10, padding: "16px 22px", borderBottom: `1px solid ${C.line2}` }}>
          <div style={{ fontSize: 18, fontWeight: 900, color: C.navy }}>상황실 배정 요청</div>
          <span style={{ fontSize: 12, fontWeight: 700, color: "#fff", background: "#D93025", borderRadius: 999, padding: "1px 10px" }}>
            {cases.length}건 · 관제 판단 대기{waitMin != null ? ` ${waitMin}분째` : ""}
          </span>
          <span title="생성형 AI가 아니라 규칙 기반 계산입니다. 가중치는 전문의 검토 전 초안입니다." style={{ fontSize: 11.5, color: C.sub, border: `1px solid ${C.line}`, borderRadius: 3, padding: "1px 6px" }}>규칙 기반 · 전문의 검토 전 초안</span>
          <div style={{ flex: 1 }} />
          <button type="button" onClick={onClose} style={{ fontFamily: "inherit", fontSize: 13, color: C.ink3, background: "#fff", border: `1px solid ${C.line}`, borderRadius: 4, padding: "5px 12px", cursor: "pointer" }}>나중에 ✕</button>
        </div>

        <div style={{ padding: "14px 22px", overflowY: "auto", display: "flex", flexDirection: "column", gap: 14 }}>
          {groups.map((g) => {
            const naive = g.caseIds.length;
            const toConflict = g.proposal.cases.filter((c) => c.proposedHospitalId === g.hospitalId).length;
            return (
              <div key={g.hospitalId} style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                <div style={{ fontSize: 13.5, color: C.ink, lineHeight: 1.6 }}>
                  <b style={{ color: C.navy }}>{g.hospitalName ?? g.hospitalId}</b>이(가) 환자 {naive}명의 1순위 수용 병원인데 여력이{" "}
                  <b style={{ color: "#D93025" }}>{g.capacityKnown ? `${g.capacity}석` : "미상"}</b>입니다.
                  <div style={{ fontSize: 12.5, color: C.sub }}>
                    각자 정하면 {naive}명 모두 이 병원으로 · 함께 정하면 이 병원 {toConflict}명, 나머지 {naive - toConflict}명은 다른 수용 병원으로
                  </div>
                </div>
                {g.proposal.cases.map((c) => (
                  <CaseCard key={c.caseId} c={c} now={now} chosen={choiceOf(c)} onConfirmRequest={() => onConfirmRequest(c.caseId)}
                    onChoose={(hid) => setPicked((p) => ({ ...p, [c.caseId]: hid }))} />
                ))}
              </div>
            );
          })}
          {cases.length === 0 && <div style={{ fontSize: 13, color: C.sub }}>지금 관제가 정해야 할 충돌이 없습니다.</div>}
        </div>

        <div style={{ flex: "none", display: "flex", alignItems: "center", gap: 10, padding: "12px 22px", borderTop: `1px solid ${C.line2}`, background: "rgba(244,242,250,.7)" }}>
          <div style={{ fontSize: 12, color: C.sub, flex: 1 }}>
            지정하면 구급대원 화면에 알려지고 이송이 확정됩니다. 수용 회신 전 병원은 상황실 지정으로 확정되고 병원에 통보됩니다.
            {ready.length > 0 && ` 제안 그대로 ${followed}건 · 변경 ${ready.length - followed}건`}
            {designations > 0 && ` · 상황실 지정 ${designations}건`}
          </div>
          <button
            type="button"
            disabled={ready.length === 0}
            onClick={() => { for (const c of ready) onDispatch(c.caseId, choiceOf(c) as string); }}
            style={{ fontFamily: "inherit", fontSize: 14, fontWeight: 900, color: "#fff", background: ready.length ? C.blue : C.faint, border: 0, borderRadius: 999, padding: "9px 18px", cursor: ready.length ? "pointer" : "default" }}
          >
            {ready.length === cases.length ? `배분 안대로 지정 (${ready.length}건)` : `지정 가능한 ${ready.length}건 지정`}
          </button>
        </div>
      </div>
    </div>
  );
}
