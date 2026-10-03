// 브라우저 마이크 → 16kHz 모노 16비트 PCM 프레임(2026-10-03, 중앙 voice).
//
// voice의 STT(Qwen3-ASR)는 16kHz 모노 소리를 받는다. 예전엔 MediaRecorder가 만든 webm 조각을 보냈는데,
// 그 형식은 voice가 읽지 않아(화면 시각화용일 뿐이었다) STT 입력이 될 수 없었다. 여기서 마이크 소리를 그대로
// 받아 16kHz로 줄이고 16비트 정수로 바꿔 약 0.1초(1,600샘플 = 3,200바이트)씩 넘긴다. hub는 이 바이트를 사건별로
// 모아 중앙 voice에 그대로 넘긴다 — 형식은 voice/stream_recorder.py와 맞춘다(리틀엔디언).
//
// AudioWorklet을 우선 쓰고(별도 스레드라 화면이 바빠도 끊기지 않는다), 없으면 ScriptProcessor로 대신한다.
// 워클릿 코드는 파일을 따로 두지 않고 Blob URL로 만든다 — 정적 파일 경로·번들 설정에 기대지 않게.

export const PCM_SAMPLE_RATE = 16000;
const FRAME_SAMPLES = 1600; // 0.1초

const WORKLET_SOURCE = `
class PcmTap extends AudioWorkletProcessor {
  process(inputs) {
    const ch = inputs[0] && inputs[0][0];
    if (ch && ch.length) this.port.postMessage(ch.slice(0));
    return true;
  }
}
registerProcessor("pcm-tap", PcmTap);
`;

export interface PcmCapture {
  audioContext: AudioContext;
  // 화면 레벨 막대용
  analyser: AnalyserNode;
  stop: () => void;
}

// 입력 샘플레이트(보통 48kHz·44.1kHz)를 16kHz로 줄인다. 구간 평균이라 간단한 저역 통과도 겸한다.
class Downsampler {
  private readonly ratio: number;
  private carry: number[] = [];
  private pos = 0;
  private out = new Int16Array(FRAME_SAMPLES);
  private outLen = 0;

  constructor(
    inputRate: number,
    private readonly onFrame: (frame: ArrayBuffer) => void,
  ) {
    this.ratio = inputRate / PCM_SAMPLE_RATE;
  }

  push(input: Float32Array) {
    const buf = this.carry.length ? Float32Array.from([...this.carry, ...input]) : input;
    let pos = this.pos;
    while (pos + this.ratio <= buf.length) {
      const start = Math.floor(pos);
      const end = Math.max(start + 1, Math.floor(pos + this.ratio));
      let sum = 0;
      for (let i = start; i < end; i++) sum += buf[i];
      const v = Math.max(-1, Math.min(1, sum / (end - start)));
      this.out[this.outLen++] = v < 0 ? v * 0x8000 : v * 0x7fff;
      if (this.outLen === FRAME_SAMPLES) this.flush();
      pos += this.ratio;
    }
    const keepFrom = Math.floor(pos);
    this.carry = Array.from(buf.subarray(keepFrom));
    this.pos = pos - keepFrom;
  }

  flush() {
    if (this.outLen === 0) return;
    // Int16Array는 플랫폼 엔디언을 따르는데, 브라우저가 도는 기기는 사실상 전부 리틀엔디언이다.
    this.onFrame(this.out.slice(0, this.outLen).buffer);
    this.outLen = 0;
  }
}

export async function startPcmCapture(
  stream: MediaStream,
  onFrame: (frame: ArrayBuffer) => void,
): Promise<PcmCapture> {
  const audioContext = new AudioContext();
  // 휴대폰 브라우저는 사용자 동작 직후가 아니면 suspended로 시작하는 경우가 있다
  if (audioContext.state === "suspended") await audioContext.resume().catch(() => {});
  const source = audioContext.createMediaStreamSource(stream);
  const analyser = audioContext.createAnalyser();
  analyser.fftSize = 128;
  source.connect(analyser);

  const down = new Downsampler(audioContext.sampleRate, onFrame);
  // 소리를 스피커로 내보내지 않으면서 처리 노드를 계속 돌게 하는 0 볼륨 출력
  const mute = audioContext.createGain();
  mute.gain.value = 0;
  mute.connect(audioContext.destination);

  let disconnect: () => void;
  if (audioContext.audioWorklet) {
    const url = URL.createObjectURL(new Blob([WORKLET_SOURCE], { type: "application/javascript" }));
    try {
      await audioContext.audioWorklet.addModule(url);
    } finally {
      URL.revokeObjectURL(url);
    }
    const node = new AudioWorkletNode(audioContext, "pcm-tap", { numberOfInputs: 1, numberOfOutputs: 1 });
    node.port.onmessage = (event: MessageEvent<Float32Array>) => down.push(event.data);
    source.connect(node);
    node.connect(mute);
    disconnect = () => {
      node.port.onmessage = null;
      node.disconnect();
    };
  } else {
    const node = audioContext.createScriptProcessor(4096, 1, 1);
    node.onaudioprocess = (event) => down.push(event.inputBuffer.getChannelData(0));
    source.connect(node);
    node.connect(mute);
    disconnect = () => {
      node.onaudioprocess = null;
      node.disconnect();
    };
  }

  return {
    audioContext,
    analyser,
    stop: () => {
      disconnect();
      down.flush(); // 마지막 0.1초 미만도 보낸다 — 통화 끝 말이 잘리지 않게
      source.disconnect();
      audioContext.close().catch(() => {});
    },
  };
}
