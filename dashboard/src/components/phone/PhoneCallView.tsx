"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import { css, cx } from "styled-system/css";
import { PHASE_LABEL } from "@/components/ambulance/DispatchControlPanel";
import { CONNECTION_LABEL, type ConnectionMode } from "@/hooks/use-dashboard-socket";
import { distanceLabel } from "@/lib/distance";
import { startPcmCapture, type PcmCapture } from "@/lib/pcm-capture";
import type {
  AmbulanceSimState,
  CallSignalType,
  CallStatus,
  CallTranscriptLine,
  SceneCandidate,
  SceneCandidates,
} from "@/types/dashboard";

// 휴대폰 통화 화면(2026-10-03). 전용 주소 /phone?id=<apid>(첫 페이지 P-<apid> 코드)로 연다(app/phone/page.tsx).
// 휴대폰은 전화만 한다 — 출동·현장 종료·이송 승인은 태블릿·PC 화면에서 한다.
//
// 통화는 연출이다: 병원과 실제로 음성이 연결되지는 않는다. 구급대원이 고른 병원 대시보드에 "📞 통화 중"이 뜨고,
// 휴대폰 마이크 음성만 hub를 거쳐 중앙 voice로 가서 STT·구조화된 뒤 존 안의 후보 병원 전체에 동시에 전달된다.
// 사건 하나에 통화는 한 번이다(첫 병원 통화 내용이 곧 모든 병원에 보낼 환자 정보).
//
// 화면은 앱처럼 기기 화면 하나를 꽉 채운다(2026-10-03): 높이는 100dvh(주소창이 접혔다 펴져도 맞춤), 노치·홈 바는
// safe-area만큼 비우고, 목록·자막만 안에서 스크롤한다. 큰 화면에선 가운데 520px 폭으로 모으고, 가로로 눕힌 낮은
// 화면(높이 520px 이하)에선 통화 화면을 좌우 두 칸으로 나눈다.

const CONNECTING_MS = 1500;

// 클릭 처리 안에서만 부른다 — 렌더 중 Date.now()로 오인하는 린트(react-hooks/purity)를 피하려고 밖으로 뺐다
const clock = () => Date.now();

type LocalCall = {
  caseId: string;
  hospitalId: string;
  hospitalName: string;
  phase: "connecting" | "in_call" | "ended";
  startedAt: number;
  endedAt: number | null;
};

function mmss(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000));
  return `${String(Math.floor(total / 60)).padStart(2, "0")}:${String(total % 60).padStart(2, "0")}`;
}

// ── 아이콘(이모지는 기기마다 모양이 달라 SVG로) ──
const PHONE_PATH =
  "M6.62 10.79a15.05 15.05 0 0 0 6.59 6.59l2.2-2.2a1 1 0 0 1 1.01-.24 11.36 11.36 0 0 0 3.56.57 1 1 0 0 1 1 1V20a1 1 0 0 1-1 1A17 17 0 0 1 3 4a1 1 0 0 1 1-1h3.5a1 1 0 0 1 1 1c0 1.25.2 2.45.57 3.57a1 1 0 0 1-.25 1.02l-2.2 2.2z";

function PhoneIcon({ size = 22, hangUp = false }: { size?: number; hangUp?: boolean }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="currentColor"
      aria-hidden
      style={hangUp ? { transform: "rotate(135deg)" } : undefined}
    >
      <path d={PHONE_PATH} />
    </svg>
  );
}

function CheckIcon({ size = 36 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={3} strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <path d="M5 12.5l4.5 4.5L19 7.5" />
    </svg>
  );
}

// ── 공통 레이아웃 ──
const SAFE_X = { paddingLeft: "max(16px, env(safe-area-inset-left))", paddingRight: "max(16px, env(safe-area-inset-right))" };

// 화면 한 장에 고정(2026-10-03): 뷰포트에 position:fixed로 붙여 페이지 자체는 드래그해도 움직이지 않는다.
// 목록·자막(scrollStyle, data-scroll)만 안에서 스크롤되고, 끝에 닿아도 바깥으로 튕김이 번지지 않는다(contain).
// 길게 눌러 글자 선택·확대·더블탭 확대도 막아 앱처럼 쓴다.
const shellStyle = css({
  position: "fixed",
  inset: "0",
  display: "flex",
  flexDirection: "column",
  overflow: "hidden",
  backgroundColor: "bg",
  WebkitTapHighlightColor: "transparent",
  overscrollBehavior: "none",
  touchAction: "manipulation",
  userSelect: "none",
  WebkitUserSelect: "none",
  WebkitTouchCallout: "none",
  // 한국어는 어절 단위로 줄바꿈(글자 중간에서 끊지 않게), 아주 긴 단어만 어디서든 끊는다
  wordBreak: "keep-all",
  overflowWrap: "anywhere",
});

