"use client";

import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { css } from "styled-system/css";
import { AmbulanceLegend, AmbulanceTopBar } from "@/components/ambulance/AmbulanceTopBar";
import { AD } from "@/components/ambulance/ambulance-design";
import { usePauseToast } from "@/components/ui/PauseToast";
import { CallSummaryEditablePanel } from "@/components/ambulance/CallSummaryEditablePanel";
import { CallDemoPanel } from "@/components/ambulance/CallDemoPanel";
import { HospitalCandidateListPanel } from "@/components/ambulance/HospitalCandidateListPanel";
import { CandidateMapPanel } from "@/components/ambulance/CandidateMapPanel";
import { DispatchControlPanel } from "@/components/ambulance/DispatchControlPanel";
import { TransportMonitorPanel } from "@/components/ambulance/TransportMonitorPanel";
import { CONNECTION_LABEL, useDashboardSocket } from "@/hooks/use-dashboard-socket";
import type { CallSignalType, DispatchTarget } from "@/types/dashboard";

// 이 프로세스(voice)는 구급차 1대 전용이라 사건도 한 번에 하나만 진행된다 —
// 병원과 달리 여러 사건을 동시에 다룰 필요가 없다. 다만 hub가 어느 구급차·
// 사건인지 구분할 수 있어야 하므로, 자기 apid(URL의 ?id=)와 통화 시작마다
// 새로 만드는 caseId를 실어 보낸다 (feature/hub 담당자 참고사항 참고).
// caseId를 구급차(apid)별로 탭 세션에 보관한다. sessionStorage는 사생활 보호 모드 등에서
// 예외를 던질 수 있어 실패해도 조용히 넘어간다(그 경우 새로고침 복원만 안 될 뿐이다).
function caseIdKey(apid: string) {
  return `goldenlink:caseId:${apid}`;
}

function loadCaseId(apid: string | null): string | null {
  if (!apid || typeof window === "undefined") return null;
  try {
    return window.sessionStorage.getItem(caseIdKey(apid));
  } catch {
    return null;
  }
}

function saveCaseId(apid: string | null, caseId: string) {
  if (!apid) return;
  try {
    window.sessionStorage.setItem(caseIdKey(apid), caseId);
  } catch {
    // 저장 실패는 무시 — 새로고침 복원만 안 된다
  }
}

function alertNotSent() {
  window.alert(
    "hub와 연결이 끊겨 신호를 보내지 못했습니다. 상단에 '실시간 연동'이 다시 뜨면 한 번 더 눌러주세요.",
  );
}

