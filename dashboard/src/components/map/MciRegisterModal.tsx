"use client";

import { useEffect, useState } from "react";
import { C, GLASS } from "@/lib/control-map";
import { searchPlaces } from "@/lib/geocode";
import { supportCandidates } from "@/lib/fire-hq";
import { MciSketch } from "@/components/map/MciSketch";
import type { GeocodeResult, MciAssessment } from "@/types/dashboard";

// 다수 사상자 신고(2026-11-04) — 개정법 이후 상황실이 직접 등록하고 에이전트가 단계별로 일하는 모습을 보인다.
// 위치·추정 사상자 수를 넣으면 hub가 ① 반경 병원 여력 집계 ② 중증부터 예상 분배(규칙, spider 줄 길이 + 여력·부하)
// ③ 가까운 대기 구급대 추천을 돌려준다(mci_assessment). 결과는 미리 보기이고 출동은 관제가 [출동 지시]로 정한다.
// 단계는 응답이 오면 차례로 펼쳐 보인다(화면 연출) — 계산은 hub에서 이미 끝났고 생성형 AI가 아니라 규칙이다.
// 위치는 주소·장소 검색(hub /geocode — 카카오 키는 hub에만)으로 어디든 고르고, 자주 쓰는 곳·선택한 사건 위치는 바로 고른다.

const PLACES: { label: string; lat: number; lng: number }[] = [
  { label: "서울시청", lat: 37.5665, lng: 126.978 },
  { label: "강남역", lat: 37.4979, lng: 127.0276 },
  { label: "여의도", lat: 37.5219, lng: 126.9245 },
  { label: "잠실", lat: 37.5133, lng: 127.1001 },
];
const SEVS = ["중증", "중등증", "경증"] as const;
const SEV_COLOR: Record<string, string> = { 중증: "#D9434B", 중등증: "#F26B1D", 경증: "#1E9E6A" };
const STAGE_COLOR: Record<string, string> = { 인식: "#5AA9E6", 판단: "#6B5BD2", 행동: "#F5B942", 학습: "#1E9E6A" };

