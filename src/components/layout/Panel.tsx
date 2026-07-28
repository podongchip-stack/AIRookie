import type { ReactNode } from "react";
import { css } from "styled-system/css";

export function Panel({
  title,
  badge,
  children,
}: {
  title: string;
  badge?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section
      className={css({
        display: "flex",
        flexDirection: "column",
        gap: "3",
        borderWidth: "1px",
        borderColor: "gray.200",
        borderRadius: "lg",
        backgroundColor: "white",
        padding: "5",
      })}
    >
      <header
        className={css({
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
        })}
      >
        <h2 className={css({ fontSize: "md", fontWeight: "semibold" })}>
          {title}
        </h2>
        {badge}
      </header>
      {children}
    </section>
  );
}
