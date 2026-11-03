"use client";

import { useMemo, useState } from "react";
import { C } from "@/lib/control-map";
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

function equipText(v: string | null | undefined) {
  if (v === "Y") return { text: "운영", color: "#4E8B1F" };
  if (v === "N" || v === "N1") return { text: "미운영", color: "#D93025" };
  return { text: "정보 없음", color: C.faint };
}

function Evidence({ h }: { h: AssignmentEvidence }) {
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

function CaseCard({ c, chosen, onChoose }: { c: AssignmentCase; chosen: string | null; onChoose: (hid: string) => void }) {
  return (
    <section style={{ border: `1px solid ${C.line}`, borderRadius: 6, padding: "12px 14px", display: "flex", flexDirection: "column", gap: 8 }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 8, flexWrap: "wrap" }}>
        <span style={{ fontSize: 14, fontWeight: 900, color: C.navy }}>{c.ambulanceName ?? c.caseId}</span>
        {c.ktasLevel != null && <span style={{ fontSize: 12, fontWeight: 700, color: "#fff", background: c.ktasLevel <= 2 ? "#D93025" : c.ktasLevel === 3 ? "#F26B1D" : "#4E8B1F", borderRadius: 3, padding: "0 6px" }}>Pre-KTAS {c.ktasLevel}</span>}
        <span style={{ fontSize: 13, color: C.ink2 }}>{c.chiefComplaint ?? c.expectedDiagnosis ?? ""}</span>
      </div>
      <div style={{ fontSize: 12.5, color: c.proposedHospitalId ? C.navy : "#B3261E", background: C.bg, borderRadius: 4, padding: "6px 10px" }}>
        에이전트 제안 · {c.reason}
      </div>
      <div role="radiogroup" aria-label={`${c.ambulanceName ?? c.caseId} 배정 병원`} style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        {c.candidates.map((h) => {
          const selectable = h.status === "approved";
          const on = chosen === h.hospitalId;
          const [stText, stColor] = STATUS_TEXT[h.status] ?? [h.status, C.sub];
          return (
            <label key={h.hospitalId} style={{
              display: "flex", gap: 10, alignItems: "flex-start", border: `1px solid ${on ? C.blue : C.line2}`, background: on ? "#F2F7FF" : "#fff",
              borderRadius: 5, padding: "8px 10px", cursor: selectable ? "pointer" : "default", opacity: selectable ? 1 : 0.7,
            }}>
              <input type="radio" name={`assign-${c.caseId}`} checked={on} disabled={!selectable} onChange={() => onChoose(h.hospitalId)} style={{ marginTop: 3 }} />
              <div style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column", gap: 5 }}>
                <div style={{ display: "flex", alignItems: "baseline", gap: 8, flexWrap: "wrap" }}>
                  <span style={{ fontSize: 13.5, fontWeight: 700, color: C.navy }}>{h.name}</span>
                  {c.proposedHospitalId === h.hospitalId && <span style={{ fontSize: 11, fontWeight: 900, color: "#fff", background: C.blue, borderRadius: 3, padding: "0 6px" }}>추천</span>}
                  <span style={{ fontSize: 12, fontWeight: 700, color: stColor }}>{stText}{h.rejectReason ? ` · ${h.rejectReason}` : ""}</span>
                  <span style={{ marginLeft: "auto", fontSize: 12 }}><LineFormula h={h} /></span>
                </div>
                <Evidence h={h} />
                {!selectable && h.status === "pending" && <div style={{ fontSize: 11.5, color: C.muted }}>아직 수용 회신 전 — 지정하려면 병원의 수용 회신이 필요합니다</div>}
              </div>
            </label>
          );
        })}
      </div>
    </section>
  );
}

export function AssignmentModal({ groups, onClose, onDispatch }: {
  groups: AssignmentGroup[];
  onClose: () => void;
  onDispatch: (caseId: string, hospitalId: string) => void;
}) {
  // 사건별 관제 선택 — 기본은 에이전트 제안. 고른 병원이 더는 수용 상태가 아니면(수용 곤란으로 번복 등) 새 제안으로 돌아간다.
  const [picked, setPicked] = useState<Record<string, string>>({});
  const cases = useMemo(() => groups.flatMap((g) => g.proposal.cases), [groups]);
  const choiceOf = (c: AssignmentCase) => {
    const mine = picked[c.caseId];
    return mine && c.candidates.some((h) => h.hospitalId === mine && h.status === "approved") ? mine : c.proposedHospitalId;
  };
  const ready = cases.filter((c) => choiceOf(c));
  const followed = ready.filter((c) => choiceOf(c) === c.proposedHospitalId).length;

  return (
    <div role="dialog" aria-modal="true" aria-label="상황실 배정 요청" style={{ position: "absolute", inset: 0, zIndex: 320, background: "rgba(20,33,61,.5)", display: "flex", alignItems: "center", justifyContent: "center" }}>
      <button type="button" aria-label="나중에" onClick={onClose} style={{ position: "absolute", inset: 0, border: 0, background: "transparent", cursor: "default" }} />
      <div style={{ position: "relative", width: 860, maxHeight: "calc(100% - 48px)", maxWidth: "calc(100% - 32px)", background: "#fff", borderRadius: 6, boxShadow: "0 20px 60px rgba(20,33,61,.35)", display: "flex", flexDirection: "column", overflow: "hidden" }}>
        <div style={{ flex: "none", display: "flex", alignItems: "center", gap: 10, padding: "16px 22px", borderBottom: `1px solid ${C.line2}` }}>
          <div style={{ fontSize: 18, fontWeight: 900, color: C.navy }}>상황실 배정 요청</div>
          <span style={{ fontSize: 12, fontWeight: 700, color: "#fff", background: "#D93025", borderRadius: 3, padding: "1px 8px" }}>{cases.length}건 · 관제 판단 대기</span>
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
                  <CaseCard key={c.caseId} c={c} chosen={choiceOf(c)} onChoose={(hid) => setPicked((p) => ({ ...p, [c.caseId]: hid }))} />
                ))}
              </div>
            );
          })}
          {cases.length === 0 && <div style={{ fontSize: 13, color: C.sub }}>지금 관제가 정해야 할 충돌이 없습니다.</div>}
        </div>

        <div style={{ flex: "none", display: "flex", alignItems: "center", gap: 10, padding: "12px 22px", borderTop: `1px solid ${C.line2}`, background: "#FAFBFC" }}>
          <div style={{ fontSize: 12, color: C.sub, flex: 1 }}>
            지정하면 구급대원 화면에 알려지고 이송이 확정됩니다. 수용 회신 전 병원은 지정할 수 없습니다.
            {ready.length > 0 && ` 제안 그대로 ${followed}건 · 변경 ${ready.length - followed}건`}
          </div>
          <button
            type="button"
            disabled={ready.length === 0}
            onClick={() => { for (const c of ready) onDispatch(c.caseId, choiceOf(c) as string); }}
            style={{ fontFamily: "inherit", fontSize: 14, fontWeight: 900, color: "#fff", background: ready.length ? C.navy : C.faint, border: 0, borderRadius: 5, padding: "9px 18px", cursor: ready.length ? "pointer" : "default" }}
          >
            {ready.length === cases.length ? `배분 안대로 지정 (${ready.length}건)` : `지정 가능한 ${ready.length}건 지정`}
          </button>
        </div>
      </div>
    </div>
  );
}
