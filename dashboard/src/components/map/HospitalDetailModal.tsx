"use client";

import { useEffect, useState } from "react";
import { C, GLASS } from "@/lib/control-map";
import { rejectionReasonLabel } from "@/lib/rejection";
import type { HospitalBackupView, MapHospital } from "@/types/dashboard";

// 관제 병원 상세(2026-11-04) — 병원을 누르면 한 화면에 모은다. hub GET /hospital-backup(열람용, 순위와 무관).
// ① 정보 신뢰도 모델(AI): 지금 응급실 병상 숫자를 믿어도 될 확률·위험 등급·값이 생긴 지 얼마·최종 확인
// ② E-Gen: 등급·병상(가용/정원, 이송 확정 차감 반영)·장비 운영·중증질환 수용 신고(언제부터)·수용 제한 공지
// ③ 심평원: 보유 병상·장비·전문의·간호등급 ④ 규칙: 질환군별 수용 신고 판정(심평원 대조)·거미줄 유효 역량·최근 수용 곤란 반영
// 출처마다 배지(AI / E-Gen / 심평원 / 규칙)를 단다. 보유는 최대치이고 지금 쓸 수 있는지는 E-Gen 가용·병원 회신으로 본다.

const TIER: Record<string, [string, string]> = {
  declared_yes: ["가능 신고", "#1E9E6A"], unknown_specialist: ["전문의 있음·미상", "#5AA9E6"], unknown_designated: ["전문병원 지정·미상", "#5AA9E6"],
  unknown_bare: ["근거 없음·미상", "#8A8FA0"], declared_no: ["불가능 신고", "#D9434B"],
};
const RISK: Record<string, [string, string]> = { low: ["변동 위험 낮음", "#1E9E6A"], medium: ["변동 위험 보통", "#B7791F"], high: ["변동 위험 높음", "#D9434B"] };
const fmtAt = (iso?: string | null) => (iso ? new Date(iso).toLocaleString("ko-KR", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "-");
const fmtAge = (min?: number | null) => (min == null ? "-" : min < 60 ? `${Math.round(min)}분` : min < 1440 ? `${Math.floor(min / 60)}시간 ${Math.round(min % 60)}분` : `${Math.floor(min / 1440)}일`);

function Tag({ children, tone = C.blue }: { children: React.ReactNode; tone?: string }) {
  return <span style={{ fontSize: 10.5, fontWeight: 700, color: tone, border: `1px solid ${tone}`, borderRadius: 999, padding: "0 7px", lineHeight: "16px" }}>{children}</span>;
}

function Section({ title, tag, children }: { title: string; tag?: React.ReactNode; children: React.ReactNode }) {
  return (
    <section style={{ display: "flex", flexDirection: "column", gap: 8, padding: "12px 14px", borderRadius: 14, background: "#fff", border: GLASS.border, boxShadow: "0 2px 10px rgba(91,75,138,.06)" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <span style={{ fontSize: 13.5, fontWeight: 900, color: C.navy }}>{title}</span>{tag}
      </div>
      {children}
    </section>
  );
}

export function HospitalDetailModal({ hospitalId, overview, onClose }: {
  hospitalId: string;
  overview: MapHospital | undefined;
  onClose: () => void;
}) {
  const [view, setView] = useState<HospitalBackupView | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    const httpUrl = process.env.NEXT_PUBLIC_HUB_HTTP_URL;
    if (!httpUrl) return;
    let cancelled = false;
    fetch(`${httpUrl.replace(/\/$/, "")}/hospital-backup?id=${encodeURIComponent(hospitalId)}`)
      .then(async (r) => {
        const body = await r.json();
        if (cancelled) return;
        if (!r.ok) setError(body.error ?? `불러오지 못했습니다(${r.status})`);
        else setView(body as HospitalBackupView);
      })
      .catch(() => { if (!cancelled) setError("hub에 연결하지 못했습니다"); });
    return () => { cancelled = true; };
  }, [hospitalId]);
  const noHub = !process.env.NEXT_PUBLIC_HUB_HTTP_URL;

  const br = view?.bedReliability;
  const groups = Object.entries(view?.assessmentGroups ?? {}).sort((a, b) => b[1].score - a[1].score);
  const severe = Object.entries(view?.severeDeclarations?.groups ?? {});

  return (
    <div role="dialog" aria-modal="true" aria-label="병원 상세" style={{ position: "absolute", inset: 0, zIndex: 330, background: "rgba(28,31,42,.32)", backdropFilter: "blur(6px)", display: "flex", alignItems: "center", justifyContent: "center" }}>
      <button type="button" aria-label="닫기" onClick={onClose} style={{ position: "absolute", inset: 0, border: 0, background: "transparent", cursor: "default" }} />
      <div style={{ position: "relative", width: 1100, maxHeight: "calc(100% - 48px)", maxWidth: "calc(100% - 32px)", background: GLASS.solid, border: GLASS.border, borderRadius: GLASS.radius, boxShadow: "0 24px 60px rgba(91,75,138,.28)", fontFamily: GLASS.font, display: "flex", flexDirection: "column", overflow: "hidden", whiteSpace: "normal" }}>
        <div style={{ flex: "none", display: "flex", alignItems: "center", gap: 10, padding: "16px 22px", borderBottom: `1px solid ${C.line2}`, flexWrap: "wrap" }}>
          <div style={{ fontSize: 18, fontWeight: 900, color: C.navy }}>{view?.name ?? overview?.name ?? hospitalId}</div>
          <span style={{ fontSize: 12, color: C.sub }}>H-{hospitalId}</span>
          {(view?.emergencyLevel ?? overview?.emergencyLevel) && <Tag>{view?.emergencyLevel ?? overview?.emergencyLevel}</Tag>}
          {view?.erPhone && <span style={{ fontSize: 12.5, color: C.ink2 }}>응급실 ☎ {view.erPhone}</span>}
          <div style={{ flex: 1 }} />
          <button type="button" onClick={onClose} style={{ fontFamily: "inherit", fontSize: 13, color: C.ink3, background: "#fff", border: `1px solid ${C.line}`, borderRadius: 999, padding: "5px 12px", cursor: "pointer" }}>닫기 ✕</button>
        </div>
        <div style={{ padding: "14px 22px", overflowY: "auto", display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: 12 }}>
          {noHub && <div style={{ fontSize: 13, color: C.sub }}>hub 주소가 없어 불러올 수 없습니다(목데이터 모드).</div>}
          {error && <div style={{ fontSize: 13, color: "#B3261E" }}>{error}</div>}
          {!noHub && !error && !view && <div style={{ fontSize: 13, color: C.sub }}>불러오는 중…</div>}
          {view && (
            <>
              <Section title="정보 신뢰도 모델" tag={<Tag>AI · 정보 생존 모델</Tag>}>
                {br ? (
                  <>
                    <div style={{ display: "flex", alignItems: "baseline", gap: 10 }}>
                      <span style={{ fontSize: 26, fontWeight: 900, color: br.riskLevel ? RISK[br.riskLevel][1] : C.navy }}>{Math.round(br.authority * 100)}%</span>
                      <span style={{ fontSize: 12.5, color: C.ink2 }}>지금 응급실 병상 숫자가 유효할 확률</span>
                      {br.riskLevel && <Tag tone={RISK[br.riskLevel][1]}>{RISK[br.riskLevel][0]}</Tag>}
                    </div>
                    <div style={{ fontSize: 12.5, color: C.ink2, lineHeight: 1.7 }}>
                      이 값이 생긴 지 {fmtAge(br.ageMin)} · 예측 수명 {fmtAge(br.predictedSurvivalMin)}<br />
                      최종 확인 {fmtAt(br.checkedAt)}{br.confirmedAt ? ` (병원이 직접 확인 ${fmtAt(br.confirmedAt)})` : ""} · 모델 {br.modelTag}
                    </div>
                    <div style={{ fontSize: 11, color: C.muted }}>수용 확률이 아니라, 보이는 병상 숫자가 바뀌지 않고 유지될 확률입니다. 순위에는 쓰지 않습니다.</div>
                  </>
                ) : <div style={{ fontSize: 12.5, color: C.muted }}>이 병원의 신뢰도 예측이 없습니다.</div>}
                {view.beds.some((b) => b.authority != null) && (
                  <div style={{ display: "flex", flexWrap: "wrap", gap: 8, fontSize: 12 }}>
                    {view.beds.filter((b) => b.authority != null).map((b) => (
                      <span key={b.key} style={{ color: C.ink2 }}>{b.label} <b style={{ color: C.navy }}>{Math.round((b.authority ?? 0) * 100)}%</b></span>
                    ))}
                  </div>
                )}
              </Section>

              <Section title="병상" tag={<><Tag tone="#1E9E6A">E-Gen</Tag><Tag tone="#5B6070">심평원</Tag></>}>
                <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12.5 }}>
                  <thead><tr style={{ color: C.sub, textAlign: "right" }}><th style={{ textAlign: "left", fontWeight: 600 }}>구분</th><th style={{ fontWeight: 600 }}>지금 가용</th><th style={{ fontWeight: 600 }}>E-Gen 정원</th><th style={{ fontWeight: 600 }}>심평원 보유</th></tr></thead>
                  <tbody>
                    {view.beds.map((b) => (
                      <tr key={b.key} style={{ textAlign: "right", borderTop: `1px solid ${C.line2}` }}>
                        <td style={{ textAlign: "left", padding: "4px 0", color: C.navy, fontWeight: 600 }} title={b.note ?? undefined}>{b.label}</td>
                        <td>{b.available ?? "-"}</td><td>{b.egenCapacity ?? "-"}</td><td>{b.hiraCapacity ?? "-"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <div style={{ fontSize: 11.5, color: C.sub }}>이송 중 {view.inFlightCount}건(가용에 차감 반영) · E-Gen 갱신 {fmtAt(view.egenUpdatedAt)}{view.nursingGrade ? ` · 간호등급 ${view.nursingGrade}` : ""}</div>
              </Section>

              <Section title="장비" tag={<><Tag tone="#1E9E6A">E-Gen 운영</Tag><Tag tone="#5B6070">심평원 보유</Tag></>}>
                <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: "4px 14px", fontSize: 12.5 }}>
                  {view.equipment.map((e) => (
                    <span key={e.key} style={{ color: C.ink2 }} title={e.note ?? undefined}>
                      {e.label}{" "}
                      <b style={{ color: e.egenOperating === "Y" ? "#1E9E6A" : e.egenOperating ? "#D9434B" : C.faint }}>
                        {e.egenOperating === "Y" ? "운영" : e.egenOperating ? "미운영" : "운영 정보 없음"}
                      </b>
                      {e.hiraCount != null && <span style={{ color: C.sub }}> · 보유 {e.hiraCount}</span>}
                    </span>
                  ))}
                  {view.equipment.length === 0 && <span style={{ color: C.muted }}>장비 정보가 없습니다.</span>}
                </div>
                <div style={{ fontSize: 11, color: C.muted }}>지금 남은 대수는 공개 정보가 없습니다 — 운영 여부와 보유 대수만입니다.</div>
              </Section>

              <Section title="전문의" tag={<Tag tone="#5B6070">심평원</Tag>}>
                <div style={{ display: "flex", flexWrap: "wrap", gap: "4px 12px", fontSize: 12.5 }}>
                  {view.specialties.map((s) => <span key={s.department} style={{ color: C.ink2 }}>{s.department} <b style={{ color: C.navy }}>{s.doctorCount}</b></span>)}
                  {view.specialties.length === 0 && <span style={{ color: C.muted }}>전문의 정보가 없습니다.</span>}
                </div>
                {view.hiraCollectedAt && <div style={{ fontSize: 11, color: C.muted }}>심평원 수집 {fmtAt(view.hiraCollectedAt)}</div>}
              </Section>

              <Section title="중증질환 수용" tag={<><Tag tone="#1E9E6A">E-Gen 신고</Tag><Tag tone="#6B5BD2">규칙 · 심평원 대조</Tag></>}>
                <div style={{ display: "flex", flexDirection: "column", gap: 4, fontSize: 12 }}>
                  {groups.map(([g, v]) => {
                    const decl = view.severeDeclarations?.groups?.[g];
                    const [label, color] = TIER[v.tier] ?? [v.tier, C.sub];
                    return (
                      <div key={g} style={{ display: "flex", gap: 8, alignItems: "baseline" }} title={v.basis.join("\n")}>
                        <span style={{ width: 96, flex: "none", color: C.navy, fontWeight: 600 }}>{g}</span>
                        <span style={{ fontWeight: 700, color }}>{label}</span>
                        <span style={{ color: C.muted }}>신뢰 {v.confidence}</span>
                        {decl && <span style={{ marginLeft: "auto", color: C.sub }}>신고 「{decl.value}」 {fmtAt(decl.bornAt)}{decl.ageIsMin ? " 이전부터" : "부터"}</span>}
                      </div>
                    );
                  })}
                  {groups.length === 0 && severe.map(([g, d]) => (
                    <div key={g} style={{ color: C.ink2 }}>{g} · 신고 「{d.value}」 {fmtAt(d.bornAt)}부터</div>
                  ))}
                  {groups.length === 0 && severe.length === 0 && <span style={{ color: C.muted }}>중증질환 신고 정보가 없습니다.</span>}
                </div>
              </Section>

              <Section title="수용 제한 공지 · 최근 수용 곤란" tag={<><Tag tone="#1E9E6A">E-Gen</Tag><Tag tone="#6B5BD2">규칙 · 학습 반영</Tag></>}>
                <div style={{ display: "flex", flexDirection: "column", gap: 5, fontSize: 12.5 }}>
                  {view.acceptanceMessages.map((m, i) => (
                    <div key={i} style={{ color: m.kind === "severe" ? "#B3261E" : C.ink2 }}>
                      [{m.kind === "severe" ? `중증 차단 · ${m.diseaseGroup ?? m.diseaseName ?? ""}` : m.department ?? "응급실"}] {m.message}
                      <span style={{ color: C.muted }}> · {fmtAt(m.startAt)}~{m.endAt ? fmtAt(m.endAt) : ""}</span>
                    </div>
                  ))}
                  {(view.recentRefusals ?? []).map((r, i) => (
                    <div key={`r${i}`} style={{ color: "#B7791F" }}>
                      수용 곤란 · {rejectionReasonLabel(r.reasonCode)} ({r.axis === "momentary" ? "순간적 — 30분 동안 다른 사건 +15분" : "구조적 — 같은 질환군 24시간 뒤로"}) · {fmtAt(r.until)}까지
                    </div>
                  ))}
                  {view.acceptanceMessages.length === 0 && (view.recentRefusals ?? []).length === 0 && <span style={{ color: C.muted }}>지금 유효한 공지·반영 중인 수용 곤란이 없습니다.</span>}
                </div>
              </Section>

              {view.capability && (
                <Section title="거미줄 역량(배정 계산)" tag={<Tag tone="#6B5BD2">규칙 · 전문의 검토 전 초안</Tag>}>
                  <div style={{ fontSize: 12.5, color: C.ink2, lineHeight: 1.7 }}>
                    유효 역량 <b style={{ color: C.navy }}>{view.capability.effectiveCapacity}</b> ({view.capability.parts}){view.capability.nightPenalty ? " · 야간 감점 중" : ""}<br />
                    대표 Pre-KTAS {view.capability.hospitalKtas ?? "-"} · 줄이 걸리는 Pre-KTAS {view.capability.supportedKtas.join(", ") || "-"}(일반 질환 기준, 표시용)
                  </div>
                </Section>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
