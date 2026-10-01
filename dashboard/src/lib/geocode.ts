import type { GeocodeResult } from "@/types/dashboard";

// 출동 시뮬레이션의 "주소 지정"(2026-10-01). hub의 GET /geocode가 카카오 장소·주소 검색을 대신 불러 준다 —
// REST 키는 서버 전용이라 브라우저가 직접 부르지 않는다(lib/route.ts와 같은 방식). apid를 주면 결과마다
// 그 구급차 기지에서의 예상 시간(분)이 붙는다. 실패하면 error 문구와 빈 목록.
export async function searchPlaces(query: string, apid: string): Promise<{ results: GeocodeResult[]; error?: string }> {
  const httpUrl = process.env.NEXT_PUBLIC_HUB_HTTP_URL;
  if (!httpUrl) return { results: [], error: "hub 주소가 없어 검색할 수 없습니다(목데이터 모드)" };
  try {
    const params = `query=${encodeURIComponent(query)}&apid=${encodeURIComponent(apid)}`;
    const response = await fetch(`${httpUrl}/geocode?${params}`);
    const data = (await response.json()) as { results?: GeocodeResult[]; error?: string };
    return { results: data.results ?? [], error: data.error };
  } catch {
    return { results: [], error: "검색에 실패했습니다" };
  }
}
