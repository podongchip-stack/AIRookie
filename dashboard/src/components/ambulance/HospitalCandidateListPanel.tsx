"use client";

import { useEffect, useState } from "react";
import type { CSSProperties, ReactNode } from "react";
import { distanceLabel, distanceTitle } from "@/lib/distance";
import { rejectionReasonLabel, unavailableReasonLabel } from "@/lib/rejection";
import { AD, pill } from "@/components/ambulance/ambulance-design";
import { formatDeclarationAge, liveBedReliability } from "@/lib/bedReliability";
import type { AcceptanceMessage, HospitalCandidate, HospitalStatus, HubMatchResult, ReliabilityConfidence, SceneCandidates } from "@/types/dashboard";

// 병원 후보 리스트(2026-10-05 디자인 시안) — 화면 아래쪽 가로 스크롤 카드 줄. 카드마다 이름 · 거리 · ETA · 상태,
// 병상 · AI 유효 · 전문의 세 칸, 진료과·등급 칩, AI 배후진료 한 줄, [이송 승인].
//
// 순서는 hub가 보낸 hospitals[] 순서를 그대로 쓴다(2026-10-01). "확정·승인 병원을 위로, 거절 병원은 맨 뒤"
// 규칙도 hub의 scoring.rank_key()에 있다. 거절해도 목록에서 없애지 않는 원칙은 그대로다.

const STATUS_LABEL: Record<HospitalStatus, string> = {
  pending: "판단 대기",
  approved: "후보 등록",
  rejected: "수용 불가",
  confirmed: "이송 확정",
};

const STATUS_PILL: Record<HospitalStatus, { bg: string; fg: string }> = {
  pending: { bg: AD.orangeSoft, fg: AD.orange },
  approved: { bg: AD.blueSoft, fg: AD.blue },
  rejected: { bg: AD.redSoft, fg: AD.red },
  confirmed: { bg: AD.greenSoft, fg: AD.green },
};

const CONFIDENCE_LABEL: Record<ReliabilityConfidence, string> = {
  high: "신뢰도 높음",
  medium: "신뢰도 보통",
  low: "신뢰도 낮음",
};

// 확장 필드(수술실·입원실·소아)의 E-Gen 필드명 → 한글 라벨.
// info의 reliability/train_field.py FIELD_LABELS와 같은 값 — 모르는 필드가
// 오면 필드명을 그대로 보여준다(조용히 숨기면 확장을 눈치채지 못한다).
const BED_FIELD_LABEL: Record<string, string> = {
  hvoc: "수술실",
  hvicc: "중환자실",
  hvgc: "입원실",
  hv28: "소아",
  hv29: "음압",
};

const CARD_WIDTH = 340;

const cardBase: CSSProperties = {
  flex: `0 0 ${CARD_WIDTH}px`,
  boxSizing: "border-box",
  scrollSnapAlign: "start",
  display: "flex",
  flexDirection: "column",
  gap: 6,
  background: "#FFFFFF",
  borderRadius: 18,
  padding: "12px 14px",
  whiteSpace: "normal",
};

// 병상 신뢰도(infosurv, AI) — 도착 시 유효 확률. ≥80% 파랑(믿고 출발), 50~80% 회색(참고), <50% 빨강(재확인 권장).
function validTone(rArrive: number): { bg: string; fg: string } {
  if (rArrive >= 0.8) return { bg: AD.blueSoft, fg: AD.blue };
  if (rArrive >= 0.5) return { bg: AD.chip, fg: AD.ink3 };
  return { bg: AD.redSoft, fg: AD.red };
}

