"use client";

import { useState } from "react";
import { css } from "styled-system/css";
import { AmbulanceTopBar } from "@/components/ambulance/AmbulanceTopBar";
import { Legend } from "@/components/hospital/Legend";
import { CallSummaryEditablePanel } from "@/components/ambulance/CallSummaryEditablePanel";
import { HospitalCandidateListPanel } from "@/components/ambulance/HospitalCandidateListPanel";
import { VitalsEcgPanel } from "@/components/hospital/VitalsEcgPanel";
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
        since={state.callSummary?.transcript.timestamp ?? null}
      />
      <Legend />

      <main
        className={css({
          display: "grid",
          gridTemplateColumns: { base: "1fr", md: "1fr 1fr", lg: "1fr 1.15fr 1.05fr" },
          gridTemplateRows: { base: "none", lg: "auto minmax(0, 1fr)" },
          gap: "6",
          alignItems: "stretch",
          flex: "1",
          minHeight: "0",
        })}
      >
        <div
          className={css({
            gridColumn: { base: "1", lg: "1" },
            gridRow: { base: "auto", lg: "1" },
          })}
        >
          <CallSummaryEditablePanel data={state.callSummary} />
        </div>

        <div
          className={css({
            gridColumn: { base: "1", md: "2", lg: "2" },
            gridRow: { base: "auto", lg: "1" },
          })}
        >
          <HospitalCandidateListPanel
            data={state.hospitalMatch}
            confirmedHospitalId={confirmedHospitalId}
            onApprove={handleApprove}
          />
        </div>

        <div
          className={css({
            gridColumn: { base: "1", md: "1 / span 2", lg: "3" },
            gridRow: { base: "auto", lg: "1 / span 2" },
          })}
        >
          <CandidateMapPanel data={state.hospitalMatch} confirmedHospitalId={confirmedHospitalId} />
        </div>

        <div
          className={css({
            gridColumn: { base: "1", md: "1 / span 2", lg: "1 / span 2" },
            gridRow: "auto",
          })}
        >
          <VitalsEcgPanel data={state.vitals} subtitle="현재 측정 중" showLockNote={false} layout="grid" />
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
