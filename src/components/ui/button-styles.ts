import { css } from "styled-system/css";

export const primaryButtonStyle = css({
  paddingX: "4",
  paddingY: "2",
  borderRadius: "md",
  fontSize: "sm",
  fontWeight: "semibold",
  color: "white",
  backgroundColor: "brand",
  cursor: "pointer",
  _hover: { backgroundColor: "brand.emphasis" },
  _disabled: { opacity: 0.4, cursor: "not-allowed" },
});

export const secondaryButtonStyle = css({
  paddingX: "4",
  paddingY: "2",
  borderRadius: "md",
  fontSize: "sm",
  fontWeight: "medium",
  color: "gray.700",
  backgroundColor: "gray.100",
  cursor: "pointer",
  _hover: { backgroundColor: "gray.200" },
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
