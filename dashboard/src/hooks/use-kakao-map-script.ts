"use client";

import { useEffect, useState } from "react";

// 구급차/병원 대시보드 지도 패널 둘 다 이 훅을 쓴다. 스크립트 태그를 두 번
// 삽입하면 중복 로드가 되므로, 모듈 스코프에 프라미스를 캐시해뒀다가 이미
// 로드 중/완료면 그걸 그대로 재사용한다.
let loaderPromise: Promise<void> | null = null;

function loadKakaoMapScript(appKey: string): Promise<void> {
  if (window.kakao?.maps) return Promise.resolve();
  if (loaderPromise) return loaderPromise;

  loaderPromise = new Promise((resolve, reject) => {
    const script = document.createElement("script");
    // autoload=false + kakao.maps.load()로 명시적으로 초기화 시점을 잡는다 —
    // 안 그러면 스크립트 로드 즉시 내부적으로 지도 리소스를 불러오기 시작해서
    // 우리 쪽 준비 상태(ready)와 타이밍이 어긋난다.
    script.src = `https://dapi.kakao.com/v2/maps/sdk.js?appkey=${appKey}&autoload=false`;
    script.async = true;
    script.onload = () => window.kakao.maps.load(() => resolve());
    script.onerror = () => reject(new Error("카카오맵 SDK 로드에 실패했습니다"));
    document.head.appendChild(script);
  });

  return loaderPromise;
}

// NEXT_PUBLIC_KAKAO_MAP_APP_KEY는 dashboard 앱 루트(dashboard/.env.local)에
// 있어야 Next.js가 읽는다 — 저장소 루트의 .env는 이 프로젝트가 안 읽는다.
export function useKakaoMapScript() {
  const [ready, setReady] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const appKey = process.env.NEXT_PUBLIC_KAKAO_MAP_APP_KEY;
    if (!appKey) {
      // 이펙트 본문에서 setState를 동기 호출하면 안 되므로(react-hooks/set-state-in-effect,
      // use-dashboard-socket.ts의 mock 타이머와 같은 이유) 다음 틱으로 미룬다.
      const timer = setTimeout(
        () => setError("NEXT_PUBLIC_KAKAO_MAP_APP_KEY가 설정되지 않았습니다 (dashboard/.env.local 확인)"),
        0,
      );
      return () => clearTimeout(timer);
    }

    let cancelled = false;
    loadKakaoMapScript(appKey)
      .then(() => {
        if (!cancelled) setReady(true);
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "카카오맵 SDK 로드 실패");
      });

    return () => {
      cancelled = true;
    };
  }, []);

  return { ready, error };
}
