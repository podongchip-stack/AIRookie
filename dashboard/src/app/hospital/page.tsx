"use client";

import { Suspense } from "react";
import { useSearchParams } from "next/navigation";
import { HospitalDashboard } from "@/components/hospital/HospitalDashboard";

// 병원 대시보드 — 첫 페이지에서 병원 접근 코드(H-<hpid>)를 입력해 연다(2026-10-03 회의로 관제 지도와 분리).
// 관제 지도는 병원 이름과 접근 코드를 보여줄 뿐 이 화면을 열지 않는다. 내용은 HospitalDashboard 컴포넌트.
function HospitalDashboardContent() {
  const searchParams = useSearchParams();
  return <HospitalDashboard hospitalId={searchParams.get("id") ?? ""} />;
}

export default function HospitalDashboardPage() {
  return (
    <Suspense fallback={null}>
      <HospitalDashboardContent />
    </Suspense>
  );
}
