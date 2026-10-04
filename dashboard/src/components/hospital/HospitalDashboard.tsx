"use client";

import { useState } from "react";
import { css, cx } from "styled-system/css";
import { HospitalTopBar } from "@/components/hospital/HospitalTopBar";
import { HospitalSelfInfoPanel } from "@/components/hospital/HospitalSelfInfoPanel";
import { CallStatusBanner } from "@/components/hospital/CallStatusBanner";
import { Legend } from "@/components/hospital/Legend";
import { CaseMatchPanel } from "@/components/hospital/CaseMatchPanel";
import { MapPanel } from "@/components/hospital/MapPanel";
import { thinScrollbarStyle } from "@/components/ui/scrollbar-style";
import { useDashboardSocket } from "@/hooks/use-dashboard-socket";
import type { PreAlert, TransportAssessment } from "@/types/dashboard";

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
          padding: "5", boxShadow: "0 12px 40px rgba(22,34,46,.35)",
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
        marginBottom: "1.5",
        paddingX: "3",
        paddingY: "2",
        borderRadius: "field",
        borderWidth: "1px",
        borderColor: critical ? "coral" : "severity.medium",
        backgroundColor: critical ? "coralSoft" : "severity.medium.subtle",
        display: "flex",
        flexDirection: "column",
        gap: "0.5",
      })}
    >
      <p className={css({ fontSize: "xs", fontWeight: "bold", color: critical ? "coral" : "severity.medium" })}>
        🚑 이송 중 상태 변화 · NEWS2 {latest.news2}
        {latest.si != null ? ` · 쇼크지수 ${latest.si}` : ""}
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

