"use client";

import { css } from "styled-system/css";
import { HospitalTopBar } from "@/components/hospital/HospitalTopBar";
import { Legend } from "@/components/hospital/Legend";
import { RawTranscriptPanel } from "@/components/hospital/RawTranscriptPanel";
import { SummaryCapacityPanel } from "@/components/hospital/SummaryCapacityPanel";
import { VitalsEcgPanel } from "@/components/hospital/VitalsEcgPanel";
import { MapPanel } from "@/components/hospital/MapPanel";
import { useDashboardSocket } from "@/hooks/use-dashboard-socket";

// 병원 대시보드는 병원 1곳 전용 화면이라 자신의 병원 ID가 고정된다.
// 인증/병원별 라우팅이 붙기 전까지는 mock 데이터의 "C"(이송 확정 예시)를 사용한다.
const MY_HOSPITAL_ID = "C";

export default function HospitalDashboardPage() {
  const { state, sendAction } = useDashboardSocket();

  const myHospital =
    state.hospitalMatch?.hospitals.find((h) => h.hospital_id === MY_HOSPITAL_ID) ?? null;

  return (
    <div className={css({ minHeight: "full", backgroundColor: "bg", padding: "10", margin: "10", borderWidth: "1px", borderColor: "line", borderRadius: "panel" })}>
      <HospitalTopBar
        status={myHospital?.status ?? null}
        since={state.callSummary?.transcript.timestamp ?? null}
      />
      <Legend />

      <main
        className={css({
          display: "grid",
          gridTemplateColumns: { base: "1fr", md: "1fr 1fr", lg: "1fr 1.15fr 1.05fr" },
          gridTemplateRows: { base: "none", lg: "auto minmax(0, 1fr)" },
          gap: "4.5",
          alignItems: "stretch",
        })}
      >
        <div
          className={css({
            gridColumn: { base: "1", lg: "1" },
            gridRow: { base: "auto", lg: "1" },
          })}
        >
          <RawTranscriptPanel data={state.callSummary} />
        </div>

        <div
          className={css({
            gridColumn: { base: "1", md: "2", lg: "2" },
            gridRow: { base: "auto", lg: "1" },
          })}
        >
          <SummaryCapacityPanel
            data={state.callSummary}
            vitals={state.vitals}
            capacity={state.hospitalCapacity}
            hospitalId={MY_HOSPITAL_ID}
            onAction={sendAction}
          />
        </div>

        <div
          className={css({
            gridColumn: { base: "1", md: "1 / span 2", lg: "3" },
            gridRow: { base: "auto", lg: "1 / span 2" },
          })}
        >
          <VitalsEcgPanel data={state.vitals} />
        </div>

        <div
          className={css({
            gridColumn: { base: "1", md: "1 / span 2", lg: "1 / span 2" },
            gridRow: "auto",
          })}
        >
          <MapPanel hospital={myHospital} />
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
        AI는 환자 정보 구조화와 기록 자동화만 수행합니다. 수용 결정은 본원 의료진의 판단입니다.
      </p>
    </div>
  );
}
