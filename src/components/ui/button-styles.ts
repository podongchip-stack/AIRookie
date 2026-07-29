import { css } from "styled-system/css";

export const primaryButtonStyle = css({
  paddingX: "3.5",
  paddingY: "1.5",
  borderRadius: "full",
  fontSize: "sm",
  fontWeight: "semibold",
  color: "white",
  backgroundColor: "brand",
  cursor: "pointer",
  _hover: { backgroundColor: "brand.emphasis" },
  _disabled: { opacity: 0.4, cursor: "not-allowed" },
});

export const secondaryButtonStyle = css({
  paddingX: "5",
  paddingY: "2.5",
  borderRadius: "md",
  fontSize: "sm",
  fontWeight: "medium",
  color: "gray.700",
  backgroundColor: "gray.100",
  cursor: "pointer",
  _hover: { backgroundColor: "gray.200" },
  _disabled: { opacity: 0.4, cursor: "not-allowed" },
});

// 병원의 "승인"은 후보 등록일 뿐 최종 확정이 아니다 (CLAUDE.md). 구급대원의
// "이송 승인"(brand/amber)과 시각적 무게를 다르게 두기 위해 별도 색을 쓴다.
export const mintButtonStyle = css({
  paddingX: "3.5",
  paddingY: "1.5",
  borderRadius: "full",
  fontSize: "sm",
  fontWeight: "semibold",
  color: "white",
  backgroundColor: "mint",
  cursor: "pointer",
  _hover: { backgroundColor: "#0B8A5F" },
  _disabled: { opacity: 0.4, cursor: "not-allowed" },
});

export const dangerButtonStyle = css({
  paddingX: "3.5",
  paddingY: "1.5",
  borderRadius: "full",
  fontSize: "sm",
  fontWeight: "semibold",
  color: "coral",
  backgroundColor: "surface",
  borderWidth: "1px",
  borderColor: "coral",
  cursor: "pointer",
  _hover: { backgroundColor: "coralSoft" },
  _disabled: { opacity: 0.4, cursor: "not-allowed" },
});

export const inputStyle = css({
  width: "100%",
  borderWidth: "1px",
  borderColor: "gray.300",
  borderRadius: "md",
  paddingX: "2.5",
  paddingY: "1.5",
  fontSize: "sm",
  _focus: { borderColor: "brand", outline: "none" },
});
