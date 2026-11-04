// 시·도 소방본부(2026-11-04) — 다수 사상자 등록에서 구급차가 모자랄 때 "인근 지역 지원 요청" 후보를 고르는 데 쓴다.
// 좌표는 본부가 있는 도시의 **대략 위치**다(정확한 청사 좌표가 아님) — 화면에도 그렇게 표시한다. 규칙 기반.

export interface FireHq {
  name: string;
  city: string;
  lat: number;
  lng: number;
}

export const FIRE_HQ: FireHq[] = [
  { name: "서울소방재난본부", city: "서울", lat: 37.5665, lng: 126.978 },
  { name: "경기도소방재난본부", city: "수원", lat: 37.2636, lng: 127.0286 },
  { name: "경기도북부소방재난본부", city: "의정부", lat: 37.7381, lng: 127.0337 },
  { name: "인천소방본부", city: "인천", lat: 37.4563, lng: 126.7052 },
  { name: "강원특별자치도소방본부", city: "춘천", lat: 37.8813, lng: 127.7298 },
  { name: "충청북도소방본부", city: "청주", lat: 36.6424, lng: 127.489 },
  { name: "충청남도소방본부", city: "홍성(내포)", lat: 36.6588, lng: 126.6728 },
  { name: "대전소방본부", city: "대전", lat: 36.3504, lng: 127.3845 },
  { name: "세종소방본부", city: "세종", lat: 36.48, lng: 127.289 },
  { name: "전북특별자치도소방본부", city: "전주", lat: 35.8242, lng: 127.148 },
  { name: "광주소방안전본부", city: "광주", lat: 35.1595, lng: 126.8526 },
  { name: "전라남도소방본부", city: "무안", lat: 34.99, lng: 126.48 },
  { name: "대구소방안전본부", city: "대구", lat: 35.8714, lng: 128.6014 },
  { name: "경상북도소방본부", city: "안동", lat: 36.5684, lng: 128.7294 },
  { name: "부산소방재난본부", city: "부산", lat: 35.1796, lng: 129.0756 },
  { name: "울산소방본부", city: "울산", lat: 35.5384, lng: 129.3114 },
  { name: "경상남도소방본부", city: "창원", lat: 35.2279, lng: 128.6811 },
  { name: "제주특별자치도소방안전본부", city: "제주", lat: 33.4996, lng: 126.5312 },
];

export function kmBetween(a: { lat: number; lng: number }, b: { lat: number; lng: number }): number {
  const rad = Math.PI / 180;
  const dLat = (b.lat - a.lat) * rad;
  const dLng = (b.lng - a.lng) * rad;
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(a.lat * rad) * Math.cos(b.lat * rad) * Math.sin(dLng / 2) ** 2;
  return 6371 * 2 * Math.asin(Math.sqrt(h));
}

/** 사고 지점에서 가까운 본부 순 — 맨 앞(관할로 보는 가장 가까운 본부)은 빼고 지원 요청 후보 n곳 */
export function supportCandidates(at: { lat: number; lng: number }, n = 3): (FireHq & { km: number })[] {
  const sorted = FIRE_HQ.map((h) => ({ ...h, km: kmBetween(at, h) })).sort((a, b) => a.km - b.km);
  return sorted.slice(1, 1 + n);
}
