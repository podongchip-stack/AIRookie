"use client";

import { CONNECTION_LABEL, type ConnectionMode } from "@/hooks/use-dashboard-socket";
import { formatElapsed, useElapsedSeconds } from "@/hooks/use-elapsed-time";
import { Viewer3DButton } from "@/components/hospital/Viewer3DButton";
import { VerificationButton } from "@/components/ui/VerificationButton";
import { HD } from "@/components/hospital/hospital-design";

// 병원 대시보드 상단바(2026-10-04 디자인 시안 "골든링크 병원 대시보드"). 왼쪽: 골든링크 · v2.0 · 본원 이름 ·
// 화면 이름 / 오른쪽: 진행 중인 사건 수 · 실시간 연동 · 정보 수신 후 경과 · 신뢰도 검증 · 3D 뷰어.
export function HospitalTopBar({
  caseCount,
  connectionMode,
  since,
  hospitalId,
  hospitalName,
  onClose,
}: {
  // 여러 구급차가 동시에 본원을 후보로 걸 수 있어(다중 사건) 진행 중인 사건 수를 보여준다
  caseCount: number;
  connectionMode: ConnectionMode;
  since: string | null;
  hospitalId: string;
  // hub가 알려준 실제 병원명. 아직 모르면 ID로 대체 표시한다.
  hospitalName: string | null;
  onClose?: () => void;
}) {
  const elapsed = useElapsedSeconds(since);
  const live = connectionMode === "live";

  return (
    <header
      style={{
        flex: "none", background: "#FFFFFF", borderRadius: 14, padding: "8px 18px", display: "flex", flexWrap: "wrap",
        alignItems: "center", justifyContent: "space-between", gap: "6px 20px", border: `1px solid ${HD.line}`,
      }}
    >
      <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: "8px 12px" }}>
        <span style={{ fontSize: 19, fontWeight: 900, color: HD.navy, letterSpacing: -0.3 }}>골든링크</span>
        <span style={{ fontSize: 10.5, fontWeight: 700, color: HD.blue, background: HD.blueSoft, borderRadius: 6, padding: "3px 7px" }}>v2.0</span>
        <span style={{ fontSize: 13, fontWeight: 700, color: HD.green, background: HD.greenSoft, borderRadius: 6, padding: "3px 9px" }}>
          {hospitalName ?? `병원 ID: ${hospitalId}`}
        </span>
        <span style={{ fontSize: 12, color: HD.sub }}>병원 대시보드 · 응급의학과 수용 판단</span>
      </div>
      <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: "8px 18px" }}>
        <span style={{ fontSize: 13.5, fontWeight: 700, color: HD.orange, background: HD.orangeSoft, borderRadius: 999, padding: "5px 13px" }}>
          {caseCount > 0 ? `진행 중인 사건 ${caseCount}건` : "수신 대기 중"}
        </span>
        <span style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 12, color: live ? HD.green : HD.orange }}>
          <span style={{ width: 7, height: 7, borderRadius: "50%", background: live ? HD.green : "#B0B7C2" }} />
          {CONNECTION_LABEL[connectionMode].text.replace(/^[●◌○]\s*/, "")}
        </span>
        <span style={{ fontSize: 12, color: HD.sub }}>
          정보 수신 후 <b style={{ color: HD.navy, fontSize: 15, fontWeight: 700 }}>{formatElapsed(elapsed)}</b> 경과
        </span>
        <VerificationButton hpid={hospitalId} />
        <Viewer3DButton />
        {onClose && (
          <button
            type="button"
            onClick={onClose}
            style={{ minHeight: 34, padding: "0 13px", borderRadius: 999, border: `1px solid ${HD.line}`, background: "#fff", color: HD.ink3, fontSize: 12.5, fontFamily: "inherit", cursor: "pointer" }}
          >
            닫기
          </button>
        )}
      </div>
    </header>
  );
}
