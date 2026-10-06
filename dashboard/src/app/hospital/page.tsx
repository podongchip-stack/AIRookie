"use client";

import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { css } from "styled-system/css";
import { HospitalDashboard } from "@/components/hospital/HospitalDashboard";
import { CONNECTION_LABEL, useDashboardSocket } from "@/hooks/use-dashboard-socket";
import { DemoVideoOverlay } from "@/components/ui/DemoVideoOverlay";

// 시연용 자동 로그인(2026-10-04): /hospital?id=auto — 특정 병원에 고정하지 않고, 사건이
// 병원들에 수용 요청을 보내는 순간 **그 사건의 1순위 병원**(이송이 확정되면 확정 병원)
// 대시보드로 자동 전환된다. 구급대 자동 전환(/ambulance?id=auto)과 짝 — 시연 중 관제에서
// H-코드를 찾아 입력할 필요가 없어진다. 사건이 끝나면 대기 화면으로 돌아온다.
function HospitalAutoFollow() {
  const { state, connectionMode } = useDashboardSocket({ role: "monitor", id: "hospital-auto" });
  const [hpid, setHpid] = useState<string | null>(null);
  const cases = Object.values(state.monitorCases);
  // 최신 사건 기준 — 확정 병원이 있으면 그쪽(도착 결과까지 그 병원 화면이 담당), 없으면 아직 거절하지
  // 않은 병원 중 1순위(hub가 보낸 순서). 거절한 병원(병상 없음 포함)은 건너뛴다(2026-10-04).
  let target: string | null = null;
  for (const monitorCase of cases) {
    const confirmed = monitorCase.hospitals.find((h) => h.status === "confirmed");
    const open = monitorCase.hospitals.find((h) => h.status !== "rejected");
    target = (confirmed ?? open)?.hospitalId ?? target;
  }
  // 지금 보는 병원이 아직 응답할 수 있는 후보/확정이면 화면을 유지한다(요청 도중 널뛰기 방지).
  // 거절하면(2026-10-04) 더는 유지 대상이 아니라 다음 후보 병원 화면으로 넘어간다 — 예전엔 거절해도
  // 후보 목록에 남아 있다는 이유로 그 병원 화면에 멈춰 있었다.
  const stillRelevant = hpid
    ? cases.some((c) => c.hospitals.some((h) => h.hospitalId === hpid && h.status !== "rejected"))
    : false;
  // 처음 전환·사건 종료는 렌더 중에 바로(React 권장 패턴), 거절 뒤 다음 병원으로는 1.5초 뒤에
  // (그 병원 화면에 거절 결과가 잠깐 보이도록) 넘긴다.
  if (!hpid && target) setHpid(target);
  else if (hpid && !stillRelevant && !target) setHpid(null);
  const nextAfterReject = hpid && !stillRelevant && target && target !== hpid ? target : null;
  useEffect(() => {
    if (!nextAfterReject) return;
    const timer = setTimeout(() => setHpid(nextAfterReject), 1500);
    return () => clearTimeout(timer);
  }, [nextAfterReject]);

  if (hpid) return <HospitalDashboard key={hpid} hospitalId={hpid} />;
  return (
    <div
      className={css({
        display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center",
        gap: "3", minHeight: "100vh", backgroundColor: "bg", padding: "8", textAlign: "center",
      })}
    >
      <p className={css({ fontSize: "2xl" })}>🏥</p>
      <h1 className={css({ fontSize: "lg", fontWeight: "bold", color: "ink" })}>수용 요청 대기 중</h1>
      <p className={css({ fontSize: "sm", color: "ink2" })}>
        사건이 병원에 수용 요청을 보내면 그 사건의 1순위 병원 대시보드로 자동 전환됩니다. (시연용 자동 로그인)
      </p>
      <p className={css({ fontSize: "xs", color: CONNECTION_LABEL[connectionMode].color })}>
        {CONNECTION_LABEL[connectionMode].text}
      </p>
    </div>
  );
}

// 병원 대시보드 — 첫 페이지에서 병원 접근 코드(H-<hpid>)를 입력해 연다(2026-10-03 회의로 관제 지도와 분리).
// 관제 지도는 병원 이름과 접근 코드를 보여줄 뿐 이 화면을 열지 않는다. 내용은 HospitalDashboard 컴포넌트.
function HospitalDashboardContent() {
  const searchParams = useSearchParams();
  const id = searchParams.get("id");
  if (id === "auto") return <HospitalAutoFollow />;
  return <HospitalDashboard hospitalId={id ?? ""} />;
}

export default function HospitalDashboardPage() {
  return (
    <>
      <Suspense fallback={null}>
        <HospitalDashboardContent />
      </Suspense>
      <DemoVideoOverlay src="/demo-videos/hospital.mp4" />
    </>
  );
}
