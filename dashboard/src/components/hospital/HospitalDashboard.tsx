"use client";

import { useState } from "react";
import { usePauseToast } from "@/components/ui/PauseToast";
import { css } from "styled-system/css";
import { HospitalTopBar } from "@/components/hospital/HospitalTopBar";
import { HospitalSelfInfoPanel } from "@/components/hospital/HospitalSelfInfoPanel";
import { CallStatusBanner } from "@/components/hospital/CallStatusBanner";
import { RequestCard, cardKind, kindMeta } from "@/components/hospital/RequestCard";
import { MapPanel } from "@/components/hospital/MapPanel";
import { HD } from "@/components/hospital/hospital-design";
import { useDashboardSocket } from "@/hooks/use-dashboard-socket";
import type { DashboardState, PreAlert, TransportAssessment } from "@/types/dashboard";

// 예비 고지 모달(2026-10-04) — 구급대가 출동한 순간 hub가 현장 존 안 후보 병원에 먼저
// 보내는 선(先) 경고. 실제 수용 요청이 오기 전에 "올 수 있다"를 알려 준비 시간을 벌어 준다.
// 실제 요청(match_result)이 도착하면 소켓 훅이 자동으로 지우므로, 여기선 표시와 [확인]만 한다.
function PreAlertModal({ alerts, onDismiss }: { alerts: PreAlert[]; onDismiss: (caseId: string) => void }) {
  if (alerts.length === 0) return null;
  return (
    <div
      className={css({
        position: "fixed", inset: "0", zIndex: "100",
        display: "flex", alignItems: "center", justifyContent: "center",
        backgroundColor: "rgba(22, 34, 46, 0.45)",
      })}
    >
      <div
        className={css({
          display: "flex", flexDirection: "column", gap: "3",
          width: "min(440px, 90vw)", backgroundColor: "surface",
          borderRadius: "panel", borderWidth: "2px", borderColor: "severity.medium",
          padding: "5", boxShadow: "0 12px 40px rgba(22,34,46,.35)", whiteSpace: "normal",
        })}
      >
        <h2 className={css({ fontSize: "md", fontWeight: "bold", color: "severity.medium" })}>
          ⚠️ 인근 사고 발생 — 구급대 출동 중
        </h2>
        {alerts.map((alert) => (
          <div key={alert.caseId} className={css({ display: "flex", flexDirection: "column", gap: "1" })}>
            <p className={css({ fontSize: "sm", color: "ink" })}>
              <b>{alert.ambulanceName ?? alert.apid}</b>가 본원에서{" "}
              {alert.distanceKm != null ? <b>약 {alert.distanceKm}km</b> : "인근"} 지점으로 출동했습니다.
            </p>
            {alert.reportedSymptom && (
              // 신고 전화에서 파악한 1차 증상 — 확정 정보가 아니라 '신고 내용'이다(현장 평가와 다를 수 있음)
              <p className={css({ fontSize: "sm", fontWeight: "semibold", color: "ink" })}>
                신고 증상: {alert.reportedSymptom}
                {alert.reportedSeverity === "high" ? " · 중증 의심" : alert.reportedSeverity === "medium" ? " · 중등증 의심" : ""}
                <span className={css({ fontSize: "2xs", color: "ink3", fontWeight: "normal" })}> (신고 내용 — 현장 평가와 다를 수 있음)</span>
              </p>
            )}
            <p className={css({ fontSize: "xs", color: "ink2" })}>
              현장 통화가 끝나면 환자 수용 요청이 올 수 있습니다 — 수용 가능 여부를 미리 확인해 주세요.
            </p>
          </div>
        ))}
        <button
          type="button"
          className={css({
            alignSelf: "flex-end", fontSize: "sm", fontWeight: "bold", color: "white",
            backgroundColor: "navy", borderRadius: "field", paddingX: "4", paddingY: "2", cursor: "pointer",
          })}
          onClick={() => alerts.forEach((alert) => onDismiss(alert.caseId))}
        >
          확인
        </button>
      </div>
    </div>
  );
}

