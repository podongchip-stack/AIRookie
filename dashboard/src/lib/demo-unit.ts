// 구급대 둘(같은 역삼119안전센터 소속)에 기기를 나눠 고정해 진행하는 시연(2026-11-03). 좌표·시나리오는 가상, 레지스트리는 실제 등록 ID.
// defaultScenario는 UNIT_SCENARIOS의 key — 두 사건의 중증도가 달라 첫 전화 추천 순위가 다르게 나오는 조합이 기본이다.
export const DEMO_UNITS = [
  { apid: "SEL0111", name: "역삼119안전센터 구급 1", short: "구급 1", phoneCode: "P-SEL0111", tabletCode: "A-SEL0111", defaultScenario: "cardiac" },
  { apid: "SEL0112", name: "역삼119안전센터 구급 2", short: "구급 2", phoneCode: "P-SEL0112", tabletCode: "A-SEL0112", defaultScenario: "mild" },
] as const;

export const DEMO_UNIT = DEMO_UNITS[0];

// Pre-KTAS 1~5 하나씩(2026-11-02). key는 DemoConsole의 신고 접수 상황(PATIENT_TEMPLATES)과 같다.
export const UNIT_SCENARIOS = [
  { key: "arrest", ktas: 1, title: "강남역 심정지", detail: "58세 남성 · 쓰러져 의식·호흡 없음, CPR 후 맥박 회복 · Pre-KTAS 1", spot: { label: "강남역 인근 · 심정지 신고", lat: 37.4979, lng: 127.0276 } },
  { key: "cardiac", ktas: 2, title: "선릉역 흉통 환자", detail: "62세 남성 · 흉통과 호흡곤란 · 심근경색 의심 · Pre-KTAS 2", spot: { label: "선릉역 인근 · 흉통 신고", lat: 37.5045, lng: 127.049 } },
  { key: "abdominal", ktas: 3, title: "삼성역 복통 환자", detail: "48세 여성 · 우하복부 통증과 구토 · 충수염 의심 · Pre-KTAS 3", spot: { label: "삼성역 인근 · 복통 신고", lat: 37.5088, lng: 127.0632 } },
  { key: "mild", ktas: 4, title: "역삼역 발목 염좌", detail: "24세 여성 · 보도 턱에서 발목을 접질림 · Pre-KTAS 4", spot: { label: "역삼역 인근 · 발목 부상 신고", lat: 37.5007, lng: 127.0365 } },
  { key: "minor", ktas: 5, title: "강남역 손바닥 찰과상", detail: "27세 여성 · 넘어져 손바닥이 쓸림, 출혈 거의 없음 · Pre-KTAS 5", spot: { label: "강남역 인근 · 경미한 부상 신고", lat: 37.4985, lng: 127.0282 } },
] as const;
