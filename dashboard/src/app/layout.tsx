import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";
// Pretendard(2026-11-04) — 발표 자료와 같은 글꼴. 관제 지도가 GLASS.font로 쓴다. 쓰는 글자만 내려받는 동적 서브셋
import "pretendard/dist/web/variable/pretendardvariable-dynamic-subset.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "골든링크 대시보드",
  description: "응급이송 골든타임 단축을 위한 실시간 병원 매칭 시스템",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className={`${geistSans.variable} ${geistMono.variable}`}>
      <body>{children}</body>
    </html>
  );
}