function AmbulanceDashboardContent({ apid }: { apid: string | null }) {
  const { state, connectionMode, sendAction, sendCallSignal, sendAudioChunk, sendSimCommand, sendTransportVitals } =
    useDashboardSocket(apid ? { role: "ambulance", id: apid } : null);
  // 이송 승인을 눌렀지만 hub 응답(confirmed)을 아직 못 받은 병원. 화면의 "확정"은 hub 기준으로만
  // 띄운다(2026-10-01) — 예전엔 누르는 즉시 로컬에서 확정으로 바꿔서, hub가 거부해도(병원 미승인 등)
  // 화면엔 확정으로 남았다. mock 모드는 hub가 없으니 누른 값을 그대로 확정으로 본다.
  const [pendingConfirm, setPendingConfirm] = useState<{ hospitalId: string; result: unknown } | null>(null);
  // 통화 시작 때 만든 caseId는 탭 세션에 저장해 둔다 — 예전엔 메모리에만 있어서 새로고침
  // 한 번에 사라졌고, 그러면 hub가 결과를 다시 보내줘도 화면에 못 띄웠다(2026-09-24).
  const [myCaseId, setMyCaseIdState] = useState<string | null>(() => loadCaseId(apid));
  const setMyCaseId = (caseId: string) => {
    setMyCaseIdState(caseId);
    saveCaseId(apid, caseId);
  };

  // 출동 시뮬레이션(start-all.sh 기본값, 2026-10-01). 켜져 있으면 caseId는 [이동] 때 만들고,
  // 통화 시작은 현장 도착 뒤 그 사건으로만 한다(hub도 같은 규칙으로 거부한다).
  const simOn = state.identity.simDispatch === true;
  const mySim = apid ? state.ambulanceSim[apid] ?? null : null;
  // 이 구급차의 사건은 hub의 시뮬레이션 상태가 기준이다(2026-10-03). 탭에 기억해 둔 caseId는 세션 저장소라
  // 브라우저를 껐다 켜면 사라지거나 지난 사건 것이 남는데, 그러면 [현장 종료]·통화 시작이 엉뚱한 caseId로
  // 나가 hub가 조용히 거부했다(버튼은 켜져 있는데 눌러도 안 되는 문제). hub가 사건을 알려 주면 그것을 쓰고,
  // 대기·복귀 중처럼 hub의 caseId가 비어 있을 때만 탭의 값([이동]으로 막 만든 caseId 포함)을 쓴다.
  const simCaseId = simOn ? mySim?.caseId ?? null : null;
  const currentCaseId = simCaseId ?? myCaseId;

  // 기본은 내가 연 통화(currentCaseId)의 결과다. 그 caseId조차 모를 때(새 탭 등)는 hub가 준
  // 결과 중 이 구급차(apid)의 가장 최근 사건을 되찾아 쓴다 — hub는 연결 때 이 구급차의
  // 진행 중인 사건을 따라잡기로 보내준다. myCaseId가 있으면(새 통화 진행 중) 예전
  // 사건으로 대체하지 않는다: 새 결과가 오기 전에 지난 환자 정보를 띄우면 안 된다.
  const ownResults = Object.values(state.matchResults).filter((r) => r.apid === apid);
  const myResult = currentCaseId
    ? state.matchResults[currentCaseId] ?? null
    : ownResults[ownResults.length - 1] ?? null;
  const activeCaseId = myResult?.caseId ?? currentCaseId;
  const hubConfirmedId = myResult?.hospitals.find((h) => h.status === "confirmed")?.hospitalId ?? null;
  // 요청 중 표시는 누른 순간의 결과가 그대로일 때만 유효하다 — hub가 새 결과를 보내면(확정
  // 반영이든 거부로 그대로든) 자연히 풀린다. 거부되면 hub가 재전송하지 않을 수 있어 5초 뒤에도 푼다.
  const pendingConfirmId =
    pendingConfirm && (connectionMode === "mock" || pendingConfirm.result === myResult)
      ? pendingConfirm.hospitalId
      : null;
  const confirmedHospitalId = connectionMode === "mock" ? pendingConfirmId ?? hubConfirmedId : hubConfirmedId;
  useEffect(() => {
    if (!pendingConfirm || connectionMode === "mock") return;
    const timer = setTimeout(() => setPendingConfirm(null), 5000);
    return () => clearTimeout(timer);
  }, [pendingConfirm, connectionMode]);

  const [callActive, setCallActive] = useState(false);
  // 이 사건의 통화 상태(hub 기준) — 휴대폰으로 건 통화를 태블릿도 안다
  const myCallStatus = currentCaseId ? state.callStatus[currentCaseId] ?? null : null;
  const phoneCalling = myCallStatus?.state === "calling" && myCallStatus.device === "phone" && !callActive;
  // 출동 위치(주소 검색·지도 클릭). 없으면 무작위. 출동하면 비운다.
  const [dispatchTarget, setDispatchTarget] = useState<DispatchTarget | null>(null);
  // [이동]·[현장 종료] 때 올려서 출동 조작부(검색어·결과)와 통화 시연(인식 텍스트)을 새로 그린다 — 지난 사건의
  // 내용이 다음 출동 화면에 남지 않게(2026-10-01). 통화 시연은 내려갈 때 마이크·인식을 스스로 멈춘다.
  const [resetSeq, setResetSeq] = useState(0);
  // 출동 위치 지정은 구급차 화면에서 제거(2026-10-04) — 위치는 상황실(시연 콘솔) 지령 소관.
  // 지도 클릭 선택도 같이 끈다. [이동]은 무작위 출동 폴백으로만 남는다.
  const canPickTarget = false;
  const onSceneForMyCase = mySim?.phase === "on_scene" && mySim.caseId === currentCaseId;
  const startBlockedReason = phoneCalling
    ? `휴대폰으로 ${myCallStatus?.hospitalName ?? "병원"}과 통화 중입니다`
    : myCallStatus?.state === "ended" && !callActive
      ? "이 사건의 통화는 이미 끝났습니다"
      : simOn && !onSceneForMyCase
        ? "현장 도착 후 통화할 수 있습니다"
        : null;

  function handleDispatch() {
    if (!apid) return;
    const caseId = crypto.randomUUID();
    setMyCaseId(caseId);
    setPendingConfirm(null);
    if (!sendSimCommand("dispatch", apid, caseId, dispatchTarget)) alertNotSent();
    else {
      setDispatchTarget(null);
      setResetSeq((n) => n + 1);
    }
  }

  // 시연 일시정지 중엔 이 화면의 조작(이송 승인·현장 종료·이송 중 시나리오)을 막고 위쪽에 안내를 잠깐 띄운다(2026-10-05)
  const simPaused = simOn && mySim?.paused === true && mySim.pauseReason !== "call";
  const pauseToast = usePauseToast(state.actionRefused);

  function handleSceneEnd() {
    if (simPaused) {
      pauseToast.notify();
      return;
    }
    // hub가 기억하는 이 구급차의 사건으로 보낸다 — 다른 caseId면 hub가 거부한다.
    const caseId = simCaseId ?? activeCaseId;
    if (!apid || !caseId) return;
    if (!sendSimCommand("scene_end", apid, caseId)) alertNotSent();
    else {
      setCallActive(false);
      setResetSeq((n) => n + 1);
    }
  }

  // [정지]·[상황 재개](2026-10-03): 출동 중·현장·이송 중인 시연 상황을 멈추고 이어 간다.
  function handleSimControl(type: "sim_pause" | "sim_resume") {
    if (!apid) return;
    if (!sendSimCommand(type, apid, simCaseId ?? activeCaseId ?? "")) alertNotSent();
  }

  function handleCallSignal(signal: CallSignalType) {
    if (!apid) return;
    setCallActive(signal === "call_started");
    if (signal === "call_started" && simOn) {
      if (currentCaseId && !sendCallSignal(signal, apid, currentCaseId, { device: "tablet" })) alertNotSent();
    } else if (signal === "call_started") {
      // mock 모드에선 고정 caseId를 써야 mock-data.ts의 mockHubMatchResult
      // (caseId: "case-mock-demo")와 실제로 매칭된다 — crypto.randomUUID()로
      // 만들면 mock 데이터의 고정 ID와 절대 일치하지 않아 "통화 시작"을 눌러도
      // 영원히 수신 대기 중으로 남는다(2026-08-11 실제로 재현됨).
      const caseId = connectionMode === "mock" ? "case-mock-demo" : crypto.randomUUID();
      setMyCaseId(caseId);
      setPendingConfirm(null);
      if (!sendCallSignal(signal, apid, caseId, { device: "tablet" })) alertNotSent();
    } else if (activeCaseId) {
      if (!sendCallSignal(signal, apid, activeCaseId, { device: "tablet" })) alertNotSent();
    }
  }

  function handleApprove(hospitalId: string) {
    if (simPaused) {
      pauseToast.notify();
      return;
    }
    if (!activeCaseId) return;
    setPendingConfirm({ hospitalId, result: myResult });
    sendAction({
      caseId: activeCaseId,
      action: "final_approval",
      hospital_id: hospitalId,
      actor: "paramedic",
      timestamp: new Date().toISOString(),
    });
  }

  if (!apid) {
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
          구급차 ID가 없습니다. 랜딩 페이지에서 A-&lt;구급차ID&gt; 형식의 코드로 다시 입장해주세요.
        </p>
      </div>
    );
  }

  // 존재하지 않는 apid는 이제 랜딩 페이지(src/app/page.tsx)에서 GET /identity로
  // 미리 걸러서 애초에 이 페이지까지 못 들어오게 한다 — 여기서 known===false로
  // 전체 화면을 막는 처리는 2026-08-11에 랜딩 페이지 쪽으로 옮겼다(직접 URL로
  // 들어온 경우엔 상단바 이름이 ID 폴백으로 남는 정도로만 티가 난다).

  const confirmedName = myResult?.hospitals.find((h) => h.hospitalId === confirmedHospitalId)?.name ?? null;

  // 디자인 시안(2026-10-05, "골든링크 시연 화면") — 위: 왼쪽 360px 열(현장 상태 · 통화 요약/통화 현황) + 오른쪽 지도,
  // 아래: 병원 후보 가로 스크롤 카드. 넓은 화면에선 한 화면(100vh)에 맞추고, 좁으면 세로로 쌓여 스크롤된다.
  return (
    <div className="amb-root" style={{ background: AD.bg, color: AD.ink, fontSize: 13, lineHeight: 1.4, fontVariantNumeric: "tabular-nums" }}>
      <style>{PAGE_CSS}</style>
      <div className="amb-page">
        {pauseToast.node}
        <AmbulanceTopBar
          confirmedName={confirmedName}
          connectionMode={connectionMode}
          since={state.receivedAt}
          ambulanceId={apid}
          ambulanceName={state.identity.name ?? myResult?.ambulanceName ?? null}
        />
        <AmbulanceLegend />
        {phoneCalling && (
          <div style={{ flex: "none", padding: "8px 16px", borderRadius: 12, background: AD.greenSoft, color: AD.green, fontSize: 13, fontWeight: 700 }}>
            휴대폰으로 {myCallStatus?.hospitalName ?? "병원"}과 통화 중 — 통화가 끝나면 환자 정보가 후보 병원에 동시에 전달됩니다
          </div>
        )}

        <div className="amb-top">
          {/* 왼쪽 열: 현장 상태(출동 시뮬레이션) → 통화 요약·통화 현황 → 이송 중 모니터링 → (--dashboard-call이면) 통화 시연.
              내용이 늘어나면 이 열만 스크롤된다. */}
          <div className="amb-left amb-thin">
            {simOn && (
              <DispatchControlPanel
                key={`dispatch-${resetSeq}`}
                apid={apid}
                sim={mySim}
                target={dispatchTarget}
                onTargetChange={setDispatchTarget}
                confirmed={confirmedHospitalId != null}
                callActive={callActive || myCallStatus?.state === "calling"}
                onDispatch={handleDispatch}
                onSceneEnd={handleSceneEnd}
                onPause={() => handleSimControl("sim_pause")}
                onResume={() => handleSimControl("sim_resume")}
              />
            )}
            {/* 통화는 기본적으로 휴대폰 전화 앱으로만(2026-10-03) — 통화 현황(상태·실시간 자막)은 통화 요약 카드 아래쪽에 합쳤다.
                hub를 --dashboard-call로 띄웠을 때만 이 화면에도 [통화 시작]이 있는 통화 시연 패널이 붙는다. */}
            <CallSummaryEditablePanel
              key={`summary-${resetSeq}`}
              data={myResult}
              apid={apid}
              callStatus={myCallStatus}
              voiceLines={currentCaseId ? state.callTranscripts[currentCaseId] ?? [] : []}
              sentHospitalCount={myResult ? myResult.hospitals.length : null}
              waitingHint={simOn && !onSceneForMyCase && !myResult ? "현장 도착 후 대원 휴대폰의 전화 앱으로 병원에 전화합니다" : null}
            />
            {/* 이송 중 모니터링(2.5단계, 2026-10-04) — 이송이 확정된 사건에만 뜬다. 활력징후
                입력 구멍의 데모 어댑터(가상 시나리오)와 hub 규칙 엔진 판정 표시. */}
            {confirmedHospitalId != null && activeCaseId && apid && (
              <div style={{ flex: "none" }}>
                <TransportMonitorPanel
                  caseId={activeCaseId}
                  apid={apid}
                  assessments={state.transportAssessments[activeCaseId] ?? []}
                  live={connectionMode === "live"}
                  onSendVitals={(...args: Parameters<typeof sendTransportVitals>) => {
                    if (simPaused) {
                      pauseToast.notify();
                      return false;
                    }
                    return sendTransportVitals(...args);
                  }}
                />
              </div>
            )}
            {state.identity.dashboardCall === true && (
              <div style={{ flex: "none", minHeight: 320 }}>
                <CallDemoPanel
                  // 이송이 끝나 기지로 돌아가는 동안·대기 중엔 지난 통화 텍스트를 비운다(이송 완료 뒤 남지 않게).
                  key={`call-${resetSeq}-${simOn && ["returning", "idle"].includes(mySim?.phase ?? "idle") ? "done" : "live"}`}
                  onCallSignal={handleCallSignal}
                  onAudioChunk={sendAudioChunk}
                  startBlockedReason={startBlockedReason}
                  voiceLines={currentCaseId ? state.callTranscripts[currentCaseId] ?? [] : []}
                />
              </div>
            )}
          </div>

          <div className="amb-map">
            <CandidateMapPanel
              // 이송이 확정되면 지도엔 확정 병원만(2026-10-03) — 이동 중 주변 병원 마커는 접는다(목록은 펼칠 수 있다).
              data={
                myResult && confirmedHospitalId && myResult.hospitals.some((h) => h.hospitalId === confirmedHospitalId)
                  ? { ...myResult, hospitals: myResult.hospitals.filter((h) => h.hospitalId === confirmedHospitalId) }
                  : myResult
              }
              confirmedHospitalId={confirmedHospitalId}
              sim={simOn ? mySim : null}
              scene={activeCaseId ? state.sceneCandidates[activeCaseId] ?? null : null}
              target={canPickTarget ? dispatchTarget : null}
              onMapClick={
                canPickTarget
                  ? (lat, lng) => setDispatchTarget({ lat, lng, label: "지도에서 고른 위치", mode: "map" })
                  : undefined
              }
            />
          </div>
        </div>

        <HospitalCandidateListPanel
          data={myResult}
          confirmedHospitalId={confirmedHospitalId}
          pendingHospitalId={pendingConfirmId}
          scene={activeCaseId ? state.sceneCandidates[activeCaseId] ?? null : null}
          onApprove={handleApprove}
        />
      </div>
    </div>
  );
}

