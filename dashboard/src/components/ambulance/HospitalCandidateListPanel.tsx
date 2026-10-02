"use client";

import { useEffect, useState } from "react";
import { css, cx } from "styled-system/css";
import { hospitalStatusBadge } from "styled-system/recipes";
import { Tag } from "@/components/hospital/Tag";
import { mintButtonStyle, primaryButtonStyle } from "@/components/ui/button-styles";
import { thinScrollbarStyle } from "@/components/ui/scrollbar-style";
import { formatDeclarationAge, liveBedReliability } from "@/lib/bedReliability";
import type { HospitalStatus, HubMatchResult, ReliabilityConfidence, SceneCandidates } from "@/types/dashboard";

// 공용 Panel은 height:100%만 두고 minHeight/overflow는 안 잡아서, 그리드 셀이
// 콘텐츠(병원 몇 개)만큼 계속 늘어나는 걸 막지 못했다 — maxHeight를 목록에
// 고정값으로 줘봤지만 이번엔 그 값이 실제 셀 높이보다 작아서 패널 하단에
// 빈 공간이 남았다(2026-08-11 두 번 다 확인됨). Panel을 공용으로 고치면 다른
// 패널에도 영향이 갈 수 있어서, 이 컴포넌트만 자체 마크업(같은 시각 스타일 +
// minHeight:0 + overflow:hidden)으로 바꿔 셀 높이에 정확히 맞추고, 넘치는 건
// 안쪽 <ul>이 스크롤로 흡수하게 한다.
function ListPanelShell({
  subtitle,
  children,
}: {
  subtitle?: string;
  children: React.ReactNode;
}) {
  return (
    <section
      className={css({
        display: "flex",
        flexDirection: "column",
        height: "100%",
        minHeight: "0",
        overflow: "hidden",
        borderWidth: "1px",
        borderColor: "line",
        borderRadius: "panel",
        backgroundColor: "surface",
        padding: "4",
        minWidth: "0",
      })}
    >
      <header
        className={css({
          display: "flex",
          alignItems: "flex-start",
          justifyContent: "space-between",
          gap: "2.5",
          paddingBottom: "3",
          marginBottom: "3",
          borderBottomWidth: "1px",
          borderColor: "line",
          flexShrink: "0",
        })}
      >
        <h2 className={css({ fontSize: "sm", fontWeight: "semibold", letterSpacing: "-0.01em", color: "ink" })}>
          병원 후보 리스트
          {subtitle && (
            <span className={css({ display: "block", fontSize: "xs", fontWeight: "normal", color: "ink", marginTop: "0.5" })}>
              {subtitle}
            </span>
          )}
        </h2>
        <Tag source="rule">hv1 · hvec · hv2</Tag>
      </header>
      {children}
    </section>
  );
}

const STATUS_LABEL: Record<HospitalStatus, string> = {
  pending: "판단 대기",
  approved: "후보 등록",
  rejected: "수용 불가",
  confirmed: "이송 확정",
};

// 순서는 hub가 보낸 hospitals[] 순서를 그대로 쓴다(2026-10-01). 예전엔 여기서 병상 유무 →
// 승인 여부 → 진료과 점수 → 직선거리로 다시 정렬해서, hub가 정한 순위(카카오 ETA 기반
// 이동시간 점수·수용 불가 신고 내림·오래된 병상 값 예외)가 화면에 전혀 반영되지 않았다.
// "확정·승인 병원을 위로, 거절 병원은 맨 뒤" 규칙도 이제 hub의 scoring.rank_key()에 있다.
// 거절해도 목록에서 없애지 않는 원칙은 그대로다.

const deptChipStyle = css({
  display: "inline-flex",
  alignItems: "center",
  fontSize: "xs",
  fontWeight: "semibold",
  color: "navy",
  backgroundColor: "navySoft",
  paddingX: "2",
  paddingY: "0.5",
  borderRadius: "chip",
});

const bedChipAvailableStyle = css({
  display: "inline-flex",
  alignItems: "center",
  fontSize: "xs",
  fontWeight: "semibold",
  color: "mint",
  backgroundColor: "mintSoft",
  paddingX: "2",
  paddingY: "0.5",
  borderRadius: "chip",
});

