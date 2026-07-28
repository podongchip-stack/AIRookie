import { sourceBadge } from "styled-system/recipes";

const LABEL: Record<"ai" | "rule", string> = {
  ai: "AI 처리",
  rule: "규칙 기반",
};

export function SourceBadge({ source }: { source: "ai" | "rule" }) {
  return <span className={sourceBadge({ source })}>{LABEL[source]}</span>;
}
