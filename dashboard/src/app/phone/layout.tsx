import type { Metadata, Viewport } from "next";

// 휴대폰 전화 앱 전용(2026-10-03): 노치·홈 바 영역까지 화면을 쓰고(safe-area로 비움), 확대 없이 기기 폭에 맞춘다.
export const metadata: Metadata = {
  title: "골든링크 전화",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
  themeColor: "#FFFFFF",
  // 앱처럼 화면 한 장에 고정 — 확대하지 않는다(통화 화면은 버튼·자막이 이미 기기 크기에 맞춰 커진다)
  maximumScale: 1,
  userScalable: false,
};

// html·body도 고정해 바깥 페이지가 끌려 움직이거나 당겨서 새로고침되지 않게 한다(이 경로에만 적용).
const LOCK_PAGE_CSS = `
html, body { height: 100%; overflow: hidden; overscroll-behavior: none; }
body { position: fixed; inset: 0; }
`;

export default function PhoneLayout({ children }: { children: React.ReactNode }) {
  return (
    <>
      <style>{LOCK_PAGE_CSS}</style>
      {children}
    </>
  );
}