const bedChipEmptyStyle = css({
  display: "inline-flex",
  alignItems: "center",
  fontSize: "xs",
  fontWeight: "semibold",
  color: "coral",
  backgroundColor: "coralSoft",
  paddingX: "2",
  paddingY: "0.5",
  borderRadius: "chip",
});

// "확인된 만실"(coral)과는 색을 다르게 둔다 — 미상은 병원에 자리가 없다고 확정된
// 게 아니라 데이터가 아직 없는 것뿐이라, 만실과 같은 경고색으로 보이면 구급대원이
// 실제로는 받아줄 수도 있는 병원을 스스로 후보에서 빼게 된다(CLAUDE.md 참고).
const bedChipUnknownStyle = css({
  display: "inline-flex",
  alignItems: "center",
  fontSize: "xs",
  fontWeight: "semibold",
  color: "ink2",
  backgroundColor: "surfaceSub",
  paddingX: "2",
  paddingY: "0.5",
  borderRadius: "chip",
});

// info-v2(hospital_score) 신뢰도 판정 배지. severityBadge(high=coral)와 반대로
// "high confidence"는 좋은 신호라 mint를 쓴다 — 색 의미가 severity와 정반대라
// 그 recipe를 재사용하지 않고 이 패널 안에서만 쓰는 별도 칩으로 둔다.
const CONFIDENCE_CHIP_STYLE: Record<ReliabilityConfidence, string> = {
  high: css({
    display: "inline-flex",
    alignItems: "center",
    fontSize: "xs",
    fontWeight: "semibold",
    color: "mint",
    backgroundColor: "mintSoft",
    paddingX: "2",
    paddingY: "0.5",
    borderRadius: "chip",
  }),
  medium: css({
    display: "inline-flex",
    alignItems: "center",
    fontSize: "xs",
    fontWeight: "semibold",
    color: "ink2",
    backgroundColor: "surfaceSub",
    paddingX: "2",
    paddingY: "0.5",
    borderRadius: "chip",
  }),
  low: css({
    display: "inline-flex",
    alignItems: "center",
    fontSize: "xs",
    fontWeight: "semibold",
    color: "ink3",
    backgroundColor: "surfaceSub",
    paddingX: "2",
    paddingY: "0.5",
    borderRadius: "chip",
  }),
};

const CONFIDENCE_LABEL: Record<ReliabilityConfidence, string> = {
  high: "신뢰도 높음",
  medium: "신뢰도 보통",
  low: "신뢰도 낮음",
};

const reliabilityBasisStyle = css({
  fontSize: "xs",
  color: "ink3",
  marginTop: "0.5",
});

// 병상 신뢰도(infosurv, AI) 칩 — "도착 시 유효 확률"을 띠로 색 구분한다.
// 확률의 절대값이 의미 있는(캘리브레이트된) 값이라 %를 그대로 노출한다.
// ≥80%는 mint(믿고 출발), 50~80%는 중립(참고), <50%는 coral(도착 전 재확인 권장).
const bedRelHighStyle = css({
  display: "inline-flex",
  alignItems: "center",
  fontSize: "xs",
  fontWeight: "semibold",
  color: "mint",
  backgroundColor: "mintSoft",
  paddingX: "2",
  paddingY: "0.5",
  borderRadius: "chip",
  fontVariantNumeric: "tabular-nums",
});

const bedRelMidStyle = css({
  display: "inline-flex",
  alignItems: "center",
  fontSize: "xs",
  fontWeight: "semibold",
  color: "ink2",
  backgroundColor: "surfaceSub",
  paddingX: "2",
  paddingY: "0.5",
  borderRadius: "chip",
  fontVariantNumeric: "tabular-nums",
});

const bedRelLowStyle = css({
  display: "inline-flex",
  alignItems: "center",
  fontSize: "xs",
  fontWeight: "semibold",
  color: "coral",
  backgroundColor: "coralSoft",
  paddingX: "2",
  paddingY: "0.5",
  borderRadius: "chip",
  fontVariantNumeric: "tabular-nums",
});

function bedReliabilityChipStyle(rArrive: number): string {
  if (rArrive >= 0.8) return bedRelHighStyle;
  if (rArrive >= 0.5) return bedRelMidStyle;
  return bedRelLowStyle;
}

