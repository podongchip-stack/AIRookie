"use client";

import { useState, type ReactNode } from "react";
import { distanceLabel } from "@/lib/distance";
import { REJECTION_REASON_GROUPS, rejectionReasonLabel, unavailableReasonLabel } from "@/lib/rejection";
import { HD } from "@/components/hospital/hospital-design";
import { FollowupCallBox } from "@/components/panels/FollowupCallBox";
import { ConfirmationChip, OverrideChangesBox } from "@/components/panels/PatientConfirmation";
import type {
  AmbulanceSimState, ApprovalAction, HospitalCandidate, HubMatchResult, RejectionReason, Severity,
} from "@/types/dashboard";

// 구급차 수용 요청 카드(2026-10-04, 디자인 시안 "골든링크 병원 대시보드"). 예전 CaseMatchPanel을 대체한다.
// 왼쪽 띠(상태 색) · KTAS 상자 · 환자 정보(AI 구조화) · 활력징후 한 줄 · 상태 안내 | 오른쪽: 임베딩 매칭·상태 칩,
// 도착 예상(누르면 지도에 경로), 버튼(판단 대기: 병원 승인/불가, 도착: 수용 완료/도착 후 수용 불가). 불가 사유는
// 카드 맨 아래 한 줄로 펼친다. 병원의 승인·불가는 후보 등록일 뿐이라 번복할 수 있다(이송 결정은 구급대원).

export type CardKind = "pending" | "approved" | "transit" | "arrived" | "done" | "declined" | "full";

const KIND: Record<CardKind, { label: string; map: string; band: string; ink: string; bg: string; group: number }> = {
  arrived: { label: "도착 · 결과 대기", map: "도착", band: HD.blue, ink: HD.blue, bg: HD.blueSoft, group: 0 },
  pending: { label: "판단 대기 중", map: "판단 대기", band: HD.orange, ink: HD.orange, bg: HD.orangeSoft, group: 1 },
  approved: { label: "본원 승인함", map: "본원 승인", band: HD.lime, ink: HD.lime, bg: HD.limeSoft, group: 1 },
  transit: { label: "이송 확정됨", map: "이송 확정", band: HD.green, ink: HD.green, bg: HD.greenSoft, group: 2 },
  done: { label: "수용 완료", map: "수용 완료", band: HD.gray, ink: HD.lime, bg: HD.limeSoft, group: 3 },
  declined: { label: "수용 불가", map: "수용 불가", band: HD.gray, ink: HD.red, bg: HD.redSoft, group: 3 },
  full: { label: "병상 없음", map: "병상 없음", band: HD.gray, ink: HD.red, bg: HD.redSoft, group: 3 },
};

export const kindMeta = (kind: CardKind) => KIND[kind];

// 이 사건이 본원 입장에서 지금 어떤 단계인지
export function cardKind(hospital: HospitalCandidate, arrivalReady: boolean, accepted: boolean): CardKind {
  if (hospital.status === "confirmed") return accepted ? "done" : arrivalReady ? "arrived" : "transit";
  const confirmedFull =
    hospital.status !== "approved" && !hospital.bedCountUnknown && !hospital.bedDataStale && hospital.availableBedCount <= 0;
  if (hospital.unavailableReason || confirmedFull) return "full";
  if (hospital.status === "rejected") return "declined";
  if (hospital.status === "approved") return "approved";
  return "pending";
}

const SEV: Record<Severity, { ink: string; bg: string; label: string }> = {
  high: { ink: HD.red, bg: HD.redSoft, label: "중증 의심" },
  medium: { ink: HD.orange, bg: HD.orangeSoft, label: "중등증 의심" },
  low: { ink: HD.blue, bg: HD.blueSoft, label: "경증 의심" },
};

// 활력징후 주의 색 — 화면 강조용 참고 기준(진단 아님): 수축기 90 이하·140 이상, 맥박 50 미만·100 이상, SpO₂ 95 미만
const warn = {
  bp: (sbp?: number | null) => sbp != null && (sbp <= 90 || sbp >= 140),
  hr: (hr?: number | null) => hr != null && (hr < 50 || hr >= 100),
  sp: (sp?: number | null) => sp != null && sp < 95,
};

const REASONS: { value: RejectionReason; label: string }[] = [
  { value: "UNSPECIFIED", label: "사유 없음" },
  ...REJECTION_REASON_GROUPS.flatMap((g) => g.options),
];

