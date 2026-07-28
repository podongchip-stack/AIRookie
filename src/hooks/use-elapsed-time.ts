"use client";

import { useEffect, useState } from "react";

function computeElapsed(since: string | null): number {
  if (!since) return 0;
  return Math.max(0, Math.floor((Date.now() - new Date(since).getTime()) / 1000));
}

export function useElapsedSeconds(since: string | null): number {
  const [prevSince, setPrevSince] = useState(since);
  const [elapsed, setElapsed] = useState(() => computeElapsed(since));

  // since가 바뀌면(새 통화 요약 수신 등) 렌더링 중 즉시 리셋한다.
  if (since !== prevSince) {
    setPrevSince(since);
    setElapsed(computeElapsed(since));
  }

  useEffect(() => {
    if (!since) return;
    const id = setInterval(() => setElapsed(computeElapsed(since)), 1000);
    return () => clearInterval(id);
  }, [since]);

  return elapsed;
}

export function formatElapsed(totalSeconds: number): string {
  const m = Math.floor(totalSeconds / 60).toString().padStart(2, "0");
  const s = (totalSeconds % 60).toString().padStart(2, "0");
  return `${m}:${s}`;
}