const columnStyle = css({
  width: "100%",
  maxWidth: "520px",
  marginX: "auto",
  flex: "1",
  minHeight: "0",
  display: "flex",
  flexDirection: "column",
});

const scrollStyle = css({
  flex: "1",
  minHeight: "0",
  overflowY: "auto",
  overscrollBehavior: "contain",
  touchAction: "pan-y",
  WebkitOverflowScrolling: "touch",
  scrollbarWidth: "none",
  "&::-webkit-scrollbar": { display: "none" },
});

const chipBase = {
  display: "inline-flex",
  alignItems: "center",
  gap: "1",
  paddingX: "2",
  paddingY: "0.5",
  borderRadius: "full",
  fontSize: "2xs",
  fontWeight: "semibold",
  whiteSpace: "nowrap",
} as const;
const chipNeutral = css({ ...chipBase, color: "ink2", backgroundColor: "surfaceSub", borderWidth: "1px", borderColor: "line" });
const chipOk = css({ ...chipBase, color: "mint", backgroundColor: "mintSoft" });
const chipFull = css({ ...chipBase, color: "coral", backgroundColor: "coralSoft" });
const chipAi = css({ ...chipBase, color: "navy", backgroundColor: "navySoft" });

function bedChip(h: SceneCandidate): { text: string; className: string } {
  if (h.bedCountUnknown) return { text: "병상 미상", className: chipNeutral };
  return h.availableBedCount > 0
    ? { text: `빈 병상 ${h.availableBedCount}`, className: chipOk }
    : { text: "만실", className: chipFull };
}

// 출동 → 현장 도착 → 통화 → 전달, 지금 어디쯤인지
const STEPS = ["출동", "현장 도착", "통화", "병원 전달"] as const;

// 네 칸을 같은 폭으로 나누고 점 아래에 이름을 둔다 — 글자 길이와 상관없이 화면 폭 안에 들어간다(좁으면 글자가 줄어든다)
function Stepper({ current }: { current: number }) {
  return (
    <ol
      className={css({ display: "grid", gridTemplateColumns: "repeat(4, minmax(0, 1fr))", paddingTop: "1", paddingBottom: "2.5" })}
      aria-label="진행 단계"
    >
      {STEPS.map((label, i) => {
        const done = i < current;
        const active = i === current;
        const color = active ? "#0E9F6E" : done ? "#16222E" : "#94A3B8";
        return (
          <li
            key={label}
            aria-current={active ? "step" : undefined}
            className={css({ position: "relative", display: "flex", flexDirection: "column", alignItems: "center", gap: "1", minWidth: "0" })}
          >
            {i < STEPS.length - 1 && (
              <span
                aria-hidden
                className={css({ position: "absolute", top: "4px", left: "calc(50% + 9px)", right: "calc(-50% + 9px)", height: "2px", borderRadius: "full" })}
                style={{ backgroundColor: done ? "#16222E" : "#E2E8EF" }}
              />
            )}
            <span
              className={css({ width: "10px", height: "10px", borderRadius: "full", flexShrink: "0" })}
              style={{ backgroundColor: active || done ? color : "#CBD5E1", boxShadow: active ? "0 0 0 3px #E6F6F0" : undefined }}
            />
            <span
              className={css({
                maxWidth: "100%",
                fontSize: "clamp(10px, 3vw, 12px)",
                fontWeight: "semibold",
                whiteSpace: "nowrap",
                overflow: "hidden",
                textOverflow: "ellipsis",
              })}
              style={{ color }}
            >
              {label}
            </span>
          </li>
        );
      })}
    </ol>
  );
}