export function MciRegisterModal({ assessment, onRegister, onDispatch, onClose, center }: {
  assessment: MciAssessment | null;
  onRegister: (body: { lat: number; lng: number; counts: Record<string, number>; label: string }) => void;
  onDispatch: (incidentId: string) => void;
  onClose: () => void;
  center: { lat: number; lng: number } | null;
}) {
  const [where, setWhere] = useState<{ label: string; lat: number; lng: number }>(PLACES[0]);
  const [query, setQuery] = useState("");
  const [found, setFound] = useState<GeocodeResult[]>([]);
  const [searchNote, setSearchNote] = useState("");
  const search = async () => {
    const q = query.trim();
    if (q.length < 2) { setSearchNote("두 글자 이상 입력하세요"); return; }
    setSearchNote("검색 중…");
    const { results, error } = await searchPlaces(q, "");
    setFound(results.slice(0, 6));
    setSearchNote(error ?? (results.length ? "" : "검색 결과가 없습니다"));
  };
  const [label, setLabel] = useState("");
  const [counts, setCounts] = useState<Record<string, number>>({ 중증: 2, 중등증: 3, 경증: 5 });
  const [sentAt, setSentAt] = useState<number | null>(null);
  const [shown, setShown] = useState(0);
  const [dispatched, setDispatched] = useState(false);
  const fresh = assessment && sentAt != null ? assessment : null;

  // 결과가 오면 단계를 하나씩 펼친다(연출) — 인식 → 판단 → 행동 → 결과 표
  useEffect(() => {
    if (!fresh) return;
    const timers = [1, 2, 3, 4].map((n) => setTimeout(() => setShown(n), n * 550));
    return () => timers.forEach(clearTimeout);
  }, [fresh]);

  const total = SEVS.reduce((n, s) => n + (counts[s] ?? 0), 0);

  return (
    <div role="dialog" aria-modal="true" aria-label="다수 사상자 신고" style={{ position: "absolute", inset: 0, zIndex: 320, background: "rgba(28,31,42,.32)", backdropFilter: "blur(6px)", display: "flex", alignItems: "center", justifyContent: "center" }}>
      <button type="button" aria-label="닫기" onClick={onClose} style={{ position: "absolute", inset: 0, border: 0, background: "transparent", cursor: "default" }} />
      <div style={{ position: "relative", width: 820, maxHeight: "calc(100% - 48px)", maxWidth: "calc(100% - 32px)", background: GLASS.solid, border: GLASS.border, borderRadius: GLASS.radius, boxShadow: "0 24px 60px rgba(91,75,138,.28)", fontFamily: GLASS.font, display: "flex", flexDirection: "column", overflow: "hidden", whiteSpace: "normal" }}>
        <div style={{ flex: "none", display: "flex", alignItems: "center", gap: 10, padding: "16px 22px", borderBottom: `1px solid ${C.line2}` }}>
          <div style={{ fontSize: 18, fontWeight: 900, color: C.navy }}>다수 사상자 신고</div>
          <span style={{ fontSize: 11.5, fontWeight: 700, color: C.blue, background: GLASS.tint, borderRadius: 999, padding: "2px 10px" }}>AI 에이전트 · 규칙 기반 분배</span>
          <div style={{ flex: 1 }} />
          <button type="button" onClick={onClose} style={ghostBtn}>닫기 ✕</button>
        </div>

        <div style={{ padding: "16px 22px", overflowY: "auto", display: "grid", gridTemplateColumns: "280px 1fr", gap: 18 }}>
          {/* 입력 */}
          <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            <label style={lab}>사고 위치</label>
            <form onSubmit={(e) => { e.preventDefault(); void search(); }} style={{ display: "flex", gap: 6 }}>
              <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="주소·장소 검색 (예: 판교역, 시흥 산업단지)" style={{ ...inputStyle, flex: 1, minWidth: 0 }} />
              <button type="submit" style={{ ...chip(false), flex: "none" }}>검색</button>
            </form>
            {searchNote && <div style={{ fontSize: 11.5, color: C.sub }}>{searchNote}</div>}
            {found.length > 0 && (
              <div style={{ display: "flex", flexDirection: "column", gap: 4, maxHeight: 150, overflowY: "auto" }}>
                {found.map((r) => (
                  <button key={`${r.lat},${r.lng}`} type="button" onClick={() => { setWhere({ label: r.name, lat: r.lat, lng: r.lng }); setFound([]); setSearchNote(""); }}
                    style={{ textAlign: "left", fontFamily: "inherit", fontSize: 12, padding: "5px 10px", borderRadius: GLASS.radiusSm, border: `1px solid ${C.line}`, background: "#fff", cursor: "pointer" }}>
                    <b style={{ color: C.navy }}>{r.name}</b> <span style={{ color: C.sub }}>{r.address}</span>
                  </button>
                ))}
              </div>
            )}
            <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
              {PLACES.map((p) => (
                <button key={p.label} type="button" onClick={() => setWhere(p)} style={chip(where.label === p.label)}>{p.label}</button>
              ))}
              {center && <button type="button" onClick={() => setWhere({ label: "선택한 사건 위치", ...center })} style={chip(where.label === "선택한 사건 위치")}>선택한 사건 위치</button>}
            </div>
            <div style={{ fontSize: 12, color: C.ink2 }}>선택: <b style={{ color: C.blue }}>{where.label}</b></div>
            <label style={lab}>사고 내용(선택)</label>
            <input value={label} onChange={(e) => setLabel(e.target.value)} placeholder="예: 공장 화재, 다중 추돌" style={inputStyle} />
            <label style={lab}>추정 사상자</label>
            {SEVS.map((s) => (
              <div key={s} style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <span style={{ width: 56, fontSize: 13, fontWeight: 700, color: SEV_COLOR[s] }}>{s}</span>
                <button type="button" style={stepBtn} onClick={() => setCounts((c) => ({ ...c, [s]: Math.max(0, (c[s] ?? 0) - 1) }))}>−</button>
                <span style={{ width: 28, textAlign: "center", fontSize: 15, fontWeight: 900, color: C.navy }}>{counts[s] ?? 0}</span>
                <button type="button" style={stepBtn} onClick={() => setCounts((c) => ({ ...c, [s]: Math.min(60, (c[s] ?? 0) + 1) }))}>+</button>
              </div>
            ))}
            <button type="button" disabled={total === 0}
              onClick={() => { setShown(0); setDispatched(false); setSentAt(Date.now()); onRegister({ lat: where.lat, lng: where.lng, counts, label: label || where.label }); }}
              style={{ ...primaryBtn, opacity: total ? 1 : 0.5 }}>
              신고하고 에이전트 분석 ({total}명)
            </button>
          </div>

          {/* 에이전트 분석 */}
          <div style={{ display: "flex", flexDirection: "column", gap: 10, minWidth: 0 }}>
            {!fresh && (
              <div style={{ padding: 20, borderRadius: 14, background: GLASS.tint, color: C.sub, fontSize: 13, lineHeight: 1.6 }}>
                {sentAt ? "에이전트가 분석 중입니다…" : "위치와 추정 사상자를 넣고 신고하면, 에이전트가 반경 병원의 여력을 모으고 중증 환자부터 예상 분배와 출동 구급대를 제안합니다."}
              </div>
            )}
            {fresh && (
              <>
                <ol style={{ listStyle: "none", margin: 0, padding: 0, display: "flex", flexDirection: "column", gap: 6 }}>
                  {fresh.steps.map((s, i) => (
                    <li key={i} style={{ display: "grid", gridTemplateColumns: "44px 1fr", gap: 8, alignItems: "start", fontSize: 13, color: C.ink2, opacity: shown > i ? 1 : 0.25, transition: "opacity .4s" }}>
                      <span style={{ fontSize: 11, fontWeight: 700, textAlign: "center", color: "#fff", background: STAGE_COLOR[s.stage] ?? C.blue, borderRadius: 999, lineHeight: "18px" }}>{s.stage}</span>
                      <span>{shown > i ? s.text : "…"} <span style={{ fontSize: 10.5, fontWeight: 700, color: C.muted }}>{s.source === "ai" ? "AI" : "규칙"}</span></span>
                    </li>
                  ))}
                </ol>
                {shown >= 4 && (
                  <>
                    <MciSketch a={fresh} support={fresh.shortage > 0 ? supportCandidates(fresh.gps) : []} />
                    {fresh.shortage > 0 && (
                      <div style={{ padding: "8px 12px", borderRadius: GLASS.radiusSm, background: "#FDECEA", color: "#B3261E", fontSize: 12.5, lineHeight: 1.6 }}>
                        <b>구급차 {fresh.shortage}대 부족 — 인근 지역 지원 요청 후보</b>
                        {supportCandidates(fresh.gps).map((h, i) => (
                          <div key={h.name}>{i + 1}. {h.name}({h.city}) · 직선 {Math.round(h.km)}km</div>
                        ))}
                        <div style={{ fontSize: 11, color: C.sub }}>가까운 시·도 소방본부 순(본부 위치는 대략) · 실제 요청은 관제가 판단합니다</div>
                      </div>
                    )}
                    <div style={{ fontSize: 12.5, color: C.sub }}>
                      반경 {fresh.radiusKm}km 병원 {fresh.hospitalsInRadius}곳 ·{" "}
                      {Object.entries(fresh.byLevel).map(([lv, v]) => `${lv.replace("응급의료", "")} ${v.count}곳(응급실 ${v.beds}석${v.unknown ? `·미상 ${v.unknown}` : ""})`).join(" · ")}
                    </div>
                    <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
                      {fresh.plan.map((p) => (
                        <div key={p.hospitalId} style={{ display: "flex", alignItems: "center", gap: 8, padding: "6px 10px", borderRadius: GLASS.radiusSm, background: "#fff", border: `1px solid ${C.line2}`, fontSize: 12.5 }}>
                          <span style={{ flex: 1, minWidth: 0, fontWeight: 700, color: C.navy }}>{p.name}</span>
                          <span style={{ color: C.sub }}>{p.km}km · 응급실 {p.beds ?? "미상"}석</span>
                          {SEVS.filter((s) => p.bySeverity[s]).map((s) => (
                            <span key={s} style={{ fontSize: 11, fontWeight: 700, color: "#fff", background: SEV_COLOR[s], borderRadius: 999, padding: "0 7px" }}>{s} {p.bySeverity[s]}</span>
                          ))}
                        </div>
                      ))}
                      {fresh.unplaced > 0 && <div style={{ fontSize: 12.5, color: "#D9434B" }}>반경 안 여력이 부족해 {fresh.unplaced}명은 범위를 넓혀야 합니다.</div>}
                    </div>
                    <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
                      <span style={{ fontSize: 12.5, color: C.ink2 }}>
                        필요 {fresh.neededAmbulances}대 · 가용 {fresh.ambulances.length}대
                        {fresh.shortage > 0 && <b style={{ color: "#D9434B" }}> · {fresh.shortage}대 부족 — 인근 지역 지원 요청 필요</b>}
                        <br />추천 · {fresh.ambulances.slice(0, 4).map((a) => `${a.name ?? a.apid}(${a.km}km)`).join(", ")}{fresh.ambulances.length > 4 ? " …" : ""}
                      </span>
                      <button type="button" disabled={dispatched || fresh.ambulances.length === 0}
                        onClick={() => { setDispatched(true); onDispatch(fresh.incidentId); }}
                        style={{ ...primaryBtn, marginLeft: "auto", opacity: dispatched ? 0.6 : 1 }}>
                        {dispatched ? "출동 지시함" : `출동 지시 (${fresh.ambulances.length}대)`}
                      </button>
                    </div>
                    <div style={{ fontSize: 11, color: C.muted }}>예상 분배는 미리 보기입니다 — 실제 배정은 각 구급대 통화 뒤 병원 수용 회신과 상황실 확정으로 정해집니다. 가중치는 전문의 검토 전 초안입니다.</div>
                  </>
                )}
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

const lab: React.CSSProperties = { fontSize: 12, fontWeight: 700, color: C.sub };
const chip = (on: boolean): React.CSSProperties => ({
  fontFamily: "inherit", fontSize: 12, fontWeight: 600, borderRadius: 999, padding: "4px 12px", cursor: "pointer",
  border: `1px solid ${on ? C.blue : C.line}`, background: on ? GLASS.tint : "#fff", color: on ? C.blue : C.ink2,
});
const inputStyle: React.CSSProperties = { fontFamily: "inherit", fontSize: 13, padding: "7px 12px", borderRadius: GLASS.radiusSm, border: `1px solid ${C.line}`, background: "#fff" };
const stepBtn: React.CSSProperties = { width: 28, height: 28, borderRadius: 999, border: `1px solid ${C.line}`, background: "#fff", fontSize: 15, cursor: "pointer", color: C.navy };
const primaryBtn: React.CSSProperties = { fontFamily: "inherit", fontSize: 13.5, fontWeight: 900, color: "#fff", background: C.blue, border: 0, borderRadius: 999, padding: "9px 18px", cursor: "pointer" };
const ghostBtn: React.CSSProperties = { fontFamily: "inherit", fontSize: 13, color: C.ink3, background: "#fff", border: `1px solid ${C.line}`, borderRadius: 999, padding: "5px 12px", cursor: "pointer" };