// 병원 대시보드는 병원 1곳 전용 화면이라 자신의 병원 ID(hpid)가 고정된다. 첫 페이지에서 병원 접근 코드(H-<hpid>)로
// 들어온 /hospital?id= 페이지가 이 컴포넌트를 그린다(2026-10-03 회의로 관제 지도와 분리). onClose를 주면 상단바에
// [닫기] 버튼이 생긴다(다른 화면 위에 띄울 때용, 지금은 쓰지 않음). 이 화면은 자기 hub 소켓을 연다(role=hospital).
export function HospitalDashboard({ hospitalId, onClose }: { hospitalId: string; onClose?: () => void }) {
  const MY_HOSPITAL_ID: string | null = hospitalId || null;
  const { state, connectionMode, sendAction, sendInfoConfirm } = useDashboardSocket(
    MY_HOSPITAL_ID ? { role: "hospital", id: MY_HOSPITAL_ID } : null,
  );
  const [selectedCaseId, setSelectedCaseId] = useState<string | null>(null);
  // 예비 고지에서 [확인]을 누른 사건 — 모달만 닫고, 실제 요청·사건 종료 시 훅이 데이터를 지운다.
  const [dismissedPreAlerts, setDismissedPreAlerts] = useState<Set<string>>(new Set());
  const activePreAlerts = Object.values(state.preAlerts).filter((alert) => !dismissedPreAlerts.has(alert.caseId));

  // 본원이 후보로 들어있는 사건만 걸러 카드로 나열한다 — 하나의 병원이 여러
  // 구급차의 후보 목록에 동시에 들어갈 수 있어서, 사건 하나만 보던 예전
  // 구조로는 다른 구급차의 요청이 화면에서 사라져 보였다.
  //
  // 본원 자신의 승인/불가는 번복 가능한 후보 등록일 뿐이라 카드를 지우지 않지만
  // (CaseMatchPanel 참고), 그 사건이 "다른" 병원으로 이미 최종 확정됐다면 본원
  // 입장에서는 더 이상 의미가 없는 사건이라 목록에서 뺀다(2026-08-11 논의).
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
    : [];

  const selected = myCases.find((c) => c.result.caseId === selectedCaseId) ?? myCases[0] ?? null;

  if (!MY_HOSPITAL_ID) {
    return (
      <div
        className={css({
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          minHeight: "full",
          padding: "8",
        })}
      >
        <p className={css({ color: "coral", fontSize: "sm" })}>
          병원 ID가 없습니다. 첫 페이지에서 H-&lt;병원ID&gt; 형식의 접근 코드로 다시 입장해주세요.
        </p>
      </div>
    );
  }

  // 존재하지 않는 hpid는 이제 랜딩 페이지(src/app/page.tsx)에서 GET /identity로
  // 미리 걸러서 애초에 이 페이지까지 못 들어오게 한다 — 여기서 known===false로
  // 전체 화면을 막는 처리는 2026-08-11에 랜딩 페이지 쪽으로 옮겼다(직접 URL로
  // 들어온 경우엔 상단바 이름이 ID 폴백으로 남는 정도로만 티가 난다).

  return (
    <div
      className={css({
        display: "flex",
        flexDirection: "column",
        minHeight: "full",
        backgroundColor: "bg",
        padding: "7",
      })}
    >
      <HospitalTopBar
        caseCount={myCases.length}
        connectionMode={connectionMode}
        since={state.receivedAt}
        hospitalId={MY_HOSPITAL_ID}
        hospitalName={state.identity.name ?? selected?.hospital.name ?? null}
        onClose={onClose}
      />
      <Legend />

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

      {/* 귀원 정보 현황 + "현재 정보가 맞습니다" 확인 버튼 (2026-09-29).
          hub가 이 병원 정보를 알 때만 온다 — mock 모드·구버전 hub면 숨긴다. */}
      {state.selfInfo && (
        <HospitalSelfInfoPanel
          selfInfo={state.selfInfo}
          onConfirm={() => sendInfoConfirm(MY_HOSPITAL_ID)}
        />
      )}

      <main
        className={css({
          display: "grid",
          gridTemplateColumns: { base: "1fr", lg: "1.8fr 1fr" },
          gap: "6",
          alignItems: "stretch",
          flex: "1",
          minHeight: "0",
        })}
      >
        {/* 왼쪽: 본원이 후보로 걸린 사건을 전부 카드로 나열한다. 카드를 누르면
            선택되어 오른쪽 지도에 그 사건 기준 거리/ETA가 표시된다.
            바깥 div가 그리드 셀 높이를 정확히 지키고(height:100% + minHeight:0
            + overflow:hidden), 안쪽 div만 스크롤한다 — 구급차 쪽 병원 후보
            리스트에서 겪은 것과 같은 문제(overflowY:auto 하나만으론 페이지
            전체가 늘어남)를 겪지 않으려고 처음부터 이 구조로 짰다(2026-08-11). */}
        <div
          className={css({
            display: "flex",
            flexDirection: "column",
            height: "100%",
            minHeight: "0",
            overflow: "hidden",
          })}
        >
        <div
          className={cx(
            // 수용 요청 카드를 2열 세로 카드로(2026-10-01) — 가로로 긴 한 줄 카드는 여백이 너무 넓었다.
            // 카드가 많아져도 페이지가 아니라 이 목록 안에서만 스크롤된다.
            css({
              display: "grid",
              gridTemplateColumns: { base: "1fr", md: "repeat(2, minmax(0, 1fr))" },
              alignContent: "start",
              gap: "3.5",
              flex: "1",
              minHeight: "0",
              overflowY: "auto",
              paddingRight: "1",
            }),
            thinScrollbarStyle,
          )}
        >
          {myCases.length === 0 ? (
            <div className={css({ gridColumn: "1 / -1", display: "flex", flexDirection: "column", gap: "2" })}>
              <CaseMatchPanel patientInfo={null} hospital={null} hospitalId={MY_HOSPITAL_ID} caseId="" onAction={sendAction} />
              {/* 왜 비어 있는지 안내(2026-10-04) — 요청은 본원이 사건의 존(현장 반경) 안 후보일 때만 온다 */}
              <p className={css({ fontSize: "xs", color: "ink3", paddingX: "1" })}>
                수용 요청은 본원이 사건 현장의 존(반경) 안 후보에 들 때 자동으로 도착합니다 — 사건이 어느 병원에
                요청 중인지는 관제 지도(/map)의 요청 표시(병원 이름 옆 H-코드)에서 확인할 수 있습니다. 인근에서
                구급대가 출동하면 수용 요청 전에 예비 고지 알림이 먼저 뜹니다.
              </p>
            </div>
          ) : (
            myCases.map(({ result, hospital }) => {
              const isSelected = selected?.result.caseId === result.caseId;
              return (
                // CaseMatchPanel 안에 승인/거절 버튼이 이미 있어서 이 카드 자체를
                // <button>으로 감싸면 button-in-button이 되어 유효하지 않은 HTML이
                // 된다 — 대신 role="button"을 준 <div>로 카드 선택만 처리한다.
                <div
                  key={result.caseId}
                  role="button"
                  tabIndex={0}
                  onClick={() => setSelectedCaseId(result.caseId)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") setSelectedCaseId(result.caseId);
                  }}
                  className={css({
                    display: "block",
                    width: "100%",
                    textAlign: "left",
                    borderRadius: "panel",
                    cursor: "pointer",
                    outline: "none",
                    borderWidth: "2px",
                    borderColor: isSelected ? "navy" : "transparent",
                  })}
                >
                  <TransportAlertBanner assessments={state.transportAssessments[result.caseId] ?? []} />
                  <CaseMatchPanel
                    patientInfo={result.patientInfo}
                    hospital={hospital}
                    hospitalId={MY_HOSPITAL_ID}
                    caseId={result.caseId}
                    ambulanceName={result.ambulanceName}
                    arrivalReady={
                      // 출동 시뮬레이션이 켜져 있으면 구급차가 실제로 병원에 도착했을 때만 결과 버튼을 연다.
                      !state.identity.simDispatch ||
                      (result.apid != null &&
                        state.ambulanceSim[result.apid]?.caseId === result.caseId &&
                        state.ambulanceSim[result.apid]?.phase === "at_hospital")
                    }
                    arrived={result.arrival?.result === "accepted" && result.arrival.hospitalId === MY_HOSPITAL_ID}
                    onAction={sendAction}
                  />
                </div>
              );
            })
          )}
        </div>
        </div>

        <MapPanel
          hospital={selected?.hospital ?? null}
          caseId={selected?.result.caseId ?? null}
          ambulanceGps={selected?.result.ambulanceGps ?? null}
          selfGps={state.identity.gps ?? null}
          selfName={state.identity.name}
          sim={
            selected?.result.apid &&
            state.ambulanceSim[selected.result.apid]?.hospitalId === MY_HOSPITAL_ID &&
            state.ambulanceSim[selected.result.apid]?.caseId === selected.result.caseId
              ? state.ambulanceSim[selected.result.apid]
              : null
          }
        />
      </main>

      <p
        className={css({
          marginTop: "3.5",
          paddingX: "1",
          fontSize: "xs",
          color: "ink",
          textAlign: "center",
        })}
      >
        AI는 환자 정보 구조화와 기록 자동화만 수행합니다. 수용 결정은 본원 의료진의 판단입니다.
      </p>
    </div>
  );
}