// 가운데 아이콘 + 제목 + 설명(대기·종료·다른 기기 화면)
function StatusPanel({
  icon,
  tone,
  pulse = false,
  title,
  children,
}: {
  icon: ReactNode;
  tone: "mint" | "navy" | "ink";
  pulse?: boolean;
  title: string;
  children?: ReactNode;
}) {
  const color = tone === "mint" ? "#0E9F6E" : tone === "navy" ? "#1E5FA8" : "#55697C";
  const soft = tone === "mint" ? "#E6F6F0" : tone === "navy" ? "#EAF2FB" : "#F8FAFC";
  return (
    <div
      className={css({
        flex: "1",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        gap: "3",
        textAlign: "center",
        paddingY: "6",
      })}
    >
      <div className={css({ position: "relative", width: "clamp(72px, 22vw, 96px)", aspectRatio: "1" })}>
        {pulse && (
          <span
            className={css({ position: "absolute", inset: "0", borderRadius: "full", animation: "ring 1.8s ease-out infinite" })}
            style={{ backgroundColor: color }}
          />
        )}
        <span
          className={css({
            position: "absolute",
            inset: "0",
            borderRadius: "full",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            fontSize: "clamp(30px, 9vw, 40px)",
          })}
          style={{ backgroundColor: soft, color }}
        >
          {icon}
        </span>
      </div>
      <p className={css({ fontSize: "clamp(17px, 5vw, 20px)", fontWeight: "bold", color: "ink", lineHeight: "1.35" })}>{title}</p>
      {children && (
        <div className={css({ fontSize: "sm", color: "ink2", lineHeight: "1.6", maxWidth: "320px" })}>{children}</div>
      )}
    </div>
  );
}

