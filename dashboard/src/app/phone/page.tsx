"use client";

import { Suspense, useState } from "react";
import { useSearchParams } from "next/navigation";
import { css } from "styled-system/css";
import { PhoneCallView } from "@/components/phone/PhoneCallView";
import { CONNECTION_LABEL, useDashboardSocket } from "@/hooks/use-dashboard-socket";

// 휴대폰 전화 앱(2026-10-03) — 구급대원 휴대폰 전용 주소 /phone?id=<apid>. 첫 페이지에서 P-<apid> 코드로 들어온다.
// 구급차 대시보드(/ambulance)와 주소를 나눠 "구급차 단말"과 "대원 휴대폰"의 역할을 분명히 했다 — 예전엔 같은
// 주소에서 화면 폭으로 갈랐는데, 태블릿을 세로로 세우거나 창을 좁히면 전화 화면으로 바뀌었다.
// hub에는 같은 apid의 구급차 탭(role=ambulance)으로 붙는다. 출동·현장 종료·이송 승인은 구급차 대시보드에서 한다.
function PhoneContent() {
  const apid = useSearchParams().get("id");
  if (apid === "auto") return <PhoneAutoFollow />;
  return <PhoneForApid apid={apid} />;
}

// 시연용 자동 전환(2026-10-04): /phone?id=auto(첫 페이지 P-AUTO) — 구급대 대시보드 자동 전환(/ambulance?id=auto)과
// 같은 규칙. 상황이 발생해 어떤 구급대든 출동하면 그 구급대의 전화 앱으로 바뀌고, 그 사건이 끝나면(상황 취소·
// 시연 초기화·수용 완료 후 복귀) 대기 화면으로 돌아온다. 구급대 대시보드와 달리, 지금 보는 구급대의 사건이
// 진행 중이면 다른 구급대가 새로 출동해도 넘어가지 않는다 — 통화 도중에 화면이 바뀌면 안 되기 때문이다.
function PhoneAutoFollow() {
  const { state, connectionMode } = useDashboardSocket({ role: "monitor", id: "phone-auto" });
  const [apid, setApid] = useState<string | null>(null);
  const current = apid ? state.ambulanceSim[apid] ?? null : null;
  const currentActive = current !== null && !!current.caseId && !["idle", "returning"].includes(current.phase);
  const active = Object.values(state.ambulanceSim).find(
    (sim) => !!sim.caseId && !["idle", "returning"].includes(sim.phase),
  );
  // 렌더 중 조건부 갱신(React 권장 패턴)
  if (!currentActive && active && active.apid !== apid) setApid(active.apid);
  else if (!currentActive && !active && apid) setApid(null);

  if (apid) return <PhoneForApid key={apid} apid={apid} />;
  return (
    <div
      className={css({
        display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center",
        gap: "3", minHeight: "100dvh", backgroundColor: "bg", padding: "6", textAlign: "center",
      })}
    >
      <p className={css({ fontSize: "3xl" })}>📞</p>
      <h1 className={css({ fontSize: "lg", fontWeight: "bold", color: "ink" })}>출동 대기 중</h1>
      <p className={css({ fontSize: "sm", color: "ink2" })}>
        상황이 발생하면 출동하는 구급대의 전화 앱으로 자동 전환됩니다. (시연용 자동 로그인)
      </p>
      <p className={css({ fontSize: "xs", color: CONNECTION_LABEL[connectionMode].color })}>
        {CONNECTION_LABEL[connectionMode].text}
      </p>
    </div>
  );
}

function PhoneForApid({ apid }: { apid: string | null }) {
  const { state, connectionMode, sendCallSignal, sendAudioChunk } = useDashboardSocket(
    apid ? { role: "ambulance", id: apid } : null,
  );

  if (!apid) {
    return (
      <p className={css({ padding: "8", color: "coral", fontSize: "sm", textAlign: "center" })}>
        구급차 ID가 없습니다. 첫 페이지에서 P-&lt;구급차ID&gt; 코드로 다시 들어와 주세요.
      </p>
    );
  }

  // 휴대폰은 사건을 만들지 않는다 — hub의 출동 시뮬레이션 상태가 알려 준 이 구급차의 현재 사건으로만 통화한다
  const simOn = state.identity.simDispatch === true;
  const mySim = state.ambulanceSim[apid] ?? null;
  const caseId = simOn ? mySim?.caseId ?? null : null;
  const matched = caseId ? state.matchResults[caseId] : undefined;

  return (
    <PhoneCallView
      apid={apid}
      ambulanceName={state.identity.name ?? matched?.ambulanceName ?? null}
      connectionMode={connectionMode}
      simOn={simOn}
      sim={mySim}
      caseId={caseId}
      scene={caseId ? state.sceneCandidates[caseId] ?? null : null}
      callStatus={caseId ? state.callStatus[caseId] ?? null : null}
      voiceLines={caseId ? state.callTranscripts[caseId] ?? [] : []}
      sentHospitalCount={matched ? matched.hospitals.length : null}
      callBlocked={caseId ? state.sceneInputMode[caseId] === "template" : false}
      onCallSignal={(signal, id, hospitalId) => sendCallSignal(signal, apid, id, { hospitalId, device: "phone" })}
      onAudioChunk={sendAudioChunk}
    />
  );
}

export default function PhonePage() {
  return (
    <Suspense fallback={null}>
      <PhoneContent />
    </Suspense>
  );
}