// 이송 중 상태 변화 배너(2.5단계, 2026-10-04). hub가 이 병원으로 확정된 사건의
// notify 이상 판정만 보내준다(기록·보류는 안 옴 — 오경보보다 침묵). 도착 전에
// 환자 상태 변화를 미리 아는 게 목적이므로 최신 판정 하나만 띄운다. 규칙 기반.
function TransportAlertBanner({ assessments }: { assessments: TransportAssessment[] }) {
  const latest = assessments[assessments.length - 1];
  if (!latest) return null;
  const vitals = [
    latest.observation.sbp != null ? `혈압 ${latest.observation.sbp}${latest.observation.dbp != null ? `/${latest.observation.dbp}` : ""}` : null,
    latest.observation.hr != null ? `맥박 ${latest.observation.hr}` : null,
    latest.observation.rr != null ? `호흡 ${latest.observation.rr}` : null,
    latest.observation.spo2 != null ? `SpO2 ${latest.observation.spo2}%` : null,
    latest.observation.avpu != null ? `의식 ${latest.observation.avpu}` : null,
  ].filter(Boolean);
  const critical = latest.tier !== "notify";
  return (
    <div
      className={css({
        paddingX: "3",
        paddingY: "2",
        borderRadius: "field",
        borderWidth: "1px",
        borderColor: critical ? "coral" : "severity.medium",
        backgroundColor: critical ? "coralSoft" : "severity.medium.subtle",
        display: "flex",
        flexDirection: "column",
        gap: "0.5",
        whiteSpace: "normal",
      })}
    >
      <p className={css({ fontSize: "xs", fontWeight: "bold", color: critical ? "coral" : "severity.medium" })}>
        🚑 이송 중 상태 변화 · NEWS2 {latest.news2}
        {latest.si != null ? ` · 쇼크지수 ${latest.si}` : ""}
        {latest.observation.source === "voice" ? " · 이송 중 2차 통화" : ""}
        {latest.demo ? " · 가상 시나리오" : ""}
      </p>
      {vitals.length > 0 && (
        <p className={css({ fontSize: "xs", color: "ink" })}>
          {vitals.join(" · ")} ({latest.observation.measuredAt.slice(11, 19)} 측정)
        </p>
      )}
      {latest.reasons.length > 0 && (
        <p className={css({ fontSize: "xs", color: "ink2" })}>{latest.reasons[0]}</p>
      )}
    </div>
  );
}

/**
 * 미선택 통보 안내 문구를 만든다(2026-10-22).
 *
 * 아래 `myCases` 필터는 "다른 병원으로 이송이 확정된 사건"의 카드를 목록에서 뺀다(2026-08-11 결정). 그래서
 * 통보가 없으면 승인해 둔 카드가 **설명 없이 사라진다** — 수용 승낙은 빈 병상 확인이 아니라 처치 공간 확보·
 * 기존 진료 조정 같은 자원 선배정이므로, 왜 사라졌는지 알려 줘야 그 준비를 풀 수 있다(임상 자문 요구,
 * poc/CLINICAL_CONVERGENCE.md §4).
 *
 * 두 경로를 모두 받는다 — ① hub 푸시(`selection_released`, 탭이 떠 있을 때) ② 매칭 결과의 `notSelected`
 * 깃발(재접속·뒤늦게 연 탭은 푸시를 못 받고 따라잡기로만 받는다). 같은 사건으로 두 번 뜨지 않게 caseId로
 * 가른다. 승인이 풀린 건 아니다(status는 approved 그대로 — 이동 중 재선택 대상으로 남는다).
 */
function useSelectionNotice(
  state: { selectionReleased: DashboardState["selectionReleased"]; matchResults: DashboardState["matchResults"] },
  myHospitalId: string | null,
): { at: number; text: string } | null {
  const fromFlag = myHospitalId
    ? Object.values(state.matchResults).find((result) =>
        result.hospitals.some((h) => h.hospitalId === myHospitalId && h.notSelected),
      )
    : undefined;
  const caseId = state.selectionReleased?.caseId ?? fromFlag?.caseId ?? null;
  const confirmedName =
    state.selectionReleased?.confirmedHospitalName ??
    fromFlag?.hospitals.find((h) => h.status === "confirmed")?.name ??
    null;

  // `at`은 "새 안내인가"를 가르는 식별자일 뿐이라 시각이 아니라 증가하는 번호를 쓴다 — 렌더 중 Date.now()는
  // 순수하지 않아 eslint(react-hooks/purity)가 막고, 재렌더마다 값이 흔들려 토스트가 다시 뜰 수 있다.
  const [noticed, setNoticed] = useState<{ caseId: string; seq: number } | null>(null);
  if (caseId && confirmedName && caseId !== noticed?.caseId) {
    setNoticed((prev) => ({ caseId, seq: (prev?.seq ?? 0) + 1 }));
  }
  if (!noticed || !confirmedName) return null;
  return { at: noticed.seq, text: `${confirmedName}(으)로 이송이 확정됐습니다 — 귀원은 선택되지 않았습니다.` };
}

