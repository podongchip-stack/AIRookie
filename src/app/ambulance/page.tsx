"use client";

import { useState } from "react";
import { css } from "styled-system/css";
import { AmbulanceTopBar } from "@/components/ambulance/AmbulanceTopBar";
import { Legend } from "@/components/hospital/Legend";
import { CallSummaryEditablePanel } from "@/components/ambulance/CallSummaryEditablePanel";
import { HospitalCandidateListPanel } from "@/components/ambulance/HospitalCandidateListPanel";
import { CandidateMapPanel } from "@/components/ambulance/CandidateMapPanel";
import { useDashboardSocket } from "@/hooks/use-dashboard-socket";

export default function AmbulanceDashboardPage() {
  const { state, connectionMode, sendAction } = useDashboardSocket();
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
        <CallSummaryEditablePanel data={state.matchResult} />

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
