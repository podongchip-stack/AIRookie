"use client";

import { FrameModalButton } from "@/components/ui/FrameModalButton";

// 시연용 신뢰도 검증 화면(/verify)을 모달로 연다(2026-10-02). hub 주소가 없으면(목데이터 모드) 숨긴다.
export function VerificationButton() {
  if (!process.env.NEXT_PUBLIC_HUB_HTTP_URL) return null;
  return <FrameModalButton label="신뢰도 검증" badge="시연용 예시 · 실제 E-Gen 기록으로 채점" url="/verify" />;
}