// 첫 연락 추천(2026-10-03) 배지 — hub가 현장 후보(scene_candidates) 중 "빈 병상이
// 확인되고 도착 시점 유효 확률(AI, rArrive)이 가장 높은 한 곳"에 표시해 보낸다.
// 첫 통화 상대 제안일 뿐 순위(거리순)는 바꾸지 않으므로, 줄 순서가 아니라 배지로만
// 드러낸다. 좋은 신호라 mint — 테두리를 둘러 일반 칩과 구분한다.
const firstCallBadgeStyle = css({
  display: "inline-flex",
  alignItems: "center",
  fontSize: "xs",
  fontWeight: "bold",
  color: "mint",
  backgroundColor: "mintSoft",
  borderWidth: "1px",
  borderColor: "mint",
  paddingX: "2",
  paddingY: "0.5",
  borderRadius: "chip",
  flexShrink: "0",
});

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

// 확장 필드 요약 칩 — 배후진료 역량(수술실·입원실)의 유효 확률을 한 칩에
// 모아 보여준다. 개별 칩으로 펼치면 카드가 4~5칩으로 어지러워져 묶었다.
const bedRelByTypeChipStyle = css({
  display: "inline-flex",
  alignItems: "center",
  fontSize: "xs",
  fontWeight: "medium",
  color: "ink2",
  backgroundColor: "surfaceSub",
  paddingX: "2",
  paddingY: "0.5",
  borderRadius: "chip",
  fontVariantNumeric: "tabular-nums",
});