function StatBox({ label, value, bg, fg, valueColor, title }: { label: string; value: string; bg: string; fg: string; valueColor?: string; title?: string }) {
  return (
    <div style={{ background: bg, borderRadius: 12, padding: "5px 10px", minWidth: 0 }} title={title}>
      <div style={{ fontSize: 11.5, color: fg, fontWeight: 500 }}>{label}</div>
      <div style={{ fontSize: 19, fontWeight: 900, color: valueColor ?? fg, lineHeight: 1.2, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{value}</div>
    </div>
  );
}

function Chip({ children, bg = AD.chip, fg = AD.ink3, title, border }: { children: ReactNode; bg?: string; fg?: string; title?: string; border?: string }) {
  return (
    <span title={title} style={{ ...pill(bg, fg), ...(border ? { border: `1px solid ${border}` } : {}) }}>
      {children}
    </span>
  );
}

function bedBox(available: number, unknown: boolean, stale?: boolean) {
  // "확인된 만실"(빨강)과 "미상"(회색)을 다르게 둔다 — 미상을 만실처럼 보이면 구급대원이 실제로는 받아줄 수도
  // 있는 병원을 스스로 후보에서 빼게 된다(CLAUDE.md 참고).
  if (unknown) return <StatBox label="병상" value="미상" bg={AD.chip} fg={AD.ink3} title="E-Gen 병상 값이 없습니다 — 만실이 아니라 데이터가 없는 것" />;
  if (available <= 0) return <StatBox label="병상" value="없음" bg={AD.redSoft} fg={AD.red} title={stale ? "1일 넘게 갱신 안 된 값" : undefined} />;
  return <StatBox label={stale ? "병상 · 1일↑" : "병상"} value={`${available}석`} bg={AD.limeSoft} fg={AD.lime} title={stale ? "1일 넘게 갱신 안 된 값" : undefined} />;
}

function Skeletons({ from, count }: { from: number; count: number }) {
  return (
    <>
      {Array.from({ length: count }, (_, i) => (
        <div key={i} style={{ ...cardBase, gap: 10, background: AD.skeleton, border: `1px dashed ${AD.gray}` }}>
          <div style={{ fontSize: 13.5, fontWeight: 700, color: AD.muted }}>후보 {from + i}</div>
          <div style={{ height: 10, width: "50%", background: AD.line, borderRadius: 5 }} />
          <div style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))", gap: 8 }}>
            {[0, 1, 2].map((k) => <div key={k} style={{ height: 44, background: "#EEF0F4", borderRadius: 12 }} />)}
          </div>
          <div style={{ height: 10, width: "70%", background: AD.line, borderRadius: 5 }} />
          <div style={{ marginTop: "auto", height: 44, background: AD.line, borderRadius: 14 }} />
        </div>
      ))}
    </>
  );
}

function ListShell({ title, sub, children, footer }: { title?: ReactNode; sub?: ReactNode; children: ReactNode; footer?: ReactNode }) {
  return (
    <section style={{ flex: "none", display: "flex", flexDirection: "column", gap: 6, minWidth: 0 }}>
      <div style={{ display: "flex", flexWrap: "wrap", alignItems: "baseline", gap: "4px 12px", padding: "0 4px" }}>
        <div style={{ fontSize: 16, fontWeight: 700, color: AD.navy }}>병원 후보 리스트</div>
        {title && <div style={{ color: AD.ink3, fontSize: 12 }}>{title}</div>}
        <div style={{ color: AD.muted, fontSize: 11.5 }}>hv1 · hvec · hv2</div>
        {sub && <div style={{ color: AD.sub, fontSize: 11.5, whiteSpace: "normal" }}>{sub}</div>}
        {footer && <div style={{ marginLeft: "auto" }}>{footer}</div>}
      </div>
      <div
        className="amb-hscroll"
        style={{ display: "flex", alignItems: "stretch", gap: 14, overflowX: "auto", overflowY: "hidden", scrollSnapType: "x proximity", paddingBottom: 10 }}
      >
        {children}
      </div>
    </section>
  );
}

