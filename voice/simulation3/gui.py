r"""Qwen3-ASR -> MF_BERT 실험용 데스크톱 시뮬레이터 (tkinter).

장비 마이크로 말하면 발화 단위로 인식하고, v2 17필드·hub로 갈 JSON을 보여준다.
실운영 경로가 아니다. 처리는 전부 voice/의 실운영 모듈을 import해서 쓴다 — 마이크(MicRecorder)·무음 감지
(LiveTranscriber)·ASR·MF_BERT·JSON 조립까지 app.py와 같은 코드라, 여기서 맞춘 무음 기준을 환경변수로 그대로
옮기면 된다. 사본이 없으니 화면 결과와 실제 hub 전송값이 달라질 일도 없다.

    마이크 -> MicRecorder -> LiveTranscriber (발화 단위 ASR)
                               -> 발화가 늘 때마다 MfBertExtractor.extract() -> v2 17필드
                               -> build_call_summary_message() -> hub JSON (전송·저장은 안 함)

    conda activate AIRookieProject
    python voice\simulation3\gui.py
"""
from __future__ import annotations

import argparse
import json
import queue
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from asr import SAMPLE_RATE, AsrModel, Segment  # noqa: E402
from MF_BERT import MfBertExtractor  # noqa: E402
from live_transcriber import SILENCE_RMS, UTTERANCE_HOLD_SEC, LiveTranscriber  # noqa: E402
from mic_recorder import MicRecorder  # noqa: E402
from transcribe import build_call_summary_message, load_models  # noqa: E402

SESSION_NAME = "simulation"
POLL_MS = 300

#: summary v2 17필드가 어디서 왔는지 — CLAUDE.md "AI 처리 / 규칙 기반" 구분을 화면에 드러낸다
FIELD_SOURCES = [
    ("call_type", "통화 종류", "미예측 (항상 null)"),
    ("ktas_level", "KTAS 중증도", "AI"),
    ("ktas_evidence", "KTAS 근거", "미예측 (항상 null)"),
    ("chief_complaint", "주 호소", "AI (대분류에 속한 소분류만 선택)"),
    ("suspected_diagnosis", "의심 진단", "AI 구간 태깅 (원문 그대로)"),
    ("vitals", "활력징후", "AI 구간 태깅 → 규칙 숫자 파싱"),
    ("consciousness", "의식", "AI (AVPU)"),
    ("symptoms", "증상", "AI"),
    ("onset", "발생 시점", "AI 구간 태깅 → 규칙 분 환산"),
    ("incidents", "발생 기전", "AI"),
    ("disease_category", "질병 분류", "AI (기전에 질병이 있을 때만)"),
    ("injuries", "손상", "AI"),
    ("treatments", "처치", "AI"),
    ("age", "나이", "AI 구간 태깅 → 규칙 나이 파싱"),
    ("sex", "성별", "AI"),
    ("medications", "복용약", "AI 유무 + 구간 태깅"),
    ("notes", "비고", "미예측 (항상 null)"),
]


def show(value) -> str:
    if value is None:
        return "—"
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def render(extractor: MfBertExtractor, segments: list[Segment], duration_sec: float) -> dict | None:
    """구간 목록 -> 화면에 채울 값. 인식된 말이 없으면 None."""
    text = "\n".join(s.text for s in segments)
    if not text:
        return None
    summary, seconds = extractor.extract(text)
    message = build_call_summary_message(segments, duration_sec, SESSION_NAME, summary)
    return {
        "fields": [(label, show(summary[key]), source) for key, label, source in FIELD_SOURCES],
        "json": json.dumps(message.to_payload(), ensure_ascii=False, indent=2),
        "seconds": seconds,
    }


def make_table(parent, columns: list[tuple[str, int]], height: int) -> ttk.Treeview:
    frame = ttk.Frame(parent)
    frame.pack(fill="both", expand=True)
    table = ttk.Treeview(frame, columns=[name for name, _ in columns], show="headings", height=height)
    for name, width in columns:
        table.heading(name, text=name)
        table.column(name, width=width, anchor="w", stretch=True)
    scroll = ttk.Scrollbar(frame, orient="vertical", command=table.yview)
    table.configure(yscrollcommand=scroll.set)
    table.pack(side="left", fill="both", expand=True)
    scroll.pack(side="right", fill="y")
    return table


def fill_table(table: ttk.Treeview, rows) -> None:
    table.delete(*table.get_children())
    for row in rows:
        table.insert("", "end", values=row)


