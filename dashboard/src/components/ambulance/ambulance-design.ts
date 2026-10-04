// 구급차 대시보드 디자인 시안(2026-10-05, "골든링크 시연 화면")의 색 — 화면 조각들이 같은 값을 쓰도록 한 곳에 둔다.
export const AD = {
  bg: "#F4F6FA",
  line: "#E3E7EE",
  control: "#D3D9E3",
  ink: "#1B2430",
  navy: "#14213D",
  ink3: "#4A5565",
  sub: "#5A6676",
  muted: "#7A8594",
  chip: "#F1F3F6",
  blue: "#1F4E9C",
  blueSoft: "#E8EEF8",
  green: "#168A55",
  greenSoft: "#E3F3EB",
  lime: "#4E8B1F",
  limeSoft: "#EEF5E6",
  orange: "#C75B00",
  orangeSoft: "#FFF1E0",
  approve: "#B45309",
  red: "#D93025",
  redSoft: "#FDECEA",
  gray: "#9AA3B0",
  skeleton: "#FAFBFC",
} as const;

// 카드(흰 바탕 · 연한 테두리 · 둥근 18px)
export const cardStyle = {
  background: "#FFFFFF",
  border: `1px solid ${AD.line}`,
  borderRadius: 18,
  boxSizing: "border-box",
} as const;

export function pill(bg: string, color: string, weight: 500 | 700 = 500) {
  return {
    background: bg,
    color,
    fontWeight: weight,
    fontSize: 10.5,
    padding: "3px 10px",
    borderRadius: 999,
    whiteSpace: "nowrap",
    flex: "none",
  } as const;
}
