"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { css, cx } from "styled-system/css";
import { Tag } from "@/components/hospital/Tag";
import { dangerButtonStyle, primaryButtonStyle } from "@/components/ui/button-styles";
import { thinScrollbarStyle } from "@/components/ui/scrollbar-style";
import type { CallSignalType } from "@/types/dashboard";

const BAR_COUNT = 24;
const SILENT_LEVELS = Array<number>(BAR_COUNT).fill(0);

// 브라우저 표준 lib.dom.d.ts엔 Web Speech API 타입이 없어서(비표준 API) 실제로 쓰는
// 부분만 최소한으로 직접 선언한다.
interface SpeechRecognitionResultLike {
  isFinal: boolean;
  0: { transcript: string };
}
interface SpeechRecognitionEventLike extends Event {
  resultIndex: number;
  results: ArrayLike<SpeechRecognitionResultLike>;
}
interface SpeechRecognitionLike extends EventTarget {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  onresult: ((event: SpeechRecognitionEventLike) => void) | null;
  onerror: (() => void) | null;
  onend: (() => void) | null;
  start: () => void;
  stop: () => void;
}

function getSpeechRecognitionCtor(): (new () => SpeechRecognitionLike) | null {
  if (typeof window === "undefined") return null;
  const w = window as unknown as {
    SpeechRecognition?: new () => SpeechRecognitionLike;
    webkitSpeechRecognition?: new () => SpeechRecognitionLike;
  };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

// 통화 시연: 버튼을 누르면 마이크를 캡처해 화면에 실시간으로 보여주고, 캡처된
// 오디오 조각을 hub로 실시간 스트리밍한다. 통화 종료를 누르면 캡처를 멈추고
// hub에 종료 신호를 보내 통화 요약 처리를 트리거한다.
// 실시간 텍스트 표시는 브라우저 내장 Web Speech API(SpeechRecognition)로 시연용
// 즉석 인식만 하는 것이다 — 실제 STT(Whisper/Qwen3-ASR)는 feature/voice 담당
// 영역이라 이 텍스트는 hub로 보내는 값과 무관하다(hub에는 오디오 원본만 전달).
// Chrome 계열 브라우저에서만 동작한다.
// hub README에는 아직 이 오디오 스트리밍 스키마가 없다 — "hub가 직접 오디오를
// 받는다"는 이 흐름은 voice/hub 팀과 별도로 확정이 필요한 가안이다.
export function CallDemoPanel({
  onCallSignal,
  onAudioChunk,
}: {
  onCallSignal: (signal: CallSignalType) => void;
  onAudioChunk: (chunk: Blob) => void;
}) {
  const [active, setActive] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [levels, setLevels] = useState<number[]>(SILENT_LEVELS);
  const [transcript, setTranscript] = useState("");
  const [interimText, setInterimText] = useState("");
  // window가 없는 서버 렌더와 있는 클라이언트 렌더가 다른 값을 내면 하이드레이션이
  // 어긋나므로, 마운트 시점에 미리 계산해두지 않고 실제로 통화를 시작할 때(클릭
  // 핸들러 안, 클라이언트에서만 실행됨)만 판단해 반영한다.
  const [recognitionUnavailable, setRecognitionUnavailable] = useState(false);

  const streamRef = useRef<MediaStream | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const rafRef = useRef<number | null>(null);
  const recognitionRef = useRef<SpeechRecognitionLike | null>(null);
  const recognitionActiveRef = useRef(false);
  const transcriptBoxRef = useRef<HTMLDivElement | null>(null);
  const onAudioChunkRef = useRef(onAudioChunk);
  useEffect(() => {
    onAudioChunkRef.current = onAudioChunk;
  }, [onAudioChunk]);

  // 새 텍스트가 들어올 때마다 스크롤을 맨 아래로 붙여 최신 발화가 항상 보이게 한다.
  useEffect(() => {
    const box = transcriptBoxRef.current;
    if (box) box.scrollTop = box.scrollHeight;
  }, [transcript, interimText]);

  const stopAll = useCallback(() => {
    if (rafRef.current != null) {
      cancelAnimationFrame(rafRef.current);
      rafRef.current = null;
    }
    if (recorderRef.current && recorderRef.current.state !== "inactive") {
      recorderRef.current.stop();
    }
    recorderRef.current = null;
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    audioContextRef.current?.close().catch(() => {});
    audioContextRef.current = null;
    analyserRef.current = null;
    recognitionActiveRef.current = false;
    recognitionRef.current?.stop();
    recognitionRef.current = null;
    setLevels(SILENT_LEVELS);
    setInterimText("");
  }, []);

  // 언마운트 시 마이크·오디오 컨텍스트를 반드시 정리한다 (탭을 벗어나도 마이크가 켜진 채로 남지 않도록).
  useEffect(() => stopAll, [stopAll]);

  // requestAnimationFrame으로 재귀 호출되는 루프라 useCallback 대신 일반 함수 선언을 쓴다
  // (호이스팅되는 함수 선언이라야 자기 자신을 참조하는 재귀 콜백이 안전하다).
  function drawLevels() {
    const analyser = analyserRef.current;
    if (!analyser) return;
    const data = new Uint8Array(analyser.frequencyBinCount);
    analyser.getByteFrequencyData(data);
    const step = Math.max(1, Math.floor(data.length / BAR_COUNT));
    setLevels(Array.from({ length: BAR_COUNT }, (_, i) => data[i * step] ?? 0));
    rafRef.current = requestAnimationFrame(drawLevels);
  }

  function startSpeechRecognition() {
    const Ctor = getSpeechRecognitionCtor();
    if (!Ctor) {
      setRecognitionUnavailable(true);
      return;
    }

    const recognition = new Ctor();
    recognition.lang = "ko-KR";
    recognition.continuous = true;
    recognition.interimResults = true;
    recognition.onresult = (event) => {
      let interim = "";
      let finalChunk = "";
      for (let i = event.resultIndex; i < event.results.length; i++) {
        const result = event.results[i];
        const text = result[0].transcript;
        if (result.isFinal) finalChunk += text;
        else interim += text;
      }
      if (finalChunk) setTranscript((prev) => (prev ? `${prev} ${finalChunk}` : finalChunk).trim());
      setInterimText(interim);
    };
    recognition.onerror = () => {
      // 인식 오류(무음 타임아웃 등)는 무시한다 — 오디오 캡처/전송은 별개로 계속 동작한다.
    };
    recognition.onend = () => {
      // continuous=true여도 브라우저가 세션을 끊는 경우가 있어, 통화가 아직 활성 상태면 재시작한다.
      if (recognitionActiveRef.current) {
        try {
          recognition.start();
        } catch {
          // 이미 시작된 상태에서 start()를 다시 부르면 예외가 나는 브라우저가 있다 — 무시.
        }
      }
    };

    try {
      recognition.start();
      recognitionActiveRef.current = true;
      recognitionRef.current = recognition;
    } catch {
      // 음성 인식 시작 실패는 텍스트 표시만 못 하는 것이므로 통화 캡처 자체는 계속 진행한다.
    }
  }

  async function handleStart() {
    setError(null);
    if (typeof navigator === "undefined" || !navigator.mediaDevices?.getUserMedia) {
      setError("이 브라우저에서는 마이크 캡처를 지원하지 않습니다.");
      return;
    }

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;

      const audioContext = new AudioContext();
      const source = audioContext.createMediaStreamSource(stream);
      const analyser = audioContext.createAnalyser();
      analyser.fftSize = 128;
      source.connect(analyser);
      audioContextRef.current = audioContext;
      analyserRef.current = analyser;

      const recorder = new MediaRecorder(stream);
      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) onAudioChunkRef.current(event.data);
      };
      recorder.start(250);
      recorderRef.current = recorder;

      setTranscript("");
      setInterimText("");
      setRecognitionUnavailable(false);
      startSpeechRecognition();

      setActive(true);
      onCallSignal("call_started");
      rafRef.current = requestAnimationFrame(drawLevels);
    } catch {
      setError("마이크 권한이 거부되었거나 사용할 수 없습니다.");
    }
  }

  function handleEnd() {
    stopAll();
    setActive(false);
    onCallSignal("call_ended");
  }

  return (
    // 공용 <Panel>은 height:"100%"가 고정돼 있어 한 셀에 패널 하나만 있는 걸 전제로
    // 한다. 이 컴포넌트는 CallSummaryEditablePanel과 세로로 비율 분할된 wrapper
    // (flex-basis:0)에 담기므로, 그 wrapper가 준 높이를 그대로 채우도록 height:100%를
    // 직접 쓰는 자체 카드 마크업을 쓴다.
    <section
      className={css({
        display: "flex",
        flexDirection: "column",
        height: "100%",
        borderWidth: "1px",
        borderColor: "line",
        borderRadius: "panel",
        backgroundColor: "surface",
        padding: "4",
        minWidth: "0",
      })}
    >
      <header
        className={css({
          display: "flex",
          alignItems: "flex-start",
          justifyContent: "space-between",
          gap: "2.5",
          paddingBottom: "3",
          marginBottom: "3",
          borderBottomWidth: "1px",
          borderColor: "line",
        })}
      >
        <h2 className={css({ fontSize: "sm", fontWeight: "semibold", letterSpacing: "-0.01em", color: "ink" })}>
          통화 시연
          <span
            className={css({ display: "block", fontSize: "xs", fontWeight: "normal", color: "ink", marginTop: "0.5" })}
          >
            마이크로 실시간 캡처 → hub로 스트리밍
          </span>
        </h2>
        <Tag source="rule">마이크 · 실시간 스트리밍</Tag>
      </header>

      <div className={css({ display: "flex", flexDirection: "column", gap: "3", flex: "1", minHeight: "0" })}>
        <div
          className={css({
            display: "flex",
            alignItems: "flex-end",
            gap: "1",
            padding: "2",
            backgroundColor: "surfaceSub",
            borderWidth: "1px",
            borderColor: "line",
            borderRadius: "field",
            flexShrink: "0",
          })}
          style={{ height: "56px" }}
        >
          {levels.map((level, i) => (
            <span
              key={i}
              className={css({ flex: "1", borderRadius: "sm", backgroundColor: active ? "navy" : "line" })}
              style={{ height: `${Math.max(6, (level / 255) * 100)}%` }}
            />
          ))}
        </div>

        <div
          ref={transcriptBoxRef}
          className={cx(
            css({
              flex: "1",
              minHeight: "0",
              overflowY: "auto",
              padding: "3",
              backgroundColor: "surfaceSub",
              borderWidth: "1px",
              borderColor: "line",
              borderRadius: "field",
              fontSize: "sm",
              color: "ink",
              lineHeight: "1.6",
            }),
            thinScrollbarStyle,
          )}
        >
          {recognitionUnavailable ? (
            <p className={css({ color: "ink3" })}>
              이 브라우저는 실시간 텍스트 변환을 지원하지 않습니다 (Chrome 계열 권장). 오디오 캡처·전송은 정상 동작합니다.
            </p>
          ) : transcript || interimText ? (
            <p>
              {transcript}
              {interimText && (
                <span className={css({ color: "ink3" })}> {interimText}</span>
              )}
            </p>
          ) : (
            <p className={css({ color: "ink3" })}>
              {active ? "말씀하시면 여기에 실시간으로 표시됩니다..." : "통화를 시작하면 실시간 텍스트가 여기 표시됩니다."}
            </p>
          )}
        </div>

        {error && <p className={css({ fontSize: "xs", color: "coral", flexShrink: "0" })}>{error}</p>}

        <div
          className={css({
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            gap: "2",
            flexShrink: "0",
          })}
        >
          <span className={css({ fontSize: "xs", color: "ink2" })}>
            {active ? "통화 중 · 실시간 전송" : "통화 대기 중"}
          </span>
          {active ? (
            <button type="button" className={dangerButtonStyle} onClick={handleEnd}>
              통화 종료
            </button>
          ) : (
            <button type="button" className={primaryButtonStyle} onClick={handleStart}>
              통화 시작
            </button>
          )}
        </div>

        <p className={css({ fontSize: "2xs", color: "ink3", flexShrink: "0" })}>
          종료 시 hub로 통화 종료 신호를 보내 통화 요약 처리를 요청합니다.
        </p>
      </div>
    </section>
  );
}
