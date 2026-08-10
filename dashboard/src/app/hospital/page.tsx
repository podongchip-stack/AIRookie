"use client";

import { Suspense } from "react";
import { useSearchParams } from "next/navigation";
import { css } from "styled-system/css";
import { HospitalTopBar } from "@/components/hospital/HospitalTopBar";
import { Legend } from "@/components/hospital/Legend";
import { CaseMatchPanel } from "@/components/hospital/CaseMatchPanel";
import { MapPanel } from "@/components/hospital/MapPanel";
import { useDashboardSocket } from "@/hooks/use-dashboard-socket";

// 병원 대시보드는 병원 1곳 전용 화면이라 자신의 병원 ID가 고정된다.
// 랜딩 페이지(src/app/page.tsx)의 코드 입력에서 "?id="로 넘어온 값을 사용하고,
// 직접 URL로 들어온 경우(id 없음)에는 개발 편의를 위해 mock 데이터의 "C"를 기본값으로 쓴다.
const DEFAULT_HOSPITAL_ID = "C";

function HospitalDashboardContent() {
  const searchParams = useSearchParams();
  const MY_HOSPITAL_ID = searchParams.get("id") ?? DEFAULT_HOSPITAL_ID;
  const { state, connectionMode, sendAction } = useDashboardSocket();

  const myHospital =
    state.matchResult?.hospitals.find((h) => h.hospitalId === MY_HOSPITAL_ID) ?? null;

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
      <HospitalTopBar
        status={myHospital?.status ?? null}
        connectionMode={connectionMode}
        since={state.receivedAt}
      />
      <Legend />

      <main
        className={css({
          display: "grid",
          // 예상 병명 · 수용 판단 쪽에 더 넓은 공간을 준다 — 나중에 여러 구급차(사건)를
          // 동시에 보여주게 되면 이 컬럼이 카드 목록을 담을 자리라, 지금부터 넉넉하게 잡아둔다.
          gridTemplateColumns: { base: "1fr", lg: "1.8fr 1fr" },
          gap: "6",
          alignItems: "stretch",
          flex: "1",
          minHeight: "0",
        })}
      >
        <CaseMatchPanel
          patientInfo={state.matchResult?.patientInfo ?? null}
          hospital={myHospital}
          hospitalId={MY_HOSPITAL_ID}
          onAction={sendAction}
        />

        <MapPanel hospital={myHospital} />
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

export default function HospitalDashboardPage() {
  return (
    <Suspense fallback={null}>
      <HospitalDashboardContent />
    </Suspense>
  );
}