export function RequestCard({
  result,
  hospital,
  hospitalId,
  kind,
  selected,
  sim,
  banner,
  onSelect,
  onAction,
  paused = false,
  onPaused,
}: {
  result: HubMatchResult;
  hospital: HospitalCandidate;
  hospitalId: string;
  kind: CardKind;
  selected: boolean;
  // 본원으로 이송 중인 구급차의 시뮬레이션 상태(남은 시간·진행 막대)
  sim: AmbulanceSimState | null;
  // 이송 중 상태 변화 배너(있으면 카드 맨 위)
  banner?: ReactNode;
  onSelect: () => void;
  onAction: (action: ApprovalAction) => void;
  // 시연 일시정지 중(2026-10-05) — 버튼을 눌러도 보내지 않고 onPaused(화면 위 안내)만 부른다
  paused?: boolean;
  onPaused?: () => void;
}) {
  const [rejecting, setRejecting] = useState<null | "hospital_reject" | "arrival_refused" | "transport_withdraw">(null);
  // 일시정지 중엔 모든 조작을 막는다(2026-10-05) — 사유 칸을 여는 것부터 막아 hub로 아무것도 안 간다
  const act = (fn: () => void) => () => {
    if (paused) onPaused?.();
    else fn();
  };
  const p = result.patientInfo;
  const m = KIND[kind];
  const sev = SEV[p.severityTag];
  const ktas = p.ktasLevel ?? null;
  const vital = p.vitals?.[p.vitals.length - 1];
  const closed = kind === "done" || kind === "declined" || kind === "full";

  // 도착 예상: 이송 중이면 시뮬레이션 남은 시간, 아니면 매칭 때 ETA
  const etaMin =
    kind === "transit" && sim?.etaSec != null ? Math.max(1, Math.ceil(sim.etaSec / 60)) : hospital.etaMin ?? null;
  const etaMain = kind === "arrived" || kind === "done" ? "도착" : etaMin != null ? `${etaMin}분` : "-";
  const progress =
    kind === "transit" && sim?.etaSec != null && hospital.etaMin
      ? Math.min(1, Math.max(0.05, 1 - sim.etaSec / (hospital.etaMin * 60)))
      : null;

  function send(action: ApprovalAction["action"], reason?: RejectionReason) {
    onAction({
      caseId: result.caseId,
      action,
      hospital_id: hospitalId,
      actor: "hospital",
      timestamp: new Date().toISOString(),
      ...(reason ? { reason } : {}),
    });
  }

  const closedText =
    kind === "done"
      ? "환자 수용이 완료되었습니다."
      : kind === "full"
        ? `수용 불가 · ${unavailableReasonLabel(hospital.unavailableReason) ?? "응급실 병상 없음(E-Gen 0)"} — 지금은 수용 승인을 할 수 없습니다`
        : hospital.excluded
          ? `수용 철회·불가로 이 사건에서 제외됨 · 사유: ${rejectionReasonLabel(hospital.rejectReason) ?? "사유 없음"}`
          : `수용 불가 처리됨 · 사유: ${rejectionReasonLabel(hospital.rejectReason) ?? "사유 없음"}`;

  const facts = [
    p.consciousness && `의식 ${p.consciousness}`,
    p.onset && `발생 ${p.onset}`,
  ].filter(Boolean) as string[];

  return (
    <article
      style={{
        // 선택 표시는 연한 파랑 테두리 1px(2026-10-04) — 진한 남색 2px은 목록에서 너무 도드라졌다
        background: "#FFFFFF", borderRadius: 14, border: selected ? "1px solid #B9C9E2" : `1px solid ${HD.line}`,
        overflow: "hidden", display: "flex", opacity: closed ? 0.72 : 1,
      }}
    >
      <div style={{ flex: "none", width: 6, background: m.band }} />
      <div style={{ flex: 1, minWidth: 0, padding: "12px 16px 12px 14px", display: "flex", flexDirection: "column", gap: 8 }}>
        {banner}
        {/* 이송 중 2차 통화로 갱신된 환자 정보 — 직전 통화와 바뀐 점(2026-10-05) */}
        <FollowupCallBox patientInfo={p} />
        {/* 구급대원이 AI 요약을 고쳤으면 무엇이 바뀌었는지(2026-10-13, Override) — 승인은 유지되니 다시 판단할 근거 */}
        <OverrideChangesBox patientInfo={p} />
        <div style={{ display: "flex", flexWrap: "wrap", alignItems: "flex-start", gap: "10px 14px" }}>
          {/* KTAS */}
          <div
            style={{
              flex: "none", background: sev.ink, color: "#FFFFFF", borderRadius: 10, padding: "6px 9px", minWidth: 46,
              boxSizing: "border-box", display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", lineHeight: 1.1,
            }}
          >
            <span style={{ fontSize: 10.5, letterSpacing: 0.4 }}>KTAS</span>
            <span style={{ fontSize: 19, fontWeight: 900 }}>{ktas ?? "-"}</span>
          </div>

          {/* 환자 정보(AI 구조화) */}
          <div style={{ flex: "1 1 300px", minWidth: 0, display: "flex", flexDirection: "column", gap: 4 }}>
            <div style={{ display: "flex", flexWrap: "wrap", alignItems: "baseline", gap: "2px 8px" }}>
              <span style={{ fontSize: 13.5, fontWeight: 700, color: HD.navy }}>{result.ambulanceName ?? result.apid ?? "구급차"}</span>
              <span style={{ fontSize: 11.5, color: HD.muted }}>실시간 환자 정보 요약</span>
              <ConfirmationChip patientInfo={p} />
              {(p.callRound ?? 1) > 1 && (
                <span
                  style={{ fontSize: 10.5, fontWeight: 700, color: HD.orange, background: HD.orangeSoft, borderRadius: 999, padding: "2px 8px" }}
                  title="환자 상태가 바뀌어 구급대가 다시 통화했습니다 — 최신 통화 내용이 위에 반영되고, 앞선 요약은 아래에 남습니다"
                >
                  {p.callRound}차 통화로 갱신
                </span>
              )}
            </div>
            <div style={{ display: "flex", alignItems: "center" }}>
              <span
                style={{
                  fontSize: 12, fontWeight: 700, color: sev.ink, background: sev.bg, borderRadius: 999, padding: "3px 10px",
                  maxWidth: "100%", boxSizing: "border-box", overflow: "hidden", textOverflow: "ellipsis",
                }}
              >
                {sev.label} · {p.expectedDiagnosis}
              </span>
            </div>
            <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: "3px 6px" }}>
              <span style={{ fontSize: 13, color: HD.ink3 }}>
                {p.patient ? `${p.patient} · ` : ""}주 호소 <b style={{ color: HD.navy, fontSize: 13.5, fontWeight: 700 }}>{p.chiefComplaint ?? p.expectedDiagnosis}</b>
              </span>
              {p.injuryStatus.slice(0, 4).map((tag) => (
                <span key={tag} style={{ fontSize: 10.5, padding: "2px 8px", borderRadius: 6, background: HD.chip, color: HD.ink3 }}>{tag}</span>
              ))}
            </div>
            {(facts.length > 0 || p.requiredDepartment) && (
              <div style={{ fontSize: 12, color: HD.sub, overflow: "hidden", textOverflow: "ellipsis" }}>
                {facts.join(" · ")}
                {p.requiredDepartment && (
                  <>
                    {facts.length > 0 ? " · " : ""}필요 진료과 <b style={{ color: HD.navy, fontWeight: 700 }}>{p.requiredDepartment}</b>
                  </>
                )}
              </div>
            )}

            {/* 활력징후 한 줄 */}
            {vital && (
              <div style={{ display: "flex", flexWrap: "wrap", alignItems: "baseline", gap: "2px 12px", borderTop: `1px solid ${HD.line2}`, marginTop: 2, paddingTop: 5 }}>
                <span style={{ fontSize: 11.5, color: HD.sub }}>활력징후</span>
                <Vital label="혈압" value={vital.sbp != null || vital.dbp != null ? `${vital.sbp ?? "?"}/${vital.dbp ?? "?"}` : "-"} bad={warn.bp(vital.sbp)} first />
                <Vital label="맥박" value={vital.hr != null ? String(vital.hr) : "-"} bad={warn.hr(vital.hr)} />
                <Vital label="SpO₂" value={vital.spo2 != null ? `${vital.spo2}%` : "-"} bad={warn.sp(vital.spo2)} />
              </div>
            )}

            {/* 앞선 통화 요약(덧붙이기, 2026-10-05) — 지우지 않고 회차별로 남긴다 */}
            {(p.previousCalls ?? []).length > 0 && (
              <div style={{ display: "flex", flexDirection: "column", gap: 2, background: HD.line2, borderRadius: 8, padding: "5px 9px" }}>
                {(p.previousCalls ?? []).map((u) => (
                  <span key={u.callRound} style={{ fontSize: 11.5, color: HD.sub }}>
                    <b style={{ color: HD.ink3 }}>{u.callRound}차 통화</b> · {SEV[u.severityTag].label} · {u.expectedDiagnosis}
                    {u.ktasLevel != null ? ` · KTAS ${u.ktasLevel}` : ""}
                  </span>
                ))}
              </div>
            )}

            {/* 상태 안내 */}
            <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: "2px 12px" }}>
              {kind === "transit" && (
                <span style={{ display: "inline-flex", alignItems: "center", gap: 8, fontSize: 12, fontWeight: 700, color: HD.green }}>
                  본원으로 이송 중입니다{etaMin != null ? ` · 도착까지 약 ${etaMin}분` : ""}
                  {progress != null && (
                    <span style={{ display: "inline-block", width: 80, height: 5, borderRadius: 999, background: "#DDEBE3", overflow: "hidden" }}>
                      <span style={{ display: "block", width: `${Math.round(progress * 100)}%`, height: 5, background: HD.green }} />
                    </span>
                  )}
                </span>
              )}
              {kind === "arrived" && (
                <span style={{ fontSize: 12, fontWeight: 700, color: HD.blue }}>구급차가 도착했습니다 — 수용 결과를 선택하세요</span>
              )}
              {kind === "approved" && (
                <span style={{ fontSize: 12, fontWeight: 700, color: HD.lime }}>본원 승인함 — 구급대원의 이송 결정을 기다리는 중</span>
              )}
              {closed && <span style={{ fontSize: 12, fontWeight: 700, color: m.ink }}>{closedText}</span>}
              <span style={{ fontSize: 11.5, color: HD.muted }}>이송 여부는 구급대원이 최종 결정합니다</span>
            </div>
          </div>

          {/* 오른쪽: 칩 + 도착 예상 + 버튼 */}
          <div style={{ flex: "0 0 186px", display: "flex", flexDirection: "column", gap: 6 }}>
            <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", justifyContent: "space-between", gap: "4px 6px" }}>
              <span style={{ fontSize: 10.5, color: HD.blue, background: HD.blueSoft, borderRadius: 999, padding: "3px 8px", display: "inline-flex", alignItems: "center", gap: 4 }}>
                <span style={{ width: 5, height: 5, borderRadius: "50%", background: HD.blue }} />
                임베딩 매칭
              </span>
              <span style={{ fontSize: 10.5, fontWeight: 700, color: m.ink, background: m.bg, borderRadius: 999, padding: "3px 8px" }}>{m.label}</span>
            </div>
            <button
              type="button"
              onClick={onSelect}
              aria-label={`${result.ambulanceName ?? "구급차"} 경로를 지도에 표시, 도착 예상 ${etaMain}`}
              style={{
                width: "100%", minHeight: 40, borderRadius: 10, border: selected ? "1px solid #B9C9E2" : `1px solid ${HD.line}`,
                background: selected ? HD.blueSoft : "#FFFFFF", color: HD.ink, display: "flex", alignItems: "center", justifyContent: "center",
                gap: 7, padding: "4px 10px", boxSizing: "border-box", fontFamily: "inherit", cursor: "pointer",
              }}
            >
              <span style={{ fontSize: 19, fontWeight: 900, color: kind === "transit" ? HD.green : HD.navy }}>{etaMain}</span>
              <span style={{ fontSize: 11.5, color: HD.sub }}>{distanceLabel(hospital)}</span>
            </button>

            {rejecting === null && (kind === "pending" || kind === "approved" || kind === "declined") && (
              <>
                {kind !== "approved" && !hospital.excluded && (
                  <button type="button" onClick={act(() => send("hospital_approve"))} style={pausedStyle(primaryBtn, paused)}>
                    {kind === "declined" ? "승인으로 변경" : "병원 승인"}
                  </button>
                )}
                {kind !== "declined" && (
                  <button type="button" onClick={act(() => setRejecting("hospital_reject"))} style={pausedStyle(dangerBtn, paused)}>
                    {kind === "approved" ? "불가로 변경 (사유)" : "불가 (사유 선택)"}
                  </button>
                )}
              </>
            )}
            {rejecting === null && kind === "arrived" && (
              <>
                <button type="button" onClick={act(() => send("arrival_accepted"))} style={pausedStyle({ ...primaryBtn, background: HD.lime }, paused)}>
                  환자 수용 완료
                </button>
                <button type="button" onClick={act(() => setRejecting("arrival_refused"))} style={pausedStyle(dangerBtn, paused)}>
                  도착 후 수용 불가 (사유)
                </button>
              </>
            )}
            {kind === "transit" && rejecting === null && (
              <>
                {/* 이송 중 수용 철회(2026-10-05) — 도착 전에 환자 상태·본원 사정으로 못 받게 되면 바로 알린다.
                    구급차는 그 자리에서 다른 승인 병원으로 재선택하고, 본원은 이 사건에서 빠진다. */}
                <button type="button" onClick={act(() => setRejecting("transport_withdraw"))} style={pausedStyle(dangerBtn, paused)}>
                  이송 중 수용 철회 (사유)
                </button>
                <span style={{ fontSize: 11.5, color: HD.muted, textAlign: "center" }}>구급차가 도착하면 수용 결과 버튼이 열립니다</span>
              </>
            )}
            {paused && !closed && (
              <span style={{ fontSize: 11.5, fontWeight: 700, color: HD.orange, textAlign: "center" }}>시연 일시정지 중 — 조작 잠김</span>
            )}
          </div>
        </div>

        {/* 불가 사유: 카드 맨 아래 한 줄 */}
        {rejecting !== null && (
          <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 6, background: HD.redSoft, borderRadius: 10, padding: "7px 10px" }}>
            <span style={{ fontSize: 13, fontWeight: 700, color: HD.red, marginRight: 4 }}>
              {rejecting === "arrival_refused"
                ? "도착 후 수용 불가 사유를 선택하세요"
                : rejecting === "transport_withdraw"
                  ? "이송 중 수용 철회 사유를 선택하세요 — 구급차는 다른 병원으로 재선택합니다"
                  : "불가 사유를 선택하세요"}
            </span>
            {REASONS.map((r) => (
              <button
                key={r.value}
                type="button"
                onClick={() => {
                  if (paused) onPaused?.();
                  else send(rejecting, r.value);
                  setRejecting(null);
                }}
                style={{ minHeight: 36, padding: "0 11px", borderRadius: 8, border: "1.5px solid #EBA9A3", background: "#FFFFFF", color: HD.red, fontSize: 13, fontFamily: "inherit", cursor: "pointer" }}
              >
                {r.label}
              </button>
            ))}
            <button
              type="button"
              onClick={() => setRejecting(null)}
              style={{ minHeight: 36, padding: "0 12px", marginLeft: "auto", borderRadius: 8, border: "1px solid #C9D2DC", background: "#FFFFFF", color: HD.ink3, fontSize: 13, fontFamily: "inherit", cursor: "pointer" }}
            >
              취소
            </button>
          </div>
        )}
      </div>
    </article>
  );
}

