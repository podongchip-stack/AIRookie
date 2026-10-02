import { redirect } from "next/navigation";

// 병원 대시보드는 주소로 직접 열지 않는다(2026-10-03). 관제 지도(/map)에서 환자 요청이 온 병원을 눌러
// 지도 위에 띄운다 — 예전 주소(/hospital?id=)로 들어오면 관제 지도로 보낸다.
export default function HospitalDashboardPage() {
  redirect("/map");
}
