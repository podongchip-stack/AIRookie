import { severityBadge } from "styled-system/recipes";
import type { Severity } from "@/types/dashboard";

const LABEL: Record<Severity, string> = {
  high: "중증",
  medium: "중등도",
  low: "경증",
};

export function SeverityBadge({ severity }: { severity: Severity }) {
  return (
    <span className={severityBadge({ severity })}>{LABEL[severity]}</span>
  );
}
