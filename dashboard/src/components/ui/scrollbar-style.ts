import { css } from "styled-system/css";

// 스크롤 영역마다 브라우저 기본 스크롤바(진한 회색/검정)를 쓰면 전체 톤(연한
// 파스텔)과 안 어울려서, 옅고 투명한 스크롤바 스타일 하나로 통일해 재사용한다
// (구급차/병원 대시보드 공통). scrollbarWidth/scrollbarColor는 Firefox용,
// ::-webkit-scrollbar*는 Chrome/Edge용 — 둘 다 있어야 브라우저 상관없이 적용된다.
export const thinScrollbarStyle = css({
  scrollbarWidth: "thin",
  scrollbarColor: "rgba(203, 213, 225, 0.5) transparent",
  "&::-webkit-scrollbar": { width: "6px" },
  "&::-webkit-scrollbar-track": { backgroundColor: "transparent" },
  "&::-webkit-scrollbar-thumb": { backgroundColor: "rgba(203, 213, 225, 0.5)", borderRadius: "full" },
  "&::-webkit-scrollbar-thumb:hover": { backgroundColor: "rgba(203, 213, 225, 0.8)" },
});
