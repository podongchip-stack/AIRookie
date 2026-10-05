"use client";

import { Suspense, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { css, cx } from "styled-system/css";
import { CaseFocusPanel } from "@/components/map/CaseFocusPanel";
import { MonitorMapPanel } from "@/components/map/MonitorMapPanel";
import { thinScrollbarStyle } from "@/components/ui/scrollbar-style";
import { CONNECTION_LABEL, useDashboardSocket } from "@/hooks/use-dashboard-socket";
import { PHASE_SHORT, hospitalRequests } from "@/lib/monitor";
import type { MonitorCase } from "@/types/dashboard";

// 사건 상황판(2026-10-04) — 관제 지도에서 사건을 클릭하면 **새 창**으로 열린다. 관제 지도
// 본창은 항상 전체 현황(모든 병원·구급대)을 유지하고, 사건 하나를 깊게 보는 건 이 창의
// 역할이다. 지도는 그 사건 중심으로 당겨지고, 요청 표시도 이 사건 것만 그린다.
// 환자 상세(통화 전문·활력징후)는 받지 않는다 — 관제 역할의 한계 그대로(case_overview 요약만).
function CaseBoardContent() {
  const searchParams = useSearchParams();
  const caseId = searchParams.get("id");
  const { state, connectionMode } = useDashboardSocket(
    caseId ? { role: "monitor", id: `case-${caseId.slice(0, 8)}` } : null,
  );
  const monitorCase: MonitorCase | null = caseId ? state.monitorCases[caseId] ?? null : null;
  // 매칭 전 단계(신고 접수~현장 통화 전, 2026-10-04) — 구급차 시뮬레이션 상태에서 이 사건을 찾는다.
  const simForCase = caseId
    ? Object.values(state.ambulanceSim).find((s) => s.caseId === caseId) ?? null
    : null;
  const preAlert = caseId ? state.preAlerts[caseId] ?? null : null;
  // 한 번이라도 사건을 받았으면, 나중에 사라졌을 때 "종료"로 구분해 보여준다
  const [seen, setSeen] = useState(false);
  useEffect(() => {
    if (monitorCase || simForCase) setSeen(true);
  }, [monitorCase, simForCase]);

  const sim = monitorCase?.apid ? state.ambulanceSim[monitorCase.apid] ?? null : simForCase;
  // 이 사건의 요청만 지도에 그린다 — 다른 사건 표시는 본창(관제 지도)의 몫
  const singleCase = useMemo(
    () => (monitorCase ? { [monitorCase.caseId]: monitorCase } : {}),
    [monitorCase],
  );
  const requests = useMemo(() => hospitalRequests(singleCase), [singleCase]);
  const focus = useMemo(() => {
    const point = sim?.gps ?? sim?.incident ?? monitorCase?.ambulanceGps ?? null;
    return point && caseId ? { lat: point.lat, lng: point.lng, key: caseId } : null;
    // 처음 사건을 받았을 때 한 번만 당긴다
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [caseId, sim != null, monitorCase?.caseId]);

  return (
    <div className={css({ display: "flex", flexDirection: "column", height: "100vh", backgroundColor: "bg", padding: "5", gap: "3.5" })}>
      <header className={css({ display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: "3", backgroundColor: "surface", borderWidth: "1px", borderColor: "line", borderRadius: "panel", paddingX: "4.5", paddingY: "3" })}>
        <div className={css({ display: "flex", alignItems: "center", gap: "3" })}>
          <Link href="/" className={css({ fontSize: "md", fontWeight: "bold", color: "ink" })}>
            골든<span className={css({ color: "navy" })}>링크</span>
          </Link>
          <span className={css({ fontSize: "xs", color: "ink", paddingLeft: "3", borderLeftWidth: "1px", borderColor: "line" })}>
            사건 상황판{monitorCase ? ` · ${monitorCase.ambulanceName ?? monitorCase.apid ?? ""}` : ""}
          </span>
        </div>
        <div className={css({ display: "flex", alignItems: "center", gap: "3", fontSize: "xs" })}>
          <Link href="/map" className={css({ color: "navy", fontWeight: "semibold" })}>관제 지도 →</Link>
          <span className={css({ color: CONNECTION_LABEL[connectionMode].color })}>{CONNECTION_LABEL[connectionMode].text}</span>
        </div>
      </header>

      {!caseId ? (
        <p className={css({ fontSize: "sm", color: "ink2" })}>사건 식별자(?id=)가 없습니다 — 관제 지도에서 사건을 클릭해 여세요.</p>
      ) : !monitorCase && simForCase ? (
        // 매칭 전 단계 — 신고 접수부터 팔로잉(2026-10-04). 현장 통화가 끝나면 아래 전체 보드로 바뀐다.
        <main className={css({ display: "grid", gridTemplateColumns: { base: "1fr", lg: "340px 1fr" }, gap: "3.5", flex: "1", minHeight: "0" })}>
          <aside className={css({ display: "flex", flexDirection: "column", gap: "3", minHeight: "0" })}>
            <section className={css({ display: "flex", flexDirection: "column", gap: "2.5", backgroundColor: "surface", borderWidth: "1px", borderColor: "line", borderRadius: "panel", padding: "3.5" })}>
              <h2 className={css({ fontSize: "sm", fontWeight: "bold", color: "ink" })}>
                🚨 신고 접수 — {preAlert?.ambulanceName ?? simForCase.apid}
              </h2>
              <div className={css({ display: "flex", gap: "1.5", flexWrap: "wrap", fontSize: "xs" })}>
                <span className={css({ fontWeight: "semibold", color: "ink", backgroundColor: "surfaceSub", paddingX: "2", paddingY: "0.5", borderRadius: "chip" })}>
                  🚑 {PHASE_SHORT[simForCase.phase]}{simForCase.paused ? " · 정지됨" : ""}
                </span>
                {preAlert?.reportedSeverity === "high" && (
                  <span className={css({ fontWeight: "bold", color: "coral", backgroundColor: "coralSoft", paddingX: "2", paddingY: "0.5", borderRadius: "chip" })}>
                    중증 의심
                  </span>
                )}
              </div>
              {preAlert?.reportedSymptom && (
                <p className={css({ fontSize: "sm", color: "ink" })}>
                  신고 증상: <b>{preAlert.reportedSymptom}</b>
                  <span className={css({ fontSize: "2xs", color: "ink3" })}> (신고 내용 — 현장 평가와 다를 수 있음)</span>
                </p>
              )}
              <p className={css({ fontSize: "xs", color: "ink2" })}>
                {preAlert && (preAlert.hospitalCount ?? 0) > 0
                  ? `예비 고지 — 현장 인근 병원 ${preAlert.hospitalCount}곳에 선 경고 발송됨`
                  : "예비 고지 없음(경증 신고)"}
              </p>
              <p className={css({ fontSize: "xs", color: "ink3" })}>
                현장 통화가 끝나면 후보 병원 요청과 응답이 여기에 나타납니다.
              </p>
            </section>
          </aside>
          <MonitorMapPanel
            overview={state.mapOverview}
            cases={{}}
            ambulanceSim={state.ambulanceSim}
            requests={new Map()}
            focus={focus}
          />
        </main>
      ) : !monitorCase ? (
        <p className={css({ fontSize: "sm", color: "ink2" })}>
          {seen ? "✅ 사건이 종료되었습니다 — 창을 닫아도 됩니다." : "사건 정보를 기다리는 중…"}
        </p>
      ) : (
        <main className={css({ display: "grid", gridTemplateColumns: { base: "1fr", lg: "340px 1fr" }, gap: "3.5", flex: "1", minHeight: "0" })}>
          <aside
            className={cx(
              css({ display: "flex", flexDirection: "column", gap: "3", minHeight: "0", overflowY: "auto", paddingRight: "1" }),
              thinScrollbarStyle,
            )}
          >
            <CaseFocusPanel
              monitorCase={monitorCase}
              phase={sim?.phase ?? null}
              paused={sim?.paused ?? false}
              events={state.monitorEvents.filter((event) => event.caseId === monitorCase.caseId)}
            />
          </aside>
          <MonitorMapPanel
            overview={state.mapOverview}
            cases={singleCase}
            ambulanceSim={state.ambulanceSim}
            requests={requests}
            focus={focus}
          />
        </main>
      )}
    </div>
  );
}

export default function CaseBoardPage() {
  return (
    <Suspense fallback={null}>
      <CaseBoardContent />
    </Suspense>
  );
}
