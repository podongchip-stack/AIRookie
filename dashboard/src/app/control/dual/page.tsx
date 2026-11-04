"use client";

import { DemoConsole } from "@/components/control/DemoConsole";
import { DEMO_UNITS } from "@/lib/demo-unit";
import Link from "next/link";

// 동시 시연 화면(2026-11-03) — 두 구급대의 콘솔을 한 화면에 나란히 둔다. 각 칸은 한 구급대에 고정돼 따로 진행하고,
// 위 [동시 출동]은 출동 전(①) 상태인 칸을 각자 고른(기본) 상황으로 한꺼번에 출동시킨다.
export default function DualControlPage() {
  return (
    <div style={{ height: "100dvh", display: "flex", flexDirection: "column", background: "#f4f6fa" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12, padding: "8px 16px", background: "#ffffff", borderBottom: "1px solid #e3e7ee", flex: "none" }}>
        <strong style={{ fontSize: 15 }}>동시 시연 콘솔</strong>
        <span style={{ fontSize: 12, color: "#5a6676" }}>{DEMO_UNITS.map((unit) => `${unit.short} ${unit.phoneCode}`).join(" · ")}</span>
        <button type="button" onClick={() => window.dispatchEvent(new Event("demo-dispatch"))}
          style={{ minHeight: 36, padding: "0 16px", borderRadius: 8, border: "none", background: "#1f4e9c", color: "#ffffff", fontSize: 14, fontWeight: 700, cursor: "pointer" }}>
          동시 출동
        </button>
        <span style={{ flex: 1 }} />
        <Link href="/control" style={{ fontSize: 14, fontWeight: 700, color: "#1f4e9c", textDecoration: "none" }}>← 한 화면 콘솔</Link>
      </div>
      <div style={{ flex: 1, minHeight: 0, display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, padding: 8, boxSizing: "border-box" }}>
        {DEMO_UNITS.map((unit) => (
          <div key={unit.apid} style={{ minWidth: 0, minHeight: 0, borderRadius: 14, overflow: "hidden", border: "1px solid #e3e7ee" }}>
            <DemoConsole embedded fixedApid={unit.apid} />
          </div>
        ))}
      </div>
    </div>
  );
}