function Vital({ label, value, bad, first }: { label: string; value: string; bad: boolean; first?: boolean }) {
  return (
    <span style={{ display: "inline-flex", alignItems: "baseline", gap: 5, ...(first ? {} : { borderLeft: `1px solid ${HD.line}`, paddingLeft: 12 }) }}>
      <span style={{ fontSize: 11.5, color: HD.muted }}>{label}</span>
      <span style={{ fontSize: 16, fontWeight: 700, color: bad ? HD.red : HD.navy }}>{value}</span>
    </span>
  );
}

// 일시정지 중엔 버튼을 흐리게(누르면 안내만 뜬다)
function pausedStyle(style: React.CSSProperties, paused: boolean): React.CSSProperties {
  return paused ? { ...style, opacity: 0.45, cursor: "not-allowed" } : style;
}

const primaryBtn: React.CSSProperties = {
  width: "100%", minHeight: 44, borderRadius: 10, border: "none", background: HD.blue, color: "#FFFFFF", fontSize: 14,
  fontWeight: 700, fontFamily: "inherit", cursor: "pointer",
};
const dangerBtn: React.CSSProperties = {
  width: "100%", minHeight: 38, borderRadius: 10, border: `1.5px solid ${HD.red}`, background: "#FFFFFF", color: HD.red,
  fontSize: 13, fontWeight: 700, fontFamily: "inherit", cursor: "pointer",
};
