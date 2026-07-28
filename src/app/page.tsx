import Link from "next/link";
import { css } from "styled-system/css";

export default function Home() {
  return (
    <main
      className={css({
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        gap: "6",
        minHeight: "100vh",
        padding: "8",
        backgroundColor: "gray.50",
      })}
    >
      <div className={css({ display: "flex", flexDirection: "column", gap: "1", textAlign: "center" })}>
        <h1 className={css({ fontSize: "2xl", fontWeight: "bold" })}>골든링크</h1>
        <p className={css({ color: "gray.500" })}>
          응급이송 골든타임 단축을 위한 실시간 병원 매칭 시스템
        </p>
      </div>
      <div className={css({ display: "flex", gap: "4" })}>
        <Link
          href="/ambulance"
          className={css({
            paddingX: "6",
            paddingY: "3",
            borderRadius: "md",
            backgroundColor: "brand",
            color: "white",
            fontWeight: "semibold",
            _hover: { backgroundColor: "brand.emphasis" },
          })}
        >
          구급차 대시보드
        </Link>
        <Link
          href="/hospital"
          className={css({
            paddingX: "6",
            paddingY: "3",
            borderRadius: "md",
            backgroundColor: "white",
            borderWidth: "1px",
            borderColor: "gray.300",
            color: "gray.700",
            fontWeight: "semibold",
            _hover: { backgroundColor: "gray.100" },
          })}
        >
          병원 대시보드
        </Link>
      </div>
    </main>
  );
}
