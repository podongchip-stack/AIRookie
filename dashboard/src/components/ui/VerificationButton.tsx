"use client";

import { FrameModalButton } from "@/components/ui/FrameModalButton";

// 시연용 신뢰도 검증 화면(/verify)을 모달로 연다(2026-10-02). hub 주소가 없으면(목데이터 모드) 숨긴다.
// 병원 대시보드는 hpid를 넘겨 맨 위에 "우리 병원" 기록을 띄운다.
export function VerificationButton({ hpid }: { hpid?: string }) {
  if (!process.env.NEXT_PUBLIC_HUB_HTTP_URL) return null;
  const url = hpid ? `/verify?hpid=${encodeURIComponent(hpid)}` : "/verify";
  return <FrameModalButton label="신뢰도 검증" badge="시연용 예시 · 실제 E-Gen 기록으로 채점" url={url} />;
}
