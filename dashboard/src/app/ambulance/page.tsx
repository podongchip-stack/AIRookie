"use client";

import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { css } from "styled-system/css";
import { AmbulanceTopBar } from "@/components/ambulance/AmbulanceTopBar";
import { Legend } from "@/components/hospital/Legend";
import { CallSummaryEditablePanel } from "@/components/ambulance/CallSummaryEditablePanel";
import { CallDemoPanel } from "@/components/ambulance/CallDemoPanel";
import { HospitalCandidateListPanel } from "@/components/ambulance/HospitalCandidateListPanel";
import { CandidateMapPanel } from "@/components/ambulance/CandidateMapPanel";
import { DispatchControlPanel } from "@/components/ambulance/DispatchControlPanel";
import { useDashboardSocket } from "@/hooks/use-dashboard-socket";
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

function AmbulanceDashboardContent() {
  const searchParams = useSearchParams();
  const apid = searchParams.get("id");
  const { state, connectionMode, sendAction, sendCallSignal, sendAudioChunk, sendSimCommand } = useDashboardSocket(
    apid ? { role: "ambulance", id: apid } : null,
  );
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

  // 기본은 내가 연 통화(myCaseId)의 결과다. 그 caseId조차 모를 때(새 탭 등)는 hub가 준
  // 결과 중 이 구급차(apid)의 가장 최근 사건을 되찾아 쓴다 — hub는 연결 때 이 구급차의
  // 진행 중인 사건을 따라잡기로 보내준다. myCaseId가 있으면(새 통화 진행 중) 예전
  // 사건으로 대체하지 않는다: 새 결과가 오기 전에 지난 환자 정보를 띄우면 안 된다.
  const ownResults = Object.values(state.matchResults).filter((r) => r.apid === apid);
  const myResult = myCaseId
    ? state.matchResults[myCaseId] ?? null
    : ownResults[ownResults.length - 1] ?? null;
  const activeCaseId = myResult?.caseId ?? myCaseId;
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

  // 출동 시뮬레이션(hub --sim-dispatch, 2026-10-01). 켜져 있으면 caseId는 [이동] 때 만들고,
  // 통화 시작은 현장 도착 뒤 그 사건으로만 한다(hub도 같은 규칙으로 거부한다).
  const simOn = state.identity.simDispatch === true;
  const mySim = apid ? state.ambulanceSim[apid] ?? null : null;
  const [callActive, setCallActive] = useState(false);
  // 출동 위치(주소 검색·지도 클릭). 없으면 무작위. 출동하면 비운다.
  const [dispatchTarget, setDispatchTarget] = useState<DispatchTarget | null>(null);
  const canPickTarget = simOn && ["idle", "returning"].includes(mySim?.phase ?? "idle");
  const onSceneForMyCase = mySim?.phase === "on_scene" && mySim.caseId === myCaseId;
  const startBlockedReason = simOn && !onSceneForMyCase ? "현장 도착 후 통화할 수 있습니다" : null;

  function handleDispatch() {
    if (!apid) return;
    const caseId = crypto.randomUUID();
    setMyCaseId(caseId);
    setPendingConfirm(null);
    if (!sendSimCommand("dispatch", apid, caseId, dispatchTarget)) alertNotSent();
    else setDispatchTarget(null);
  }

  function handleSceneEnd() {
    if (!apid || !activeCaseId) return;
    if (!sendSimCommand("scene_end", apid, activeCaseId)) alertNotSent();
  }

  function handleCallSignal(signal: CallSignalType) {
    if (!apid) return;
    setCallActive(signal === "call_started");
    if (signal === "call_started" && simOn) {
      if (myCaseId && !sendCallSignal(signal, apid, myCaseId)) alertNotSent();
    } else if (signal === "call_started") {
      // mock 모드에선 고정 caseId를 써야 mock-data.ts의 mockHubMatchResult
      // (caseId: "case-mock-demo")와 실제로 매칭된다 — crypto.randomUUID()로
      // 만들면 mock 데이터의 고정 ID와 절대 일치하지 않아 "통화 시작"을 눌러도
      // 영원히 수신 대기 중으로 남는다(2026-08-11 실제로 재현됨).
      const caseId = connectionMode === "mock" ? "case-mock-demo" : crypto.randomUUID();
      setMyCaseId(caseId);
      setPendingConfirm(null);
      if (!sendCallSignal(signal, apid, caseId)) alertNotSent();
    } else if (activeCaseId) {
      if (!sendCallSignal(signal, apid, activeCaseId)) alertNotSent();
    }
  }

  function handleApprove(hospitalId: string) {
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
      <AmbulanceTopBar
        confirmed={confirmedHospitalId != null}
        connectionMode={connectionMode}
        since={state.receivedAt}
        ambulanceId={apid}
        ambulanceName={state.identity.name ?? myResult?.ambulanceName ?? null}
      />
      <Legend />

      <main
        className={css({
          display: "grid",
          gridTemplateColumns: { base: "1fr", md: "1fr 1fr", lg: "1fr 1.15fr 1.05fr" },
          gap: "6",
          alignItems: "stretch",
          flex: "1",
          minHeight: "0",
        })}
      >
        <div className={css({ display: "flex", flexDirection: "column", gap: "6", minHeight: "0" })}>
          {/* 통화 요약은 내용(예상 병명·증상)이 길어지면 스크롤 대신 카드 자체가
              늘어나도록 높이를 내용에 맡긴다(flex-basis:auto, flex-grow:0) —
              대신 통화 시연 쪽이 flex:1로 남는 공간을 전부 흡수한다(2026-08-12,
              고정 비율(2:3)로 나누던 이전 방식에서 전환). */}
          <div className={css({ flex: "0 0 auto" })}>
            <CallSummaryEditablePanel data={myResult} />
          </div>
          {simOn && (
            <DispatchControlPanel
              apid={apid}
              sim={mySim}
              target={dispatchTarget}
              onTargetChange={setDispatchTarget}
              confirmed={confirmedHospitalId != null}
              callActive={callActive}
              onDispatch={handleDispatch}
              onSceneEnd={handleSceneEnd}
            />
          )}
          <div className={css({ flex: "1", minHeight: "0" })}>
            <CallDemoPanel
              onCallSignal={handleCallSignal}
              onAudioChunk={sendAudioChunk}
              startBlockedReason={startBlockedReason}
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

        <div
          className={css({
            gridColumn: { base: "1", md: "1 / span 2", lg: "3" },
          })}
        >
          <CandidateMapPanel
            data={myResult}
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
        AI는 환자 정보 구조화와 기록 자동화만 수행합니다. 이송 최종 승인은 구급대원의 판단입니다.
      </p>
    </div>
  );
}

export default function AmbulanceDashboardPage() {
  return (
    <Suspense fallback={null}>
      <AmbulanceDashboardContent />
    </Suspense>
  );
}