// 시안 레이아웃 — 넓은 화면(1100px↑)은 한 화면에 고정하고 왼쪽 열만 스크롤, 좁으면 세로로 쌓인다.
// 화면 전체는 끌리지 않게 고정(2026-10-05 요청) — 페이지 스크롤·당겨서 새로고침(overscroll)·글자/이미지 끌기를 막고,
// 넘치는 내용은 왼쪽 열(세로)과 후보 카드 줄(가로) 안에서만 스크롤된다. 태블릿 주소창 높이 변화는 dvh로 흡수.
const PAGE_CSS = `
html,body{overflow:hidden;overscroll-behavior:none;height:100%}
.amb-root{height:100vh;height:100dvh;overflow:hidden;overscroll-behavior:none;user-select:none;-webkit-user-select:none;-webkit-touch-callout:none}
.amb-root input,.amb-root textarea{user-select:text;-webkit-user-select:text}
.amb-root img,.amb-root a{-webkit-user-drag:none}
.amb-page{box-sizing:border-box;width:100%;max-width:1440px;margin:0 auto;padding:10px 20px;display:flex;flex-direction:column;gap:8px;height:100%;overflow:hidden;white-space:nowrap}
.amb-top{flex:1 1 auto;min-height:0;display:flex;flex-wrap:nowrap;align-items:stretch;gap:16px}
.amb-left{flex:0 1 360px;min-width:300px;min-height:0;overflow-y:auto;overscroll-behavior:contain;padding-right:2px;display:flex;flex-direction:column;gap:8px}
.amb-map{flex:1 1 520px;min-width:0;min-height:0;display:flex;flex-direction:column}
.amb-hscroll{overscroll-behavior:contain}
@media (max-width:720px){.amb-page{padding:10px 16px}.amb-left{min-width:0;flex-basis:300px}}
.amb-hscroll::-webkit-scrollbar,.amb-thin::-webkit-scrollbar{height:8px;width:6px}
.amb-hscroll::-webkit-scrollbar-track{background:${AD.line};border-radius:4px}
.amb-hscroll::-webkit-scrollbar-thumb,.amb-thin::-webkit-scrollbar-thumb{background:${AD.gray};border-radius:4px}
`;