class SimulatorApp:
    """화면과 스레드만 담당한다. 인식·구조화는 전부 voice/ 모듈이 한다.

    tkinter 위젯은 메인 스레드에서만 만진다 — 모델 로딩·마무리 인식처럼 오래 걸리는 일은 작업 스레드에서
    돌리고, 결과는 큐로 넘겨 POLL_MS마다 메인 스레드가 꺼내 화면에 반영한다.
    """

    def __init__(self, root: tk.Tk, device: str) -> None:
        self.root = root
        self.device = device
        self.asr_model: AsrModel | None = None
        self.extractor: MfBertExtractor | None = None
        self.recorder: MicRecorder | None = None
        self.live: LiveTranscriber | None = None
        self.shown = 0
        self.meter_pos = 0
        self.results: queue.Queue = queue.Queue()

        root.title("Qwen3-ASR → MF_BERT 시뮬레이터")
        root.geometry("1400x860")
        self._build()
        self._set_status("모델 로딩 중… (약 15~20초)")
        threading.Thread(target=self._load_models, daemon=True).start()
        root.after(POLL_MS, self._poll)

    # --- 화면 구성 ---------------------------------------------------------

    def _build(self) -> None:
        left = ttk.Frame(self.root, padding=10)
        left.pack(side="left", fill="y")
        right = ttk.Frame(self.root, padding=(0, 10, 10, 10))
        right.pack(side="left", fill="both", expand=True)

        buttons = ttk.Frame(left)
        buttons.pack(fill="x")
        self.start_button = ttk.Button(buttons, text="통화 시작", command=self.start_call, state="disabled")
        self.start_button.pack(side="left", expand=True, fill="x")
        self.stop_button = ttk.Button(buttons, text="통화 종료", command=self.stop_call, state="disabled")
        self.stop_button.pack(side="left", expand=True, fill="x")

        self.threshold = tk.DoubleVar(value=SILENCE_RMS)
        self.hold = tk.DoubleVar(value=UTTERANCE_HOLD_SEC)
        self._slider(left, "무음 기준 RMS (VOICE_SILENCE_RMS)", self.threshold, 0.002, 0.05, "{:.3f}",
                     "이보다 작은 소리는 말이 아닌 것으로 본다.\n시끄러우면 올린다. 통화 시작 시점 값이 적용된다")
        self._slider(left, "발화 끊김 판정 초 (VOICE_UTTERANCE_HOLD_SEC)", self.hold, 0.2, 1.5, "{:.1f}",
                     "이만큼 조용하면 한 발화가 끝난 것으로 본다.\n말하다 자꾸 끊기면 늘린다")

        ttk.Label(left, text="현재 마이크 음량 (최근 0.5초 RMS)").pack(anchor="w", pady=(16, 0))
        self.meter = ttk.Progressbar(left, maximum=0.05, length=280)
        self.meter.pack(fill="x")
        self.meter_label = ttk.Label(left, text="—")
        self.meter_label.pack(anchor="w")

        self.status = ttk.Label(left, text="", wraplength=280, justify="left")
        self.status.pack(anchor="w", pady=(16, 0))

        top = ttk.Frame(right)
        top.pack(fill="both", expand=True)
        box = ttk.LabelFrame(top, text="summary v2 17필드 (hub로 가는 값)", padding=4)
        box.pack(side="left", fill="both", expand=True)
        self.fields_table = make_table(box, [("필드", 100), ("값", 420), ("근거", 240)], 12)
        box = ttk.LabelFrame(top, text="발화별 인식", padding=4)
        box.pack(side="left", fill="both", expand=True, padx=(8, 0))
        self.utterance_table = make_table(box, [("시작(초)", 60), ("끝(초)", 60), ("인식 텍스트", 320)], 12)

        box = ttk.LabelFrame(right, text="hub 전송 JSON 미리보기 (CallSummaryMessage, 스키마 검증 통과본 — 전송 안 함)",
                             padding=4)
        box.pack(fill="both", expand=True, pady=(8, 0))
        self.json_text = ScrolledText(box, height=12, font=("Consolas", 9))
        self.json_text.pack(fill="both", expand=True)

    def _slider(self, parent, title: str, variable: tk.DoubleVar, low: float, high: float, fmt: str, help_text: str):
        ttk.Label(parent, text=title).pack(anchor="w", pady=(16, 0))
        value_label = ttk.Label(parent, text=fmt.format(variable.get()))
        ttk.Scale(parent, from_=low, to=high, variable=variable, length=280,
                  command=lambda _: value_label.config(text=fmt.format(variable.get()))).pack(fill="x")
        value_label.pack(anchor="w")
        ttk.Label(parent, text=help_text, foreground="gray").pack(anchor="w")

    def _set_status(self, text: str) -> None:
        self.status.config(text=text)

    # --- 동작 ---------------------------------------------------------------

    def _load_models(self) -> None:
        try:
            self.results.put(("loaded", load_models(self.device)))
        except Exception as e:  # 가중치 경로 오류 등 — 화면에 그대로 보여준다
            self.results.put(("error", f"모델 로딩 실패: {e}"))

    def start_call(self) -> None:
        recorder = MicRecorder()
        try:
            recorder.start()
        except RuntimeError as e:
            self._set_status(str(e))
            return
        self.recorder = recorder
        self.live = LiveTranscriber(recorder, self.asr_model, threshold=self.threshold.get(), hold_sec=self.hold.get())
        self.live.start()
        self.shown = 0
        self.meter_pos = 0
        for table in (self.fields_table, self.utterance_table):
            fill_table(table, [])
        self.json_text.delete("1.0", "end")
        self.start_button.config(state="disabled")
        self.stop_button.config(state="normal")
        self._set_status(f"통화 중 — 말이 끊길 때마다 인식합니다.\n(무음 기준 {self.threshold.get():.3f}, "
                         f"끊김 판정 {self.hold.get():.1f}초)")

    def stop_call(self) -> None:
        recorder, live = self.recorder, self.live
        self.recorder = None
        self.live = None
        recorder.stop()
        self.stop_button.config(state="disabled")
        self._set_status("통화 종료 — 남은 발화 인식·구조화 중…")
        duration = len(recorder.snapshot()) / SAMPLE_RATE

        def finish() -> None:
            segments = live.finish()
            self.results.put(("final", (segments, render(self.extractor, segments, duration), duration)))

        threading.Thread(target=finish, daemon=True).start()

    def _poll(self) -> None:
        while not self.results.empty():
            kind, payload = self.results.get()
            if kind == "loaded":
                self.asr_model, self.extractor = payload
                self.start_button.config(state="normal")
                self._set_status(f"준비 완료 (ASR device={self.asr_model.device}).\n'통화 시작'을 누르고 말하세요.")
            elif kind == "error":
                self._set_status(payload)
            elif kind == "final":
                segments, view, duration = payload
                self._show(segments, view, duration, "통화 종료 — 최종 결과")
                self.start_button.config(state="normal")

        if self.recorder is not None:
            self._update_meter()
            segments = self.live.segments
            if len(segments) != self.shown:
                self.shown = len(segments)
                duration = self.meter_pos / SAMPLE_RATE
                self._show(segments, render(self.extractor, segments, duration), duration, "통화 중")
        self.root.after(POLL_MS, self._poll)

    def _update_meter(self) -> None:
        new = self.recorder.samples_since(self.meter_pos)
        self.meter_pos += len(new)
        recent = new[-SAMPLE_RATE // 2:]
        if len(recent):
            rms = float(np.sqrt(np.mean(recent**2)))
            self.meter["value"] = min(rms, 0.05)
            speaking = "말소리로 봄" if rms >= self.threshold.get() else "무음으로 봄"
            self.meter_label.config(text=f"{rms:.4f}  ({speaking})")

    def _show(self, segments: list[Segment], view: dict | None, duration: float, note: str) -> None:
        fill_table(self.utterance_table, [(f"{s.start:.1f}", f"{s.end:.1f}", s.text) for s in segments])
        self.utterance_table.yview_moveto(1.0)
        if view is None:
            self._set_status(f"{note} · 인식된 발화 없음 (무음 기준을 낮춰 보세요)")
            return
        fill_table(self.fields_table, view["fields"])
        self.json_text.delete("1.0", "end")
        self.json_text.insert("1.0", view["json"])
        self._set_status(f"{note} · 발화 {len(segments)}건 · 통화 {duration:.1f}초 · MF_BERT {view['seconds']:.2f}초")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--device", choices=["auto", "cuda", "mps", "cpu"], default="auto")
    args = parser.parse_args()

    root = tk.Tk()
    SimulatorApp(root, args.device)
    root.mainloop()


if __name__ == "__main__":
    main()
