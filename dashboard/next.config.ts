import type { NextConfig } from "next";

const localDev = process.env.NODE_ENV === "development";

const nextConfig: NextConfig = {
  // 카카오맵 도메인 화이트리스트가 127.0.0.1 기준으로 등록돼 있어서 개발 중엔
  // localhost 대신 127.0.0.1로 접속한다. Next.js 16은 기본적으로 localhost가
  // 아닌 호스트에서의 dev 리소스(HMR 웹소켓 등) 요청을 막으므로 명시적으로 허용해야
  // 한다(2026-08-11, 카카오맵 도메인 검증기가 "localhost"를 무효 URL로 거부해서
  // 127.0.0.1을 쓰게 된 배경 — ISSUE_카카오맵연동.md 참고).
  allowedDevOrigins: ["127.0.0.1"],
  // 관제 iframe을 웹과 같은 출처로 제공해 선택·카메라 연동을 유지한다.
  skipTrailingSlashRedirect: localDev,
  async rewrites() {
    if (!localDev) return [];
    return [
      { source: "/spider", destination: "http://127.0.0.1:2700/spider/" },
      { source: "/spider/:path*", destination: "http://127.0.0.1:2700/spider/:path*" },
    ];
  },
};

export default nextConfig;
