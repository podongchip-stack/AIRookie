// 거리 표시(2026-10-03) — 모든 대시보드가 같은 규칙으로 보여주도록 한 곳에 둔다.
// hub가 카카오 내비 기준 도로 거리(roadDistanceKm)를 주면 그것을, 못 받았으면(카카오 키 없음·반경 10km 밖·
// 조회 실패) 직선거리를 "추정"으로 구분해 보여준다. 예전엔 전부 직선거리였다.
export function distanceLabel(h: { distanceKm: number; roadDistanceKm?: number | null }): string {
  return h.roadDistanceKm != null ? `${h.roadDistanceKm}km` : `직선 ${h.distanceKm}km`;
}

export function distanceTitle(h: { roadDistanceKm?: number | null }): string {
  return h.roadDistanceKm != null ? "이동 거리 (카카오 내비 도로 기준)" : "직선 거리 (내비 경로를 못 받아 추정)";
}