// 병원이 "승인"(후보 등록) 응답을 보내야만 버튼이 활성화된다. 버튼을 누르면 그 자리에서
// 바로 이송 승인(final_approval)이 전송된다 — 별도의 "선택 → 하단에서 최종 승인" 2단계가 아니다.
export function HospitalCandidateListPanel({
  data,
  confirmedHospitalId,
  pendingHospitalId,
  scene,
  onApprove,
}: {
  data: HubMatchResult | null;
  // 매칭 결과가 오기 전 보여줄 현장 주변 후보(내비 도착 시간순, 규칙). 매칭 결과가 오면 쓰지 않는다.
  scene?: SceneCandidates | null;
  // hub가 confirmed로 돌려준 병원. 버튼을 누른 즉시가 아니라 hub 응답 기준이다(2026-10-01).
  confirmedHospitalId: string | null;
  // 이송 승인을 눌렀지만 hub 응답을 아직 못 받은 병원 — "확정 요청 중"으로 보여준다.
  pendingHospitalId: string | null;
  onApprove: (hospitalId: string) => void;
}) {
  // 병상 신뢰도의 실시간 감쇠용 시계. hub가 곡선 파라미터(predT·bornAt·sigma)를
  // 보내주므로, 다음 브로드캐스트(60초 재계산)를 기다리지 않고 매초 확률을 다시
  // 계산해 그린다 — "정보가 낡아가는 것"이 화면에서 눈으로 보이게 하는 장치.
  const [nowMs, setNowMs] = useState(() => Date.now());
  // 이송이 확정되면 확정 병원만 보이고 나머지는 접는다(2026-10-03) — 병원으로 가는 동안 주변 병원이 계속 떠 있을
  // 이유가 없다. 다만 "이동 중에도 새 병원이 승인하면 재선택"할 수 있어야 해서 펼칠 수 있게 남긴다.
  const [showOthers, setShowOthers] = useState(false);
  useEffect(() => {
    const timer = setInterval(() => setNowMs(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);

  // ── 매칭 전: 현장 주변 후보(도착 시간순) ──
  if (!data && scene) {
    return (
      <ListShell
        title={<><b style={{ fontWeight: 700, color: AD.blue }}>Zone {scene.zoneActive.join(", ")}</b> · 환자 정보 전 도착 시간순 · {scene.hospitals.length}곳</>}
        sub={
          scene.reportedSymptom
            ? `1차 신고(${scene.reportedSymptom}${scene.reportedSeverity === "high" ? " · 중증 의심" : scene.reportedSeverity === "low" ? " · 경증" : ""}) 기반 가추천 — 통화가 끝나면 진료과 적합도까지 반영한 확정 순위로 바뀝니다.`
            : "통화가 끝나면 진료과·이동시간 기준 순위와 병원 응답으로 바뀝니다."
        }
      >
        {/* 첫 연락 추천을 맨 앞에(2026-10-05 요청), 나머지는 hub가 보낸 도착 시간순 그대로 */}
        {[...scene.hospitals.filter((h) => h.firstCallRecommended), ...scene.hospitals.filter((h) => !h.firstCallRecommended)].map((h) => {
          // 병상 신뢰도(AI) — 매칭 결과 카드와 같은 실시간 감쇠. 없는 병원은 '—'(fail-soft, Optional 패턴).
          const rel = h.bedReliability ? liveBedReliability(h.bedReliability, nowMs) : null;
          const tone = rel ? validTone(rel.rArrive) : { bg: AD.chip, fg: AD.ink3 };
          const doctors = h.specialties?.reduce((sum, s) => sum + (s.doctorCount ?? 0), 0) ?? 0;
          return (
            <div key={h.hospitalId} style={{ ...cardBase, border: h.firstCallRecommended ? `2px solid ${AD.green}` : `1px solid ${AD.control}` }}>
              <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 10 }}>
                <div style={{ minWidth: 0 }}>
                  <div style={{ fontSize: 13.5, fontWeight: 700, color: AD.navy }}>{h.name}</div>
                  <div style={{ fontSize: 12, color: AD.ink3 }} title={distanceTitle(h)}>
                    <b style={{ fontWeight: 500, color: AD.ink }}>{distanceLabel(h)}</b>
                    {h.etaMin != null && <> · ETA <b style={{ fontWeight: 500, color: AD.ink }}>{h.etaMin}분</b></>}
                  </div>
                </div>
                {h.firstCallRecommended ? (
                  <span
                    style={pill(AD.greenSoft, AD.green, 700)}
                    title="빈 병상이 확인된 후보 중 도착 시점 유효 확률(AI)이 가장 높은 병원 — 첫 통화 상대 제안이며 목록 순서(도착 시간순)는 그대로입니다."
                  >
                    첫 연락 추천
                  </span>
                ) : (
                  <span style={pill(AD.chip, AD.ink3, 700)}>통화 전</span>
                )}
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))", gap: 8 }}>
                {bedBox(h.availableBedCount, h.bedCountUnknown)}
                <StatBox
                  label="AI 유효"
                  value={rel ? `${Math.round(rel.rArrive * 100)}%${h.bedReliability?.confirmedAgeSec != null ? " ✓" : ""}` : "—"}
                  bg={tone.bg}
                  fg={tone.fg}
                  title={rel && h.bedReliability ? `지금 유효 ${Math.round(rel.authority * 100)}% · ${h.bedReliability.modelTag}` : "병상 신뢰도 모델 미연동"}
                />
                <StatBox label="전문의" value={doctors > 0 ? `${doctors}명` : "—"} bg={AD.chip} fg={AD.ink3} valueColor={AD.navy} />
              </div>
              {/* 매칭 전에도 고르는 데 필요한 정보는 다 띄운다(2026-10-04): 등급·진료과. 적합도만은 통화 후에 계산된다. */}
              <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 6, minHeight: 22 }}>
                {h.specialties && h.specialties.length > 0 && (
                  <Chip bg={AD.blueSoft} fg={AD.blue}>
                    {h.specialties.slice(0, 3).map((s) => s.department).join("·")}
                    {h.specialties.length > 3 ? ` 외 ${h.specialties.length - 3}과` : ""}
                  </Chip>
                )}
                {h.emergencyLevel && h.emergencyLevel.endsWith("센터") && <Chip>{h.emergencyLevel}</Chip>}
              </div>
              <button type="button" disabled style={approveButton("disabled")}>통화 후 병원 응답을 받으면 승인</button>
            </div>
          );
        })}
      </ListShell>
    );
  }

  if (!data) {
    return (
      <ListShell title="수신 대기 중">
        <Skeletons from={1} count={8} />
      </ListShell>
    );
  }

  const focusConfirmed = confirmedHospitalId != null && data.hospitals.some((h) => h.hospitalId === confirmedHospitalId);
  const hiddenCount = focusConfirmed ? data.hospitals.length - 1 : 0;
  // 병원 승인이 오면 승인 병원 중 최상위(hub 순위)를 "추천"으로 표시한다(2026-10-04).
  // 선착순 자동 확정이 아니라 추천 + 탭 한 번 — "최종 결정은 사람" 원칙. hub가 승인
  // 병원을 위로 올려 보내므로(rank_key) 목록에서 처음 만나는 approved가 곧 추천이다.
  const recommendedId = confirmedHospitalId == null
    ? data.hospitals.find((h) => h.status === "approved")?.hospitalId ?? null
    : null;
  const visible = data.hospitals.filter((hospital) => !focusConfirmed || showOthers || hospital.hospitalId === confirmedHospitalId);
  const zoneMax = Math.max(1, ...data.zoneActive);

  // 요청 범위(존)는 목록 머리글의 "Zone 1~N"으로만 보인다 — 보라색 존 구분 카드는 2026-10-05 요청으로 뺐다.
  const items: ReactNode[] = [];
  for (const hospital of visible) {
    items.push(
      <CandidateCard
        key={hospital.hospitalId}
        hospital={hospital}
        nowMs={nowMs}
        confirmed={hospital.hospitalId === confirmedHospitalId}
        requesting={hospital.hospitalId === pendingHospitalId && hospital.hospitalId !== confirmedHospitalId}
        recommended={hospital.hospitalId === recommendedId}
        onApprove={onApprove}
      />,
    );
  }

  return (
    <ListShell
      title={
        focusConfirmed
          ? <>이송 확정 병원으로 이동 중</>
          : <><b style={{ fontWeight: 700, color: AD.blue }}>{zoneMax > 1 ? `Zone 1~${zoneMax}` : "Zone 1"}</b> · 현장 반경 {zoneMax * 5}km · {data.hospitals.length}곳</>
      }
      footer={
        hiddenCount > 0 ? (
          <button
            type="button"
            onClick={() => setShowOthers((v) => !v)}
            style={{ minHeight: 32, padding: "0 12px", borderRadius: 999, border: `1px dashed ${AD.gray}`, background: "#FFFFFF", color: AD.ink3, fontSize: 12, cursor: "pointer" }}
          >
            {showOthers ? "다른 후보 접기" : `다른 후보 ${hiddenCount}곳 보기 (재선택할 때)`}
          </button>
        ) : undefined
      }
    >
      {items}
      {!focusConfirmed && visible.length < 4 && <Skeletons from={visible.length + 1} count={4 - visible.length} />}
    </ListShell>
  );
}

