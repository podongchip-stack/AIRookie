"use client";

import { useState } from "react";
import { DashboardShell } from "@/components/layout/DashboardShell";
import { CallSummaryPanel } from "@/components/panels/CallSummaryPanel";
import { VitalsPanel } from "@/components/panels/VitalsPanel";
import { HospitalListPanel } from "@/components/panels/HospitalListPanel";
import { ApprovalActions } from "@/components/panels/ApprovalActions";
import { useDashboardSocket } from "@/hooks/use-dashboard-socket";

export default function AmbulanceDashboardPage() {
  const { state, connectionMode, sendAction } = useDashboardSocket();
  const [selectedHospitalId, setSelectedHospitalId] = useState<string | null>(null);

  return (
    <DashboardShell role="ambulance" connectionMode={connectionMode}>
      <CallSummaryPanel data={state.callSummary} />
      <VitalsPanel data={state.vitals} />
      <HospitalListPanel
        data={state.hospitalMatch}
        selectedHospitalId={selectedHospitalId}
        onSelect={setSelectedHospitalId}
      />
      <ApprovalActions
        role="ambulance"
        hospitalId={selectedHospitalId}
        onAction={sendAction}
      />
    </DashboardShell>
  );
}
