import type { ReactNode } from "react";
import { css } from "styled-system/css";
import type { DashboardRole } from "@/types/dashboard";

const TITLE: Record<DashboardRole, string> = {
  ambulance: "구급차 대시보드",
  hospital: "병원 대시보드",
};

export function DashboardShell({
  role,
  connectionMode,
  children,
}: {
  role: DashboardRole;
  connectionMode: "live" | "mock";
  children: ReactNode;
}) {
  return (
    <div className={css({ minHeight: "100vh", backgroundColor: "bg" })}>
      <header
        className={css({
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "4",
          borderBottomWidth: "1px",
          borderColor: "line",
          backgroundColor: "surface",
        })}
      >
        <h1 className={css({ fontSize: "lg", fontWeight: "bold" })}>
          골든링크 · {TITLE[role]}
        </h1>
        <span
          className={css({
            fontSize: "xs",
            fontWeight: "medium",
            color: connectionMode === "live" ? "hospitalStatus.confirmed" : "ink3",
          })}
        >
          {connectionMode === "live" ? "● 실시간 연동" : "○ 목데이터 모드"}
        </span>
      </header>
      <main
        className={css({
          display: "flex",
          flexDirection: "column",
          gap: "4",
          padding: "6",
          maxWidth: "960px",
          marginX: "auto",
        })}
      >
        {children}
      </main>
    </div>
  );
}
