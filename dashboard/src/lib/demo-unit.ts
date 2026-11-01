// 한 구급대에 기기를 고정해 진행하는 시연. 좌표·시나리오는 가상, 레지스트리는 실제 등록 ID.
export const DEMO_UNIT = {
  apid: "SEL0111",
  name: "역삼119안전센터 구급 1",
  phoneCode: "P-SEL0111",
  tabletCode: "A-SEL0111",
} as const;

export const UNIT_SCENARIOS = [
  { key: "cardiac", title: "강남역 흉통 환자", detail: "62세 남성 · 흉통과 호흡곤란 · 심근경색 의심", spot: { label: "강남역 인근 · 흉통 신고", lat: 37.4979, lng: 127.0276 } },
  { key: "trauma", title: "역삼역 교통사고", detail: "35세 남성 · 차량 충돌 · 흉부·복부 손상 의심", spot: { label: "역삼역 인근 · 교통사고", lat: 37.5007, lng: 127.0365 } },
] as const;