export function PhoneCallView({
  apid,
  ambulanceName,
  connectionMode,
  simOn,
  sim,
  caseId,
  scene,
  callStatus,
  voiceLines,
  sentHospitalCount,
  onCallSignal,
  onAudioChunk,
}: {
  apid: string;
  ambulanceName: string | null;
  connectionMode: ConnectionMode;
  simOn: boolean;
  sim: AmbulanceSimState | null;
  // hub가 알려 준 이 구급차의 현재 사건(출동 시뮬레이션). 휴대폰은 사건을 만들지 않는다.
  caseId: string | null;
  scene: SceneCandidates | null;
  // 이 사건의 통화 상태(hub 기준) — 다른 기기(태블릿)에서 건 통화도 여기로 안다
  callStatus: CallStatus | null;
  voiceLines: CallTranscriptLine[];
  // 통화 요약으로 매칭돼 전달된 병원 수(매칭 결과가 오면)
  sentHospitalCount: number | null;
  onCallSignal: (signal: CallSignalType, caseId: string, hospitalId: string | null) => boolean;
  onAudioChunk: (chunk: ArrayBuffer) => void;
}) {
  const [call, setCall] = useState<LocalCall | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [level, setLevel] = useState(0);
  const [now, setNow] = useState(() => Date.now());

  const streamRef = useRef<MediaStream | null>(null);
  const captureRef = useRef<PcmCapture | null>(null);
  const rafRef = useRef<number | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const wakeLockRef = useRef<{ release: () => Promise<void> } | null>(null);
  const transcriptRef = useRef<HTMLDivElement | null>(null);
  const onAudioChunkRef = useRef(onAudioChunk);
  useEffect(() => {
    onAudioChunkRef.current = onAudioChunk;
  }, [onAudioChunk]);

  // 사건이 바뀌면(현장 종료·다음 출동) 지난 통화 화면은 저절로 접힌다 — 상태를 지우지 않고 사건으로 거른다
  const myCall = call && call.caseId === caseId ? call : null;

  useEffect(() => {
    if (myCall?.phase !== "in_call") return;
    const timer = setInterval(() => setNow(clock()), 500);
    return () => clearInterval(timer);
  }, [myCall?.phase]);

  useEffect(() => {
    const box = transcriptRef.current;
    if (box) box.scrollTop = box.scrollHeight;
  }, [voiceLines.length]);

  function releaseAll() {
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = null;
    if (rafRef.current != null) cancelAnimationFrame(rafRef.current);
    rafRef.current = null;
    captureRef.current?.stop();
    captureRef.current = null;
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    wakeLockRef.current?.release().catch(() => {});
    wakeLockRef.current = null;
    setLevel(0);
  }

  // 페이지 고정(2026-10-03): 스크롤 영역(data-scroll) 밖에서 끄는 손가락은 무시한다 — iOS Safari는 overflow·
  // overscroll 설정만으로는 고정된 화면도 끌어당기면 통째로 튕기고, 두 손가락이면 확대된다. 스크롤 영역 안이라도
  // 더 갈 곳이 없으면(내용이 짧음) 막는다. 확대 제스처(gesturestart, iOS 전용)도 막는다.
  useEffect(() => {
    let startY = 0;
    const onStart = (e: TouchEvent) => {
      startY = e.touches[0]?.clientY ?? 0;
    };
    const onMove = (e: TouchEvent) => {
      if (e.touches.length > 1) {
        e.preventDefault();
        return;
      }
      const box = (e.target as Element | null)?.closest?.("[data-scroll]") as HTMLElement | null;
      if (!box || box.scrollHeight <= box.clientHeight) {
        e.preventDefault();
        return;
      }
      const dy = (e.touches[0]?.clientY ?? 0) - startY;
      const atTop = box.scrollTop <= 0 && dy > 0;
      const atBottom = box.scrollTop + box.clientHeight >= box.scrollHeight - 1 && dy < 0;
      if (atTop || atBottom) e.preventDefault();
    };
    const onGesture = (e: Event) => e.preventDefault();
    document.addEventListener("touchstart", onStart, { passive: true });
    document.addEventListener("touchmove", onMove, { passive: false });
    document.addEventListener("gesturestart", onGesture);
    return () => {
      document.removeEventListener("touchstart", onStart);
      document.removeEventListener("touchmove", onMove);
      document.removeEventListener("gesturestart", onGesture);
    };
  }, []);

  // 화면을 떠나면 마이크를 반드시 끈다
  const releaseRef = useRef(releaseAll);
  useEffect(() => {
    releaseRef.current = releaseAll;
  });
  useEffect(() => () => releaseRef.current(), []);

  function drawLevel() {
    const analyser = captureRef.current?.analyser;
    if (!analyser) return;
    const data = new Uint8Array(analyser.fftSize);
    analyser.getByteTimeDomainData(data);
    let peak = 0;
    for (const v of data) peak = Math.max(peak, Math.abs(v - 128));
    setLevel(Math.min(1, peak / 64));
    rafRef.current = requestAnimationFrame(drawLevel);
  }

  async function handleCall(h: SceneCandidate) {
    if (!caseId || myCall) return;
    setError(null);
    if (!navigator.mediaDevices?.getUserMedia) {
      setError("이 브라우저는 마이크를 쓸 수 없습니다. https 주소(도메인)로 열었는지 확인하세요.");
      return;
    }
    let stream: MediaStream;
    try {
      // 마이크 권한은 버튼을 누른 이 순간에 받는다(휴대폰 브라우저는 사용자 동작 안에서만 묻는다)
      stream = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
      });
    } catch {
      setError("마이크 권한이 거부되었거나 사용할 수 없습니다.");
      return;
    }
    streamRef.current = stream;
    try {
      const nav = navigator as Navigator & { wakeLock?: { request: (t: "screen") => Promise<{ release: () => Promise<void> }> } };
      wakeLockRef.current = (await nav.wakeLock?.request("screen")) ?? null; // 통화 중 화면 꺼짐 방지
    } catch {
      // 지원하지 않는 브라우저 — 화면이 꺼지면 voice가 60초 뒤 통화를 저절로 끝낸다
    }
    const startedAt = clock();
    setNow(startedAt);
    setCall({ caseId, hospitalId: h.hospitalId, hospitalName: h.name, phase: "connecting", startedAt, endedAt: null });
    // "연결 중"을 잠깐 보여 준 뒤 통화 시작(연출) — 시작 신호를 먼저 보내야 hub가 이 소켓의 음성을 사건에 묶는다
    timerRef.current = setTimeout(async () => {
      timerRef.current = null;
      if (!onCallSignal("call_started", caseId, h.hospitalId)) {
        releaseAll();
        setCall(null);
        setError("hub와 연결이 끊겨 통화를 시작하지 못했습니다. 잠시 뒤 다시 눌러 주세요.");
        return;
      }
      try {
        captureRef.current = await startPcmCapture(stream, (frame) => onAudioChunkRef.current(frame));
      } catch {
        onCallSignal("call_ended", caseId, h.hospitalId);
        releaseAll();
        setCall(null);
        setError("마이크 음성을 처리하지 못했습니다. 브라우저를 바꿔 다시 시도해 주세요.");
        return;
      }
      const connectedAt = clock();
      setNow(connectedAt);
      setCall((c) => (c && c.caseId === caseId ? { ...c, phase: "in_call", startedAt: connectedAt } : c));
      rafRef.current = requestAnimationFrame(drawLevel);
    }, CONNECTING_MS);
  }

  function handleHangUp() {
    if (!myCall) return;
    const wasConnected = myCall.phase === "in_call";
    releaseAll();
    if (wasConnected) onCallSignal("call_ended", myCall.caseId, myCall.hospitalId);
    setCall(wasConnected ? { ...myCall, phase: "ended", endedAt: clock() } : null);
  }

  const connection = CONNECTION_LABEL[connectionMode];
  const dotColor = connectionMode === "live" ? "#0E9F6E" : connectionMode === "reconnecting" ? "#D93F35" : "#66778A";

  // ── 밝은 화면 공통 틀: 앱 바 + 단계 + 본문 ──
  function lightScreen(step: number, children: ReactNode) {
    return (
      <div className={shellStyle}>
        <header
          className={css({
            flexShrink: "0",
            backgroundColor: "surface",
            borderBottomWidth: "1px",
            borderColor: "line",
          })}
          style={{ paddingTop: "env(safe-area-inset-top)" }}
        >
          <div className={columnStyle} style={SAFE_X}>
            <div className={css({ display: "flex", alignItems: "center", gap: "3", height: "56px" })}>
              <span
                className={css({
                  width: "36px",
                  height: "36px",
                  borderRadius: "12px",
                  backgroundColor: "mint",
                  color: "white",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  flexShrink: "0",
                })}
              >
                <PhoneIcon size={18} />
              </span>
              <div className={css({ flex: "1", minWidth: "0" })}>
                <p className={css({ fontSize: "md", fontWeight: "bold", color: "ink", truncate: true, lineHeight: "1.2" })}>
                  {ambulanceName ?? `구급 ${apid}`}
                </p>
                <p className={css({ display: "flex", alignItems: "center", gap: "1", fontSize: "2xs", color: "ink3" })}>
                  <span className={css({ width: "1.5", height: "1.5", borderRadius: "full" })} style={{ backgroundColor: dotColor }} />
                  {connection.text.replace(/^[●◌○]\s*/, "")} · 전화 앱
                </p>
              </div>
            </div>
            <Stepper current={step} />
          </div>
        </header>
        <main className={columnStyle} style={{ ...SAFE_X, paddingBottom: "env(safe-area-inset-bottom)" }}>
          {children}
        </main>
      </div>
    );
  }

  // ── 통화 중·연결 중 (어두운 전체 화면) ──
  if (myCall && myCall.phase !== "ended") {
    const connecting = myCall.phase === "connecting";
    const glow = connecting ? 0 : Math.round(level * 28);
    return (
      <div
        className={shellStyle}
        style={{
          background: "linear-gradient(180deg, #10202F 0%, #16222E 55%, #0B141D 100%)",
          color: "white",
          paddingTop: "env(safe-area-inset-top)",
          paddingBottom: "max(20px, env(safe-area-inset-bottom))",
        }}
      >
        <div
          className={cx(
            columnStyle,
            css({
              gap: "4",
              paddingTop: "4",
              "@media (orientation: landscape) and (max-height: 520px)": {
                flexDirection: "row",
                maxWidth: "960px",
                alignItems: "stretch",
                paddingTop: "2",
              },
            }),
          )}
          style={SAFE_X}
        >
          {/* 상대 병원 · 시간 · 종료 버튼 */}
          <div
            className={css({
              display: "flex",
              flexDirection: "column",
              alignItems: "center",
              gap: "3",
              flexShrink: "0",
              "@media (orientation: landscape) and (max-height: 520px)": {
                width: "40%",
                justifyContent: "center",
                gap: "2",
              },
            })}
          >
            <span
              className={css({
                display: "inline-flex",
                alignItems: "center",
                gap: "1.5",
                fontSize: "xs",
                fontWeight: "semibold",
                paddingX: "3",
                paddingY: "1",
                borderRadius: "full",
                backgroundColor: "rgba(255,255,255,0.1)",
                position: "relative",
                zIndex: "1",
                marginBottom: "2",
              })}
            >
              <span
                className={css({ width: "2", height: "2", borderRadius: "full", animation: "beat 1.4s ease-in-out infinite" })}
                style={{ backgroundColor: connecting ? "#F5B94A" : "#E5484D" }}
              />
              {connecting ? "연결 중…" : "통화 중 · 음성 인식"}
            </span>
            <div className={css({ position: "relative", width: "clamp(84px, 26vw, 120px)", aspectRatio: "1", "@media (orientation: landscape) and (max-height: 520px)": { width: "72px" } })}>
              {connecting && (
                <>
                  <span className={css({ position: "absolute", inset: "0", borderRadius: "full", backgroundColor: "mint", animation: "ring 1.6s ease-out infinite" })} />
                  <span className={css({ position: "absolute", inset: "0", borderRadius: "full", backgroundColor: "mint", animation: "ring 1.6s ease-out 0.8s infinite" })} />
                </>
              )}
              <span
                className={css({
                  position: "absolute",
                  inset: "0",
                  borderRadius: "full",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  fontWeight: "bold",
                  fontSize: "clamp(32px, 10vw, 46px)",
                  backgroundColor: "mint",
                  transition: "box-shadow 0.12s",
                  "@media (orientation: landscape) and (max-height: 520px)": { fontSize: "28px" },
                })}
                style={{ boxShadow: `0 0 0 ${glow}px rgba(14,159,110,0.25)` }}
              >
                {myCall.hospitalName.slice(0, 1)}
              </span>
            </div>
            <p className={css({ fontSize: "clamp(22px, 7vw, 30px)", fontWeight: "bold", textAlign: "center", lineHeight: "1.25", wordBreak: "keep-all" })}>
              {myCall.hospitalName}
            </p>
            <p className={css({ fontSize: "clamp(16px, 4.6vw, 20px)", fontVariantNumeric: "tabular-nums", opacity: 0.75 })}>
              {connecting ? "응급실 연결 중" : mmss(now - myCall.startedAt)}
            </p>
            {/* 가로 화면에선 종료 버튼을 이 칸에 둔다 */}
            <div className={css({ display: "none", "@media (orientation: landscape) and (max-height: 520px)": { display: "flex" } })}>
              <HangUpButton onClick={handleHangUp} />
            </div>
          </div>

          {/* 실시간 자막(AI 음성 인식) */}
          <div className={css({ flex: "1", minHeight: "0", display: "flex", flexDirection: "column", gap: "2" })}>
            <p className={css({ fontSize: "2xs", fontWeight: "semibold", opacity: 0.6, letterSpacing: "0.02em" })}>
              실시간 자막 · AI 음성 인식
            </p>
            <div
              ref={transcriptRef}
              data-scroll
              className={cx(
                scrollStyle,
                css({
                  display: "flex",
                  flexDirection: "column",
                  gap: "2",
                  borderRadius: "18px",
                  backgroundColor: "rgba(255,255,255,0.06)",
                  padding: "3",
                }),
              )}
            >
              {voiceLines.length > 0 ? (
                voiceLines.map((line) => (
                  <p
                    key={`${line.start}-${line.text}`}
                    className={css({
                      alignSelf: "flex-start",
                      maxWidth: "92%",
                      paddingX: "3",
                      paddingY: "2",
                      borderRadius: "14px",
                      borderTopLeftRadius: "4px",
                      backgroundColor: "rgba(255,255,255,0.12)",
                      fontSize: "clamp(14px, 4vw, 16px)",
                      lineHeight: "1.5",
                    })}
                  >
                    <span className={css({ display: "block", fontSize: "2xs", opacity: 0.55, fontVariantNumeric: "tabular-nums" })}>
                      {mmss(line.start * 1000)}
                    </span>
                    {line.text}
                  </p>
                ))
              ) : (
                <p className={css({ margin: "auto", fontSize: "sm", opacity: 0.55, textAlign: "center", lineHeight: "1.6", whiteSpace: "pre-line" })}>
                  {connecting ? "곧 연결됩니다." : "말이 끊길 때마다\n인식된 문장이 여기에 뜹니다."}
                </p>
              )}
            </div>
            <p className={css({ fontSize: "2xs", opacity: 0.5, textAlign: "center" })}>
              통화 내용은 구조화(AI) 뒤 존 안의 후보 병원 모두에 동시에 전달됩니다
            </p>
          </div>

          {/* 세로 화면 종료 버튼 */}
          <div className={css({ display: "flex", justifyContent: "center", flexShrink: "0", "@media (orientation: landscape) and (max-height: 520px)": { display: "none" } })}>
            <HangUpButton onClick={handleHangUp} />
          </div>
        </div>
      </div>
    );
  }

  // ── 통화 종료(이 기기) 또는 이 사건 통화가 이미 끝남 ──
  const endedHere = myCall?.phase === "ended";
  if (endedHere || (callStatus && callStatus.state === "ended")) {
    const name = myCall?.hospitalName ?? callStatus?.hospitalName ?? "병원";
    const duration = myCall?.endedAt ? mmss(myCall.endedAt - myCall.startedAt) : null;
    const sent = sentHospitalCount != null;
    return lightScreen(sent ? 4 : 3, <>
        <StatusPanel icon={<CheckIcon />} tone="mint" pulse={!sent} title={sent ? `후보 병원 ${sentHospitalCount}곳에 전달됐습니다` : "환자 정보를 정리하는 중…"}>
          <div
            className={css({
              marginTop: "1",
              padding: "3",
              borderRadius: "panel",
              backgroundColor: "surface",
              borderWidth: "1px",
              borderColor: "line",
              textAlign: "left",
              display: "grid",
              gridTemplateColumns: "auto 1fr",
              columnGap: "4",
              rowGap: "1",
              fontSize: "sm",
            })}
          >
            <span className={css({ color: "ink3" })}>통화</span>
            <span className={css({ color: "ink", fontWeight: "semibold" })}>{name}</span>
            {duration && (
              <>
                <span className={css({ color: "ink3" })}>시간</span>
                <span className={css({ color: "ink", fontVariantNumeric: "tabular-nums" })}>{duration}</span>
              </>
            )}
            <span className={css({ color: "ink3" })}>다음</span>
            <span className={css({ color: "ink" })}>병원 응답 확인·이송 승인은 구급차 대시보드에서</span>
          </div>
        </StatusPanel>
      </>);
  }

  // ── 다른 기기에서 통화 중 ──
  if (callStatus && callStatus.state === "calling") {
    return lightScreen(2, <>
        <StatusPanel icon={<PhoneIcon size={34} />} tone="mint" pulse title={`${callStatus.device === "phone" ? "다른 휴대폰" : "구급차 대시보드"}에서 통화 중`}>
          {callStatus.hospitalName ?? "병원"}과 통화하고 있습니다. 통화는 사건마다 한 번만 합니다.
        </StatusPanel>
      </>);
  }

  // ── 대기(현장 도착 전·시뮬레이션 꺼짐) ──
  const onScene = simOn && sim?.phase === "on_scene" && caseId != null && sim.caseId === caseId;
  if (!onScene) {
    const phase = sim?.phase ?? "idle";
    return lightScreen(phase === "dispatching" ? 0 : -1, <>
        {simOn ? (
          <StatusPanel icon="🚑" tone="navy" pulse={phase === "dispatching"} title={PHASE_LABEL[phase]}>
            현장에 도착하면 전화할 병원 목록이 여기에 뜹니다. 출동은 구급차 대시보드에서 하세요.
          </StatusPanel>
        ) : (
          <StatusPanel icon="🚑" tone="ink" title="출동 시뮬레이션이 꺼져 있습니다">
            휴대폰 전화 앱은 출동 시뮬레이션에서만 씁니다. 구급차 대시보드의 통화 시연을 쓰세요.
          </StatusPanel>
        )}
      </>);
  }

  // ── 병원 고르기 ──
  const hospitals = scene
    ? [...scene.hospitals].sort((a, b) => Number(b.firstCallRecommended ?? false) - Number(a.firstCallRecommended ?? false))
    : [];
  return lightScreen(1, <>
      <div className={css({ paddingTop: "4", paddingBottom: "3", flexShrink: "0" })}>
        <p className={css({ fontSize: "clamp(20px, 6vw, 24px)", fontWeight: "bold", color: "ink", lineHeight: "1.3", wordBreak: "keep-all" })}>
          어느 병원에 먼저 전화할까요?
        </p>
        <p className={css({ fontSize: "xs", color: "ink2", marginTop: "1", lineHeight: "1.5" })}>
          도착 시간순(규칙 기반) · 첫 통화 내용이 존 안 모든 후보 병원에 함께 전달됩니다
        </p>
        {error && (
          <p className={css({ marginTop: "2", padding: "2.5", borderRadius: "field", fontSize: "sm", color: "coral", backgroundColor: "coralSoft" })}>
            {error}
          </p>
        )}
      </div>
      {!scene ? (
        <StatusPanel icon="⋯" tone="ink" pulse title="병원 목록을 불러오는 중…" />
      ) : hospitals.length === 0 ? (
        <StatusPanel icon="!" tone="ink" title="근처에 후보 병원이 없습니다" />
      ) : (
        <ul data-scroll className={cx(scrollStyle, css({ display: "flex", flexDirection: "column", gap: "2.5", paddingBottom: "4" }))}>
          {hospitals.map((h, i) => {
            const bed = bedChip(h);
            const recommended = h.firstCallRecommended ?? false;
            return (
              <li key={h.hospitalId}>
                <button
                  type="button"
                  onClick={() => handleCall(h)}
                  className={css({
                    width: "100%",
                    minHeight: "76px",
                    display: "flex",
                    alignItems: "center",
                    gap: "3",
                    paddingX: "3.5",
                    paddingY: "3",
                    textAlign: "left",
                    borderRadius: "18px",
                    backgroundColor: "surface",
                    borderWidth: "1px",
                    borderColor: "line",
                    boxShadow: "0 1px 2px rgba(22,34,46,0.05)",
                    cursor: "pointer",
                    transition: "transform 0.08s, box-shadow 0.08s",
                    _active: { transform: "scale(0.985)", boxShadow: "none" },
                  })}
                  style={recommended ? { borderColor: "#0E9F6E", borderWidth: 2, backgroundColor: "#F3FBF8" } : undefined}
                >
                  <span
                    className={css({
                      width: "32px",
                      height: "32px",
                      borderRadius: "full",
                      flexShrink: "0",
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      fontSize: "sm",
                      fontWeight: "bold",
                    })}
                    style={recommended ? { backgroundColor: "#0E9F6E", color: "white" } : { backgroundColor: "#F4F7FA", color: "#55697C" }}
                  >
                    {recommended ? "★" : i + 1}
                  </span>
                  <div className={css({ flex: "1", minWidth: "0", display: "flex", flexDirection: "column", gap: "1" })}>
                    {recommended && (
                      <span className={css({ fontSize: "2xs", fontWeight: "bold", color: "mint" })}>첫 통화 추천</span>
                    )}
                    <span className={css({ fontSize: "clamp(15px, 4.4vw, 17px)", fontWeight: "semibold", color: "ink", truncate: true })}>
                      {h.name}
                    </span>
                    <span className={css({ display: "flex", flexWrap: "wrap", gap: "1" })}>
                      <span className={chipNeutral}>
                        {distanceLabel(h)}
                        {h.etaMin != null ? ` · ${Math.round(h.etaMin)}분` : ""}
                      </span>
                      <span className={bed.className}>{bed.text}</span>
                      {h.bedReliability && (
                        <span className={chipAi}>AI 도착 시 유효 {Math.round(h.bedReliability.rArrive * 100)}%</span>
                      )}
                    </span>
                  </div>
                  <span
                    className={css({
                      width: "48px",
                      height: "48px",
                      borderRadius: "full",
                      flexShrink: "0",
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      color: "white",
                      backgroundColor: "mint",
                      boxShadow: "0 4px 10px rgba(14,159,110,0.35)",
                    })}
                  >
                    <PhoneIcon size={22} />
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </>);
}

function HangUpButton({ onClick }: { onClick: () => void }) {
  return (
    <span className={css({ display: "flex", flexDirection: "column", alignItems: "center", gap: "1.5" })}>
      <button
        type="button"
        aria-label="통화 종료"
        onClick={onClick}
        className={css({
          width: "clamp(64px, 19vw, 76px)",
          aspectRatio: "1",
          borderRadius: "full",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          color: "white",
          backgroundColor: "#E5484D",
          boxShadow: "0 8px 20px rgba(229,72,77,0.4)",
          cursor: "pointer",
          _active: { transform: "scale(0.94)" },
        })}
      >
        <PhoneIcon size={30} hangUp />
      </button>
      <span className={css({ fontSize: "xs", opacity: 0.7 })}>종료</span>
    </span>
  );
}