function approveButton(tone: "approve" | "confirmed" | "disabled" | "requesting"): CSSProperties {
  const base: CSSProperties = {
    width: "100%", minHeight: 44, borderRadius: 14, fontWeight: 700, fontSize: 14, fontFamily: "inherit", marginTop: "auto",
  };
  if (tone === "approve") return { ...base, background: AD.approve, color: "#FFFFFF", border: 0, cursor: "pointer" };
  if (tone === "confirmed") return { ...base, background: AD.greenSoft, color: AD.green, border: `2px solid ${AD.green}`, cursor: "default" };
  if (tone === "requesting") return { ...base, background: AD.orangeSoft, color: AD.approve, border: `1px solid ${AD.approve}`, cursor: "wait" };
  return { ...base, background: AD.chip, color: AD.muted, border: 0, cursor: "not-allowed", fontSize: 12.5 };
}

function CandidateCard({
  hospital, nowMs, confirmed, requesting, recommended, onApprove,
}: {
  hospital: HospitalCandidate;
  nowMs: number;
  confirmed: boolean;
  requesting: boolean;
  recommended: boolean;
  onApprove: (hospitalId: string) => void;
}) {
  const approvable = hospital.status === "approved" || hospital.status === "confirmed";
  const statusKey: HospitalStatus = hospital.unavailableReason ? "rejected" : hospital.status;
  const statusText = requesting
    ? "확정 요청 중"
    : hospital.unavailableReason
      ? `수용 불가 · ${unavailableReasonLabel(hospital.unavailableReason)}`
      : hospital.status === "rejected" && hospital.rejectReason
        ? `${STATUS_LABEL.rejected} · ${rejectionReasonLabel(hospital.rejectReason)}`
        : STATUS_LABEL[hospital.status];
  const statusPill = STATUS_PILL[statusKey];

  // 병상 숫자 자체의 유효 확률(infosurv 생존모델, AI) — 매초 감쇠 재계산. 병원이 직접 "현재 정보 확인"을 누른 값이면 ✓
  const live = hospital.bedReliability ? liveBedReliability(hospital.bedReliability, nowMs) : null;
  const tone = live ? validTone(live.rArrive) : { bg: AD.chip, fg: AD.ink3 };
  const humanConfirmed = hospital.bedReliability?.confirmedAgeSec != null;
  const doctors = hospital.specialtyMatch.doctorCount;
  // 배후진료 역량(수술실·입원실·소아)의 유효 확률 — 응급실 칸과 같은 모델 계열(AI), 같은 실시간 감쇠
  const byType = hospital.bedReliabilityByType && Object.keys(hospital.bedReliabilityByType).length > 0
    ? Object.entries(hospital.bedReliabilityByType)
        .map(([field, br]) => `${BED_FIELD_LABEL[field] ?? field} ${Math.round(liveBedReliability(br, nowMs).rArrive * 100)}%`)
        .join(" · ")
    : null;
  const bonusTitle = hospital.bonusReasons?.length ? `순위 가산: ${hospital.bonusReasons.join(" · ")}` : undefined;

  return (
    <div
      style={{
        ...cardBase,
        border: confirmed ? `3px solid ${AD.green}` : recommended ? `2px solid ${AD.approve}` : `1px solid ${AD.control}`,
        opacity: statusKey === "rejected" && !confirmed ? 0.72 : 1,
      }}
    >
      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 10 }}>
        <div style={{ minWidth: 0 }}>
          <div
            style={{ fontSize: 13.5, fontWeight: 700, color: AD.navy }}
            // 순위 점수(finalScore) 설명 — 그동안 안 보이던 내부 값의 투명화(2026-10-04)
            title={hospital.finalScore != null ? `순위 점수 ${hospital.finalScore.toFixed(3)} — 진료과 적합도 0.6 + 이동시간 0.4 (전문성·등급 가산, 이송 중 부하 반영)` : undefined}
          >
            {hospital.name}
          </div>
          <div style={{ fontSize: 12, color: AD.ink3 }} title={distanceTitle(hospital)}>
            <b style={{ fontWeight: 500, color: AD.ink }}>{distanceLabel(hospital)}</b>
            {hospital.etaMin != null ? (
              <> · ETA <b style={{ fontWeight: 500, color: AD.ink }}>{hospital.etaMin}분</b></>
            ) : hospital.travelMin != null ? (
              <> · 약 {Math.round(hospital.travelMin)}분(직선 추정)</>
            ) : null}
          </div>
        </div>
        <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 4 }}>
          <span style={{ ...pill(statusPill.bg, statusPill.fg, 700), maxWidth: 150, overflow: "hidden", textOverflow: "ellipsis" }} title={statusText}>
            {statusText}
          </span>
          {recommended && (
            <span style={pill(AD.orangeSoft, AD.approve, 700)} title="병원이 승인한 곳 중 순위 최상위 — 이송 승인은 구급대원의 판단입니다">
              추천
            </span>
          )}
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))", gap: 8 }}>
        {bedBox(hospital.availableBedCount, hospital.bedCountUnknown, hospital.bedDataStale)}
        <StatBox
          label="AI 유효"
          value={live ? `${Math.round(live.rArrive * 100)}%${humanConfirmed ? " ✓" : ""}` : "—"}
          bg={tone.bg}
          fg={tone.fg}
          title={live && hospital.bedReliability ? `도착 시 유효 확률 · 지금 유효 ${Math.round(live.authority * 100)}%${humanConfirmed ? " · 병원이 직접 확인한 값" : ""} · ${hospital.bedReliability.modelTag}` : "병상 신뢰도 모델 미연동"}
        />
        <StatBox label="전문의" value={doctors ? `${doctors}명` : "—"} bg={AD.chip} fg={AD.ink3} valueColor={AD.navy} />
      </div>

      <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 6, minHeight: 22 }}>
        {/* 적합도 표기(2026-10-04 구분): "정보 미상"(병원 진료과 데이터 없음)과 "낮음"을 나눠 회색으로 가라앉힌다.
            어느 쪽이든 후보에서 빼지는 않는다 — 잘못 걸러내는 게 더 위험하다는 뺑뺑이 방지 원칙. */}
        {hospital.specialtyMatch.department == null ? (
          <Chip title="병원 진료과 데이터가 없어 적합도를 계산하지 못했습니다 — 거리 기준으로만 순위에 남습니다(제외하지 않음)">진료과 정보 미상</Chip>
        ) : hospital.specialtyMatch.basis !== "exact" && hospital.specialtyMatch.score < 0.3 ? (
          <Chip title={`적합도가 낮지만 후보에서 제외하지 않습니다(뺑뺑이 방지)${bonusTitle ? ` · ${bonusTitle}` : ""}`}>
            {hospital.specialtyMatch.department} · 적합도 낮음 {Math.round(hospital.specialtyMatch.score * 100)}%
          </Chip>
        ) : (
          <Chip bg={AD.blueSoft} fg={AD.blue} title={bonusTitle}>
            {hospital.specialtyMatch.department} ·{" "}
            {hospital.specialtyMatch.basis === "exact" ? "필요 진료과 일치" : `적합도 ${Math.round(hospital.specialtyMatch.score * 100)}%`}
          </Chip>
        )}
        {hospital.emergencyLevel && hospital.emergencyLevel.endsWith("센터") && <Chip>{hospital.emergencyLevel}</Chip>}
        {/* 수용 불가 신고(declared_no 강등) — 제외하지 않고 순위만 내리는 원칙의 가시화(2026-10-04) */}
        {hospital.demoteReasons?.includes("declared_no") && (
          <Chip bg={AD.redSoft} fg={AD.red} title="이 질환군은 수용 불가라고 병원이 E-Gen에 신고한 상태 — 후보에서 빼지 않고 순위만 뒤로 내립니다">
            수용 불가 신고
          </Chip>
        )}
        {/* 병원이 E-Gen에 이 질환군 차단 메시지를 걸어둠(severe_blocked 강등, 2026-10-07) — 신고와 같은 원칙으로 순위만 내린다 */}
        {hospital.demoteReasons?.includes("severe_blocked") && (
          <Chip bg={AD.redSoft} fg={AD.red} title="이 질환군은 지금 못 받는다고 병원이 E-Gen 메시지를 걸어둔 상태 — 후보에서 빼지 않고 순위만 뒤로 내립니다">
            병원 차단 메시지
          </Chip>
        )}
        {(hospital.inFlightCount ?? 0) > 0 && (
          <Chip bg={AD.orangeSoft} fg={AD.orange} title={hospital.loadReason ?? "이 병원으로 확정돼 이송 중인 다른 환자 — 그만큼 순위가 뒤로 밀린다"}>
            이송 중 {hospital.inFlightCount}건{hospital.loadPenaltyMin ? ` · 순위 +${hospital.loadPenaltyMin}분` : ""}
          </Chip>
        )}
        {/* info-v2가 심평원 대조로 판단한 신뢰도(설명용) — 데이터가 없으면 칩 자체를 숨긴다 */}
        {hospital.reliability && (
          <Chip
            bg={hospital.reliability.confidence === "high" ? AD.greenSoft : AD.chip}
            fg={hospital.reliability.confidence === "high" ? AD.green : AD.ink3}
            title={hospital.reliability.basis.length > 0 ? `근거: ${hospital.reliability.basis.join(" · ")}` : undefined}
          >
            {hospital.reliability.group} · {CONFIDENCE_LABEL[hospital.reliability.confidence]}
          </Chip>
        )}
        {/* 매칭된 질환군의 수용가능 신고가 언제 적 것인지(규칙 — E-Gen엔 신고 시각이 없어 info의 스냅샷 추적만이 아는 값) */}
        {hospital.severeFreshness && (
          <Chip>
            {hospital.severeFreshness.value === "Y" ? "수용가능 신고" : "수용불가 신고"}{" "}
            {formatDeclarationAge(hospital.severeFreshness.ageSec, hospital.severeFreshness.ageIsMin)}
          </Chip>
        )}
      </div>

      <AcceptanceMessages messages={hospital.acceptanceMessages} />

      <div style={{ minHeight: 16, fontSize: 11.5, color: AD.sub, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={byType ?? undefined}>
        {byType ? `AI · ${byType}` : live ? `AI · 응급실 지금 유효 ${Math.round(live.authority * 100)}%` : "AI · 배후진료 신뢰도 정보 없음"}
      </div>

      {confirmed ? (
        <button type="button" disabled style={approveButton("confirmed")}>이송 확정됨</button>
      ) : requesting ? (
        <button type="button" disabled style={approveButton("requesting")}>확정 요청 중…</button>
      ) : approvable ? (
        <button type="button" onClick={() => onApprove(hospital.hospitalId)} style={approveButton("approve")}>
          이송 승인
        </button>
      ) : (
        <button type="button" disabled style={approveButton("disabled")}>
          {hospital.excluded ? "이 사건에서 제외됨" : statusKey === "rejected" ? "수용 불가" : "병원 응답 대기"}
        </button>
      )}
    </div>
  );
}

