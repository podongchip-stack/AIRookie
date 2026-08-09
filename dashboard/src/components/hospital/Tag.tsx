import type { ReactNode } from "react";
import { sourceBadge } from "styled-system/recipes";

// 소스 배지지만 라벨을 패널마다 다르게 쓰고 싶을 때(Whisper STT, GPS · 카카오내비 등)
// 사용하는 래퍼. 색상 로직은 sourceBadge recipe(ai/rule)를 그대로 재사용한다.
export function Tag({
  source,
  children,
}: {
  source: "ai" | "rule";
  children: ReactNode;
}) {
  return <span className={sourceBadge({ source })}>{children}</span>;
}