// 시연용 자동 전환(2026-10-04): /ambulance?id=auto 로 열면 특정 구급대에 고정하지 않고,
// 상황이 발생해(콘솔 ① 출동) 어떤 구급대든 움직이기 시작하면 **그 구급대 화면으로 자동
// 로그인**된다 — 실무에선 발생 지점마다 출동 구급대가 달라서, 시연 중 탭을 바꿔 들어갈
// 필요가 없게 한다. 감시는 monitor 소켓으로 하고, 전환되면 그 apid의 정식 구급차
// 대시보드(자기 소켓)를 띄운다. 다른 구급대에서 새 출동이 생기면 그쪽으로 넘어간다.
function AmbulanceAutoFollow() {
  const { state, connectionMode } = useDashboardSocket({ role: "monitor", id: "ambulance-auto" });
  const [apid, setApid] = useState<string | null>(null);
  const active = Object.values(state.ambulanceSim).find(
    (sim) => !["idle", "returning"].includes(sim.phase),
  );
  // 지금 보는 구급대의 사건이 끝나면 곧바로 대기 화면으로 되돌린다(2026-10-04) — 시연 초기화(즉시 기지 대기),
  // 상황 취소(사건 없이 기지 복귀 중), 수용 완료 후 복귀 모두. 예전엔 한 번 전환되면 그 구급대 화면에 남았고,
  // 그다음엔 기지에 도착(idle)해야만 돌아와서 상황 취소 뒤 복귀 이동 동안 끝난 사건 화면이 남아 있었다.
  const currentSim = apid ? state.ambulanceSim[apid] ?? null : null;
  const caseEnded = currentSim !== null && !currentSim.caseId && ["idle", "returning"].includes(currentSim.phase);
  // 렌더 중 조건부 갱신(React 권장 패턴 — effect에서 setState하면 렌더가 한 번 더 돈다)
  if (active && active.apid !== apid) setApid(active.apid);
  else if (!active && apid && caseEnded) setApid(null);
  if (apid) return <AmbulanceDashboardContent key={apid} apid={apid} />;
  return (
    <div
      className={css({
        display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center",
        gap: "3", minHeight: "100vh", backgroundColor: "bg", padding: "8", textAlign: "center",
      })}
    >
      <p className={css({ fontSize: "2xl" })}>🚑</p>
      <h1 className={css({ fontSize: "lg", fontWeight: "bold", color: "ink" })}>출동 대기 중</h1>
      <p className={css({ fontSize: "sm", color: "ink2" })}>
        상황이 발생하면 출동하는 구급대의 대시보드로 자동 전환됩니다. (시연용 자동 로그인)
      </p>
      <p className={css({ fontSize: "xs", color: CONNECTION_LABEL[connectionMode].color })}>
        {CONNECTION_LABEL[connectionMode].text}
      </p>
    </div>
  );
}

function AmbulancePageBody() {
  const searchParams = useSearchParams();
  const id = searchParams.get("id");
  if (id === "auto") return <AmbulanceAutoFollow />;
  return <AmbulanceDashboardContent apid={id} />;
}

export default function AmbulanceDashboardPage() {
  return (
    <Suspense fallback={null}>
      <AmbulancePageBody />
    </Suspense>
  );
}