/** 병원이 E-Gen에 걸어둔 수용 제한 메시지(규칙 기반, 2026-10-07). 이 환자에 해당하는 것만 펼쳐 보이고(최대 2건),
 *  나머지는 건수만 — 원문은 툴팁에 다 있다. 메시지가 없으면 아무것도 그리지 않는다(구버전 hub 포함). */
function AcceptanceMessages({ messages }: { messages?: AcceptanceMessage[] | null }) {
  if (!messages?.length) return null;
  const matched = messages.filter((m) => m.matched);
  const others = messages.length - matched.length;
  const line = (m: AcceptanceMessage) =>
    `${m.kind === "severe" ? m.diseaseName ?? m.diseaseGroup ?? "중증질환" : m.department ?? "응급실"} — ${m.message}`;
  return (
    <div
      style={{ display: "flex", flexDirection: "column", gap: 2, fontSize: 11.5 }}
      title={["병원 공지(E-Gen 메시지 · 규칙)", ...messages.map(line)].join("\n")}
    >
      {matched.slice(0, 2).map((m, i) => (
        <div key={i} style={{ color: m.kind === "severe" ? AD.red : AD.ink, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          병원 공지 · {line(m)}
        </div>
      ))}
      {(matched.length > 2 || others > 0) && (
        <div style={{ color: AD.sub }}>
          {[
            matched.length > 2 ? `이 환자 관련 공지 ${matched.length - 2}건 더` : null,
            others > 0 ? `다른 진료 공지 ${others}건` : null,
          ]
            .filter(Boolean)
            .join(" · ")}
        </div>
      )}
    </div>
  );
}
