import type { ReactNode } from "react";
import { css } from "styled-system/css";

export function Panel({
  title,
  subtitle,
  badge,
  children,
}: {
  title: string;
  subtitle?: string;
  badge?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section
      className={css({
        display: "flex",
        flexDirection: "column",
        height: "100%",
        borderWidth: "1px",
        borderColor: "line",
        borderRadius: "panel",
        backgroundColor: "surface",
        padding: "4",
        minWidth: "0",
      })}
    >
      <header
        className={css({
          display: "flex",
          alignItems: "flex-start",
          justifyContent: "space-between",
          gap: "2.5",
          paddingBottom: "3",
          marginBottom: "3",
          borderBottomWidth: "1px",
          borderColor: "line",
        })}
      >
        <h2 className={css({ fontSize: "sm", fontWeight: "semibold", letterSpacing: "-0.01em", color: "ink" })}>
          {title}
          {subtitle && (
            <span
              className={css({
                display: "block",
                fontSize: "sm",
                fontWeight: "medium",
                color: "ink",
                marginTop: "0.5",
              })}
            >
              {subtitle}
            </span>
          )}
        </h2>
        {badge}
      </header>
      {children}
    </section>
  );
}
