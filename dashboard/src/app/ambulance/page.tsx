"use client";

import { Suspense, useState } from "react";
import { useSearchParams } from "next/navigation";
import { css } from "styled-system/css";
import { AmbulanceTopBar } from "@/components/ambulance/AmbulanceTopBar";
import { Legend } from "@/components/hospital/Legend";
import { CallSummaryEditablePanel } from "@/components/ambulance/CallSummaryEditablePanel";
import { CallDemoPanel } from "@/components/ambulance/CallDemoPanel";
import { HospitalCandidateListPanel } from "@/components/ambulance/HospitalCandidateListPanel";
import { CandidateMapPanel } from "@/components/ambulance/CandidateMapPanel";
import { useDashboardSocket } from "@/hooks/use-dashboard-socket";
import type { CallSignalType } from "@/types/dashboard";

// 이 프로세스(voice)는 구급차 1대 전용이라 사건도 한 번에 하나만 진행된다 —
// 병원과 달리 여러 사건을 동시에 다룰 필요가 없다. 다만 hub가 어느 구급차·
// 사건인지 구분할 수 있어야 하므로, 자기 apid(URL의 ?id=)와 통화 시작마다
// 새로 만드는 caseId를 실어 보낸다 (feature/hub 담당자 참고사항 참고).
function AmbulanceDashboardContent() {
  const searchParams = useSearchParams();
  const apid = searchParams.get("id");
  const { state, connectionMode, sendAction, sendCallSignal, sendAudioChunk } = useDashboardSocket(
    apid ? { role: "ambulance", id: apid } : null,
  );
  const [confirmedHospitalId, setConfirmedHospitalId] = useState<string | null>(null);
  const [myCaseId, setMyCaseId] = useState<string | null>(null);

  const myResult = myCaseId ? state.matchResults[myCaseId] ?? null : null;

  function handleCallSignal(signal: CallSignalType) {
    if (!apid) return;
    if (signal === "call_started") {
      // mock 모드에선 고정 caseId를 써야 mock-data.ts의 mockHubMatchResult
      // (caseId: "case-mock-demo")와 실제로 매칭된다 — crypto.randomUUID()로
      // 만들면 mock 데이터의 고정 ID와 절대 일치하지 않아 "통화 시작"을 눌러도
      // 영원히 수신 대기 중으로 남는다(2026-08-11 실제로 재현됨).
      const caseId = connectionMode === "mock" ? "case-mock-demo" : crypto.randomUUID();
      setMyCaseId(caseId);
      setConfirmedHospitalId(null);
      sendCallSignal(signal, apid, caseId);
    } else if (myCaseId) {
      sendCallSignal(signal, apid, myCaseId);
    }
  }

  function handleApprove(hospitalId: string) {
    if (!myCaseId) return;
    setConfirmedHospitalId(hospitalId);
    sendAction({
      caseId: myCaseId,
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
        ambulanceName={myResult?.ambulanceName ?? null}
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
          {/* 통화 요약보다 통화 시연(실시간 텍스트 변환) 쪽에 더 넓은 공간을 준다 — flex-basis를
              0으로 고정해서 내용 크기가 아니라 비율(2:3)로만 나뉘게 한다. */}
          <div className={css({ flex: "2 1 0", minHeight: "0" })}>
            <CallSummaryEditablePanel data={myResult} />
          </div>
          <div className={css({ flex: "3 1 0", minHeight: "0" })}>
            <CallDemoPanel onCallSignal={handleCallSignal} onAudioChunk={sendAudioChunk} />
          </div>
        </div>

        <HospitalCandidateListPanel
          data={myResult}
          confirmedHospitalId={confirmedHospitalId}
          onApprove={handleApprove}
        />

        <div
          className={css({
            gridColumn: { base: "1", md: "1 / span 2", lg: "3" },
          })}
        >
          <CandidateMapPanel data={myResult} confirmedHospitalId={confirmedHospitalId} />
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