// 중증신고 신선도(규칙) 칩 — 확률이 아니라 사실(신고가 언제 적 것인지)이라 중립색.
const severeFreshnessChipStyle = css({
  display: "inline-flex",
  alignItems: "center",
  fontSize: "xs",
  fontWeight: "medium",
  color: "ink2",
  backgroundColor: "surfaceSub",
  paddingX: "2",
  paddingY: "0.5",
  borderRadius: "chip",
});

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
  // 매칭 결과가 오기 전 보여줄 현장 주변 후보(거리순, 규칙). 매칭 결과가 오면 쓰지 않는다.
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
  useEffect(() => {
    const timer = setInterval(() => setNowMs(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);

  if (!data && scene) {
    return (
      <ListPanelShell subtitle={`Zone ${scene.zoneActive.join(", ")} · 환자 정보 전 거리순`}>
        <p className={css({ color: "ink3", fontSize: "xs", marginBottom: "2" })}>
          통화가 끝나면 진료과·이동시간 기준 순위와 병원 응답으로 바뀝니다.
        </p>
        <ul
          className={cx(
            css({ display: "flex", flexDirection: "column", gap: "1.5", flex: "1", minHeight: "0", overflowY: "auto" }),
            thinScrollbarStyle,
          )}
        >
          {scene.hospitals.map((h) => {
            // 병상 신뢰도(AI) — 매칭 결과 카드와 같은 실시간 감쇠 칩. 없는 병원은
            // 칩만 안 그린다(fail-soft, Optional 패턴).
            const rel = h.bedReliability ? liveBedReliability(h.bedReliability, nowMs) : null;
            return (
              <li
                key={h.hospitalId}
                className={css({
                  display: "flex",
                  flexDirection: "column",
                  gap: "1",
                  paddingX: "3",
                  paddingY: "2",
                  borderWidth: "1px",
                  borderColor: h.firstCallRecommended ? "mint" : "line",
                  borderRadius: "field",
                  fontSize: "sm",
                })}
              >
                <div className={css({ display: "flex", justifyContent: "space-between", alignItems: "center", gap: "2" })}>
                  <span className={css({ display: "inline-flex", alignItems: "center", gap: "1.5", fontWeight: "semibold", color: "ink", minWidth: "0" })}>
                    {h.name}
                    {h.firstCallRecommended && (
                      <span
                        className={firstCallBadgeStyle}
                        title="빈 병상이 확인된 후보 중 도착 시점 유효 확률(AI)이 가장 높은 병원 — 첫 통화 상대 제안이며 목록 순서(거리순)는 그대로입니다."
                      >
                        첫 연락 추천
                      </span>
                    )}
                  </span>
                  <span className={css({ color: "ink3", fontVariantNumeric: "tabular-nums", flexShrink: "0" })}>
                    {h.distanceKm}km · 병상 {h.bedCountUnknown ? "미상" : h.availableBedCount}
                  </span>
                </div>
                {rel && h.bedReliability && (
                  <div className={css({ display: "flex" })}>
                    <span
                      className={bedReliabilityChipStyle(rel.rArrive)}
                      title={`지금 유효 ${Math.round(rel.authority * 100)}%${h.bedReliability.confirmedAgeSec != null ? " · 병원이 직접 확인한 값" : ""} · ${h.bedReliability.modelTag}`}
                    >
                      AI · 도착 시 유효 {Math.round(rel.rArrive * 100)}%
                      {h.bedReliability.confirmedAgeSec != null ? " ✓" : ""}
                    </span>
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      </ListPanelShell>
    );
  }

  if (!data) {
    return (
      <ListPanelShell>
        <p className={css({ color: "ink3", fontSize: "sm" })}>수신 대기 중...</p>
      </ListPanelShell>
    );
  }

  const hospitals = data.hospitals.map((hospital) => ({
    hospital,
    confirmed: hospital.hospitalId === confirmedHospitalId,
    requesting: hospital.hospitalId === pendingHospitalId && hospital.hospitalId !== confirmedHospitalId,
  }));

  return (
    <ListPanelShell subtitle={`Zone ${data.zoneActive.join(", ")} 내 후보`}>
      {/* 병원이 몇 곳이든(거리·우선순위로 이미 정렬돼 오므로) 패널 자체가 늘어나지
          않고 이 목록 안에서만 스크롤되게 한다 — ListPanelShell이 셀 높이를 정확히
          지키므로(minHeight:0 + overflow:hidden), 여기는 남는 공간을 그대로
          차지하다가(flex:1) 넘칠 때만 스스로 스크롤하면 된다(고정 maxHeight 불필요). */}
      <ul
        className={cx(
          css({
            display: "flex",
            flexDirection: "column",
            gap: "2",
            flex: "1",
            minHeight: "0",
            overflowY: "auto",
          }),
          thinScrollbarStyle,
        )}
      >
        {hospitals.map(({ hospital, confirmed, requesting }) => {
          const approvable = hospital.status === "approved" || hospital.status === "confirmed";

          return (
            <li
              key={hospital.hospitalId}
              className={css({
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                gap: "2.5",
                paddingX: "3.5",
                paddingY: "2.5",
                borderRadius: "field",
                borderWidth: "1px",
                borderColor: confirmed ? "navy" : "line",
                backgroundColor: confirmed ? "navySoft" : "surface",
              })}
            >
              <div className={css({ display: "flex", flexDirection: "column", gap: "0.5", minWidth: "0" })}>
                <span className={css({ fontWeight: "semibold", fontSize: "sm", color: "ink" })}>
                  {hospital.name}
                </span>
                <span className={css({ fontSize: "sm", fontWeight: "medium", color: "ink" })}>
                  {hospital.distanceKm}km
                  {hospital.etaMin != null ? ` · ETA ${hospital.etaMin}분` : ""}
                </span>
                <div className={css({ display: "flex", gap: "1", flexWrap: "wrap" })}>
                  <span
                    className={deptChipStyle}
                    title={hospital.bonusReasons?.length ? `순위 가산: ${hospital.bonusReasons.join(" · ")}` : undefined}
                  >
                    {hospital.specialtyMatch.department} ·{" "}
                    {hospital.specialtyMatch.basis === "exact"
                      ? "필요 진료과 일치"
                      : `적합도 ${Math.round(hospital.specialtyMatch.score * 100)}%`}
                    {hospital.specialtyMatch.doctorCount ? ` · 전문의 ${hospital.specialtyMatch.doctorCount}명` : ""}
                  </span>
                  {hospital.emergencyLevel && hospital.emergencyLevel.endsWith("센터") && (
                    <span className={deptChipStyle}>{hospital.emergencyLevel}</span>
                  )}
                  <span
                    className={
                      hospital.bedCountUnknown
                        ? bedChipUnknownStyle
                        : hospital.availableBedCount > 0
                          ? bedChipAvailableStyle
                          : bedChipEmptyStyle
                    }
                  >
                    {hospital.bedCountUnknown
                      ? "병상 미상"
                      : hospital.availableBedCount > 0
                        ? `병상 ${hospital.availableBedCount}석`
                        : "병상 없음"}
                  </span>
                  {/* 순위(specialtyMatch·distanceKm)와는 별개의 설명용 정보 —
                      info-v2가 심평원 대조로 판단한 신뢰도. 이 병원에 해당
                      데이터가 없으면(구 feature/info 데이터 등) 칩 자체를 숨긴다. */}
                  {hospital.reliability && (
                    <span className={CONFIDENCE_CHIP_STYLE[hospital.reliability.confidence]}>
                      {hospital.reliability.group} · {CONFIDENCE_LABEL[hospital.reliability.confidence]}
                    </span>
                  )}
                  {/* 병상 숫자 자체의 유효 확률(infosurv 생존모델). 위 병상 칩이
                      "몇 석인가"라면 이건 "그 숫자가 도착 시점에도 사실일 확률".
                      AI 산출이라 규칙 기반 칩들과 구분되게 앞에 AI를 명시한다
                      (CLAUDE.md의 AI/규칙 시각 구분 원칙). 매초 감쇠 재계산. */}
                  {hospital.bedReliability &&
                    (() => {
                      const live = liveBedReliability(hospital.bedReliability, nowMs);
                      // 병원이 직접 "현재 정보 확인"을 누른 값이면 ✓로 표시 —
                      // 모델 추정만이 아니라 사람의 확인이 얹힌 확률이라는 뜻.
                      const confirmed = hospital.bedReliability.confirmedAgeSec != null;
                      return (
                        <span
                          className={bedReliabilityChipStyle(live.rArrive)}
                          title={`지금 유효 ${Math.round(live.authority * 100)}%${confirmed ? " · 병원이 직접 확인한 값" : ""} · ${hospital.bedReliability.modelTag}`}
                        >
                          AI · 도착 시 유효 {Math.round(live.rArrive * 100)}%
                          {confirmed ? " ✓" : ""}
                        </span>
                      );
                    })()}
                  {/* 배후진료 역량(수술실·입원실·소아)의 유효 확률 — 응급실
                      일반 칩과 같은 모델 계열(AI), 같은 실시간 감쇠. */}
                  {hospital.bedReliabilityByType &&
                    Object.keys(hospital.bedReliabilityByType).length > 0 && (
                      <span className={bedRelByTypeChipStyle}>
                        AI ·{" "}
                        {Object.entries(hospital.bedReliabilityByType)
                          .map(([field, br]) => {
                            const live = liveBedReliability(br, nowMs);
                            const label = BED_FIELD_LABEL[field] ?? field;
                            return `${label} ${Math.round(live.rArrive * 100)}%`;
                          })
                          .join(" · ")}
                      </span>
                    )}
                  {/* 매칭된 질환군의 수용가능 신고가 언제 적 것인지(규칙 — E-Gen엔
                      신고 시각이 없어 info의 스냅샷 추적만이 아는 값). */}
                  {hospital.severeFreshness && (
                    <span className={severeFreshnessChipStyle}>
                      {hospital.severeFreshness.value === "Y" ? "수용가능 신고" : "수용불가 신고"}{" "}
                      {formatDeclarationAge(
                        hospital.severeFreshness.ageSec,
                        hospital.severeFreshness.ageIsMin,
                      )}
                    </span>
                  )}
                </div>
                {hospital.reliability && hospital.reliability.basis.length > 0 && (
                  <p className={reliabilityBasisStyle}>근거: {hospital.reliability.basis.join(" · ")}</p>
                )}
              </div>

              <div className={css({ display: "flex", alignItems: "center", gap: "2", flexShrink: "0" })}>
                <span className={hospitalStatusBadge({ status: hospital.status })}>
                  {requesting ? "확정 요청 중" : STATUS_LABEL[hospital.status]}
                </span>
                <button
                  type="button"
                  disabled={!approvable || requesting}
                  onClick={() => onApprove(hospital.hospitalId)}
                  className={confirmed ? mintButtonStyle : primaryButtonStyle}
                >
                  {confirmed ? "승인 완료" : "이송 승인"}
                </button>
              </div>
            </li>
          );
        })}
      </ul>
    </ListPanelShell>
  );
}
