"use client";

import { Suspense } from "react";
import { useSearchParams } from "next/navigation";
import { css } from "styled-system/css";
import { PhoneCallView } from "@/components/phone/PhoneCallView";
import { useDashboardSocket } from "@/hooks/use-dashboard-socket";

// 휴대폰 전화 앱(2026-10-03) — 구급대원 휴대폰 전용 주소 /phone?id=<apid>. 첫 페이지에서 P-<apid> 코드로 들어온다.
// 구급차 대시보드(/ambulance)와 주소를 나눠 "구급차 단말"과 "대원 휴대폰"의 역할을 분명히 했다 — 예전엔 같은
// 주소에서 화면 폭으로 갈랐는데, 태블릿을 세로로 세우거나 창을 좁히면 전화 화면으로 바뀌었다.
// hub에는 같은 apid의 구급차 탭(role=ambulance)으로 붙는다. 출동·현장 종료·이송 승인은 구급차 대시보드에서 한다.
function PhoneContent() {
  const apid = useSearchParams().get("id");
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
