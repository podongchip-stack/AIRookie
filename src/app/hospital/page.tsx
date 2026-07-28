"use client";

import { DashboardShell } from "@/components/layout/DashboardShell";
import { CallSummaryPanel } from "@/components/panels/CallSummaryPanel";
import { VitalsPanel } from "@/components/panels/VitalsPanel";
import { HospitalListPanel } from "@/components/panels/HospitalListPanel";
import { ApprovalActions } from "@/components/panels/ApprovalActions";
import { useDashboardSocket } from "@/hooks/use-dashboard-socket";

// 병원 대시보드는 병원 1곳 전용 화면이라 자신의 병원 ID가 고정된다.
// 인증/병원별 라우팅이 붙기 전까지는 mock 데이터의 "A" 병원을 사용한다.
const MY_HOSPITAL_ID = "A";

export default function HospitalDashboardPage() {
  const { state, connectionMode, sendAction } = useDashboardSocket();

  return (
    <DashboardShell role="hospital" connectionMode={connectionMode}>
      <CallSummaryPanel data={state.callSummary} />
      <VitalsPanel data={state.vitals} />
      <HospitalListPanel data={state.hospitalMatch} />
      <ApprovalActions
        role="hospital"
        hospitalId={MY_HOSPITAL_ID}
        onAction={sendAction}
      />
    </DashboardShell>
  );
}
