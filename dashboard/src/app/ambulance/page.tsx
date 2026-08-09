"use client";

import { useState } from "react";
import { css } from "styled-system/css";
import { AmbulanceTopBar } from "@/components/ambulance/AmbulanceTopBar";
import { Legend } from "@/components/hospital/Legend";
import { CallSummaryEditablePanel } from "@/components/ambulance/CallSummaryEditablePanel";
import { CallDemoPanel } from "@/components/ambulance/CallDemoPanel";
import { HospitalCandidateListPanel } from "@/components/ambulance/HospitalCandidateListPanel";
import { CandidateMapPanel } from "@/components/ambulance/CandidateMapPanel";
import { useDashboardSocket } from "@/hooks/use-dashboard-socket";

export default function AmbulanceDashboardPage() {
  const { state, connectionMode, sendAction, sendCallSignal, sendAudioChunk } = useDashboardSocket();
  const [confirmedHospitalId, setConfirmedHospitalId] = useState<string | null>(null);

  function handleApprove(hospitalId: string) {
    setConfirmedHospitalId(hospitalId);
    sendAction({
      action: "final_approval",
      hospital_id: hospitalId,
      actor: "paramedic",
      timestamp: new Date().toISOString(),
    });
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
            <CallSummaryEditablePanel data={state.matchResult} />
          </div>
          <div className={css({ flex: "3 1 0", minHeight: "0" })}>
            <CallDemoPanel onCallSignal={sendCallSignal} onAudioChunk={sendAudioChunk} />
          </div>
        </div>

        <HospitalCandidateListPanel
          data={state.matchResult}
          confirmedHospitalId={confirmedHospitalId}
          onApprove={handleApprove}
        />

        <div
          className={css({
            gridColumn: { base: "1", md: "1 / span 2", lg: "3" },
          })}
        >
          <CandidateMapPanel data={state.matchResult} confirmedHospitalId={confirmedHospitalId} />
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
