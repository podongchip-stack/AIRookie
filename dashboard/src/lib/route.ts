// 지도에 그릴 도로 경로를 hub의 GET /route에서 받아온다(2026-09-24). hub가 카카오모빌리티
// 자동차 길찾기를 대신 불러 준다 — REST API 키는 서버 전용이라 브라우저가 직접 부르지 않는다.
// dashboard는 hub와만 통신한다는 원칙(CLAUDE.md)도 그대로다. 키가 없거나 조회에 실패하면
// null을 돌려주고, 지도는 지금처럼 직선을 그린다.
export async function fetchRoadPath(caseId: string, hospitalId: string): Promise<[number, number][] | null> {
  const httpUrl = process.env.NEXT_PUBLIC_HUB_HTTP_URL;
  if (!httpUrl) return null;
  try {
    const query = `caseId=${encodeURIComponent(caseId)}&hospitalId=${encodeURIComponent(hospitalId)}`;
    const response = await fetch(`${httpUrl}/route?${query}`);
    if (!response.ok) return null;
    const data = (await response.json()) as { path?: [number, number][] | null };
    return data.path && data.path.length >= 2 ? data.path : null;
  } catch {
    return null;
  }
}