// 수용 요청 카드 정렬 — 같은 단계 안에서 위험한 순(2026-10-04)
const SEVERITY_RANK: Record<string, number> = { high: 0, medium: 1, low: 2 };

// 병원 대시보드는 병원 1곳 전용 화면이라 자신의 병원 ID(hpid)가 고정된다. 첫 페이지에서 병원 접근 코드(H-<hpid>)로
// 들어온 /hospital?id= 페이지가 이 컴포넌트를 그린다(2026-10-03 회의로 관제 지도와 분리). onClose를 주면 상단바에
// [닫기] 버튼이 생긴다(다른 화면 위에 띄울 때용, 지금은 쓰지 않음). 이 화면은 자기 hub 소켓을 연다(role=hospital).
//
// 2026-10-04 디자인 시안 "골든링크 병원 대시보드": 상단바 → 본원 정보 현황(두 줄) → 목록 제목·범례 → 요청 카드
// 목록(목록만 스크롤, 1열) + 오른쪽 지도·네비게이션. 화면 높이에 맞추고, 좁으면 지도가 아래로 내려간다.
export function HospitalDashboard({ hospitalId, onClose }: { hospitalId: string; onClose?: () => void }) {
  const MY_HOSPITAL_ID: string | null = hospitalId || null;
  const { state, connectionMode, sendAction, sendInfoConfirm } = useDashboardSocket(
    MY_HOSPITAL_ID ? { role: "hospital", id: MY_HOSPITAL_ID } : null,
  );
  const [selectedCaseId, setSelectedCaseId] = useState<string | null>(null);
  // 시연 일시정지 안내(2026-10-05) — 일시정지 중 버튼을 누르거나 hub가 조작을 거부하면 화면 위에 잠깐.
  // 미선택 통보(2026-10-22)도 같은 토스트로 띄운다 — 아래 myCases 필터가 "다른 병원으로 확정된 사건"의
  // 카드를 목록에서 빼기 때문에, 통보가 없으면 승인해 둔 카드가 **설명 없이 사라진다.** 수용 승낙은 처치
  // 공간 확보·기존 진료 조정 같은 자원 선배정이라, 왜 사라졌는지 알려 줘야 그 준비를 풀 수 있다(임상 자문).
  const selectionNotice = useSelectionNotice(state, MY_HOSPITAL_ID);
  const pauseToast = usePauseToast(state.actionRefused, selectionNotice);
  // 예비 고지에서 [확인]을 누른 사건 — 모달만 닫고, 실제 요청·사건 종료 시 훅이 데이터를 지운다.
  const [dismissedPreAlerts, setDismissedPreAlerts] = useState<Set<string>>(new Set());
  const activePreAlerts = Object.values(state.preAlerts).filter((alert) => !dismissedPreAlerts.has(alert.caseId));

  // 본원이 후보로 들어있는 사건만 걸러 카드로 나열한다 — 하나의 병원이 여러 구급차의 후보 목록에 동시에 들어갈
  // 수 있다. 본원 자신의 승인/불가는 번복 가능한 후보 등록일 뿐이라 카드를 지우지 않지만, 그 사건이 "다른"
  // 병원으로 이미 최종 확정됐다면 본원 입장에서는 의미가 없어 목록에서 뺀다(2026-08-11 논의).
  const myCases = MY_HOSPITAL_ID
    ? Object.values(state.matchResults)
        .map((result) => ({
          result,
          hospital: result.hospitals.find((h) => h.hospitalId === MY_HOSPITAL_ID) ?? null,
        }))
        .filter((entry): entry is { result: typeof entry.result; hospital: NonNullable<typeof entry.hospital> } =>
          entry.hospital !== null,
        )
        .filter(
          ({ result, hospital }) =>
            hospital.status === "confirmed" ||
            !result.hospitals.some((h) => h.hospitalId !== MY_HOSPITAL_ID && h.status === "confirmed"),
        )
        .map((entry, arrival) => {
          const { result } = entry;
          // 출동 시뮬레이션이 켜져 있으면 구급차가 실제로 병원에 도착했을 때만 결과 버튼을 연다.
          const arrivalReady =
            !state.identity.simDispatch ||
            (result.apid != null &&
              state.ambulanceSim[result.apid]?.caseId === result.caseId &&
              state.ambulanceSim[result.apid]?.phase === "at_hospital");
          const accepted = result.arrival?.result === "accepted" && result.arrival.hospitalId === MY_HOSPITAL_ID;
          return { ...entry, arrival, kind: cardKind(entry.hospital, arrivalReady, accepted) };
        })
        // 정렬(2026-10-04 디자인 시안): 조치가 필요한 요청이 위로(도착·결과 대기 → 판단 대기·승인 → 이송 중 →
        // 끝난 것), 같은 단계면 위험한 환자부터 — 중증도(중증 → 중등증 → 경증) → KTAS(1이 가장 위급) → 먼저 온 요청.
        .sort(
          (a, b) =>
            kindMeta(a.kind).group - kindMeta(b.kind).group ||
            SEVERITY_RANK[a.result.patientInfo.severityTag] - SEVERITY_RANK[b.result.patientInfo.severityTag] ||
            (a.result.patientInfo.ktasLevel ?? 9) - (b.result.patientInfo.ktasLevel ?? 9) ||
            a.arrival - b.arrival,
        )
    : [];
  const activeCount = myCases.filter((c) => kindMeta(c.kind).group < 3).length;

  const selected = myCases.find((c) => c.result.caseId === selectedCaseId) ?? myCases[0] ?? null;

  if (!MY_HOSPITAL_ID) {
    return (
      <div className={css({ display: "flex", alignItems: "center", justifyContent: "center", minHeight: "full", padding: "8" })}>
        <p className={css({ color: "coral", fontSize: "sm" })}>
          병원 ID가 없습니다. 첫 페이지에서 H-&lt;병원ID&gt; 형식의 접근 코드로 다시 입장해주세요.
        </p>
      </div>
    );
  }

  const selectedSim =
    selected?.result.apid &&
    state.ambulanceSim[selected.result.apid]?.hospitalId === MY_HOSPITAL_ID &&
    state.ambulanceSim[selected.result.apid]?.caseId === selected.result.caseId
      ? state.ambulanceSim[selected.result.apid]
      : null;

  return (
    <div
      className="hd-root"
      style={{
        background: HD.bg, padding: "14px 20px", boxSizing: "border-box", height: "100vh", overflow: "hidden",
        display: "flex", flexDirection: "column", color: HD.ink, fontVariantNumeric: "tabular-nums", wordBreak: "keep-all",
      }}
    >
      <style>
        {".hd-scroll{scrollbar-width:thin;scrollbar-color:#B9C4D0 transparent}" +
          "@media (max-width:900px){.hd-root{height:auto!important;min-height:100vh;overflow:visible!important}" +
          ".hd-inner,.hd-main{flex:none!important}.hd-main{flex-wrap:wrap!important}" +
          ".hd-list{overflow:visible!important;flex:none!important}.hd-map{max-width:none!important;flex:1 1 100%!important;height:520px}}"}
      </style>
      <div className="hd-inner" style={{ width: "100%", maxWidth: 1360, margin: "0 auto", flex: "1 1 0", minHeight: 0, display: "flex", flexDirection: "column", gap: 10 }}>
        {pauseToast.node}
        <HospitalTopBar
          caseCount={activeCount}
          connectionMode={connectionMode}
          since={state.receivedAt}
          hospitalId={MY_HOSPITAL_ID}
          hospitalName={state.identity.name ?? selected?.hospital.name ?? null}
          onClose={onClose}
        />

        {/* 예비 고지(2026-10-04) — 구급대 출동 순간 오는 선 경고. 실제 요청이 오면 자동으로 사라진다. */}
        <PreAlertModal
          alerts={activePreAlerts}
          onDismiss={(caseId) => setDismissedPreAlerts((prev) => new Set(prev).add(caseId))}
        />

        {/* 구급대가 이 병원을 골라 건 통화(📞, 2026-10-03) */}
        <CallStatusBanner
          statuses={Object.values(state.callStatus).filter((s) => s.hospitalId === MY_HOSPITAL_ID)}
          arrivedCaseIds={new Set(Object.keys(state.matchResults))}
        />

        {/* 본원 정보 현황 + "현재 정보가 맞습니다" (2026-09-29). hub가 이 병원 정보를 알 때만 — mock·구버전 hub면 숨긴다. */}
        {state.selfInfo && (
          <HospitalSelfInfoPanel selfInfo={state.selfInfo} onConfirm={() => sendInfoConfirm(MY_HOSPITAL_ID)} />
        )}

        {/* 목록 제목 + 범례(출처 구분: AI · 규칙 · 의료진 판단) */}
        <div style={{ flex: "none", display: "flex", flexWrap: "wrap", alignItems: "center", justifyContent: "space-between", gap: "2px 16px", padding: "0 2px" }}>
          <div style={{ display: "flex", flexWrap: "wrap", alignItems: "baseline", gap: "2px 10px" }}>
            <h2 style={{ margin: 0, fontSize: 16, fontWeight: 700, color: HD.navy }}>구급차 수용 요청 리스트</h2>
            <span style={{ fontSize: 12, color: HD.muted }}>조치가 필요한 요청이 위로, 같은 조건이면 중증도(KTAS) 순</span>
          </div>
          <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: "2px 14px", fontSize: 11.5, color: HD.sub }}>
            {([[HD.blue, "AI 처리"], [HD.gray, "규칙 기반 · 센서 · API"], [HD.orange, "의료진 판단 영역"]] as const).map(([color, label]) => (
              <span key={label} style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
                <span style={{ width: 8, height: 8, borderRadius: "50%", background: color }} />
                {label}
              </span>
            ))}
          </div>
        </div>

        <div className="hd-main" style={{ flex: "1 1 0", minHeight: 0, display: "flex", gap: 16, alignItems: "stretch" }}>
          <section style={{ flex: "999 1 640px", minWidth: 0, minHeight: 0, display: "flex", flexDirection: "column" }}>
            <div
              className="hd-list hd-scroll"
              style={{
                flex: "1 1 0", minHeight: 0, overflowY: "auto", padding: "0 8px 0 0", display: "grid",
                gridTemplateColumns: "minmax(0, 1fr)", gap: 10, alignContent: "start", gridAutoRows: "max-content",
              }}
            >
              {myCases.length === 0 ? (
                <div style={{ background: "#FFFFFF", borderRadius: 14, border: `1px solid ${HD.line}`, padding: "18px 20px", display: "flex", flexDirection: "column", gap: 6 }}>
                  <span style={{ fontSize: 14, fontWeight: 700, color: HD.navy }}>수신 대기 중</span>
                  {/* 왜 비어 있는지 안내(2026-10-04) — 요청은 본원이 사건의 존(현장 반경) 안 후보일 때만 온다 */}
                  <span style={{ fontSize: 12, color: HD.ink3, whiteSpace: "normal", lineHeight: 1.5 }}>
                    수용 요청은 본원이 사건 현장의 존(반경) 안 후보에 들 때 자동으로 도착합니다 — 사건이 어느 병원에 요청
                    중인지는 관제 지도(/map)에서 확인할 수 있습니다. 인근에서 구급대가 출동하면 수용 요청 전에 예비 고지
                    알림이 먼저 뜹니다.
                  </span>
                </div>
              ) : (
                myCases.map(({ result, hospital, kind }) => (
                  <RequestCard
                    key={result.caseId}
                    result={result}
                    hospital={hospital}
                    hospitalId={MY_HOSPITAL_ID}
                    kind={kind}
                    selected={selected?.result.caseId === result.caseId}
                    sim={
                      result.apid && state.ambulanceSim[result.apid]?.caseId === result.caseId
                        ? state.ambulanceSim[result.apid]
                        : null
                    }
                    banner={<TransportAlertBanner assessments={state.transportAssessments[result.caseId] ?? []} />}
                    onSelect={() => setSelectedCaseId(result.caseId)}
                    onAction={sendAction}
                    paused={result.paused === true}
                    onPaused={pauseToast.notify}
                  />
                ))
              )}
            </div>
          </section>

          <div className="hd-map" style={{ flex: "1 1 340px", maxWidth: 460, minWidth: 0, minHeight: 0, display: "flex" }}>
            <MapPanel
              hospital={selected?.hospital ?? null}
              caseId={selected?.result.caseId ?? null}
              ambulanceGps={selected?.result.ambulanceGps ?? null}
              selfGps={state.identity.gps ?? null}
              selfName={state.identity.name}
              sim={selectedSim}
              unitName={selected ? selected.result.ambulanceName ?? selected.result.apid ?? null : null}
              statusText={selected ? kindMeta(selected.kind).map : null}
              statusInk={selected ? kindMeta(selected.kind).ink : null}
            />
          </div>
        </div>

        <footer style={{ flex: "none", textAlign: "center", fontSize: 11.5, color: HD.muted, padding: "0 0 2px", lineHeight: 1.4 }}>
          AI는 환자 정보 구조화와 기록 자동화만 수행합니다. 수용 결정은 본원 의료진의 판단입니다.
        </footer>
      </div>
    </div>
  );
}
