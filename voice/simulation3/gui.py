r"""Qwen3-ASR -> HMM 실험용 데스크톱 시뮬레이터 (tkinter).

장비 마이크로 말하면 발화 단위로 인식하고, 6필드·모델 판정 중간값·hub로 갈 JSON을 보여준다.
실운영 경로가 아니다. 처리는 전부 voice/의 실운영 모듈을 import해서 쓴다 — 마이크(MicRecorder)·무음 감지
(LiveTranscriber)·ASR·HMM·JSON 조립까지 app.py와 같은 코드라, 여기서 맞춘 무음 기준을 환경변수로 그대로
옮기면 된다. 사본이 없으니 화면 결과와 실제 hub 전송값이 달라질 일도 없다.

    마이크 -> MicRecorder -> LiveTranscriber (발화 단위 ASR)
                               -> 발화가 늘 때마다 HmmExtractor.analyze() -> 6필드·중간값
                               -> build_call_summary_message() -> hub JSON (전송·저장은 안 함)

    conda activate AIRookieProject
    python voice\simulation3\gui.py
"""
from __future__ import annotations

import argparse
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
from hmm import HmmExtractor  # noqa: E402
from hmm import labels as L  # noqa: E402
from hmm.symptom_names import standard_names  # noqa: E402
from live_transcriber import SILENCE_RMS, UTTERANCE_HOLD_SEC, LiveTranscriber  # noqa: E402
from mic_recorder import MicRecorder  # noqa: E402
from transcribe import build_call_summary_message, load_models  # noqa: E402

SESSION_NAME = "simulation"
POLL_MS = 300

#: summary 6필드가 어디서 왔는지 — CLAUDE.md "AI 처리 / 규칙 기반" 구분을 화면에 드러낸다
FIELD_SOURCES = [
    ("patient", "환자", "AI 나이대·성별 → 규칙 연결"),
    ("mechanism", "발생 기전", "AI 원인·부위 → 규칙 조립 (질병이면 대표 증상)"),
    ("symptoms", "증상", "AI 증상 구간 → 규칙 표준명"),
    ("treatment", "처치", "AI (시행 확률 0.5 이상)"),
    ("severity_tag", "중증도", "AI"),
    ("required_department", "필요 진료과", "규칙 (원인·부위 → 전문과목 대응표)"),
]

#: 조립 전 모델 판정 — hmm/decode.py decode_example()의 fields
DETAIL_ROWS = [
    ("cause", "원인", "AI"),
    ("cause_type", "원인 유형", "규칙 (원인에서 결정)"),
    ("body_part", "부위", "AI (외상·손상일 때만)"),
    ("representative_symptom", "대표 증상", "규칙 (질병일 때 첫 '있음' 증상)"),
    ("age_band", "나이대", "AI"),
    ("sex", "성별", "AI"),
    ("severity_tag", "중증도", "AI"),
    ("treatment", "처치", "AI"),
]


def show(value) -> str:
    if value is None:
        return "판단 보류"
    if isinstance(value, list):
        return ", ".join(value) if value else "—"
    return value or "—"


def show_detail(key: str, fields: dict) -> str:
    """부위는 외상·손상일 때만, 대표 증상은 질병일 때만 쓰는 값이라 그 밖에는 '판단 보류'가 아니라 '해당 없음'이다."""
    if key == "body_part" and fields["cause_type"] not in (L.TRAUMA, L.NON_TRAUMATIC_INJURY):
        return "해당 없음 (외상·손상 아님)"
    if key == "representative_symptom" and fields["cause_type"] != L.DISEASE:
        return "해당 없음 (질병 아님)"
    return show(fields[key])


def render(extractor: HmmExtractor, segments: list[Segment], duration_sec: float) -> dict | None:
    """구간 목록 -> 화면에 채울 값. 인식된 말이 없으면 None."""
    text = "\n".join(s.text for s in segments)
    if not text:
        return None
    result = extractor.analyze(text)
    summary, fields = result["final_output"], result["fields"]
    message = build_call_summary_message(segments, duration_sec, SESSION_NAME, summary)
    return {
        "fields": [(label, show(summary[key]), source) for key, label, source in FIELD_SOURCES],
        "details": [(label, show_detail(key, fields), source) for key, label, source in DETAIL_ROWS],
        "spans": [
            (span["span_text"], "있음" if span["present"] else "없음",
             ", ".join(name for _, name in standard_names(span["span_text"])) or "(사전에 없음 — 원문 그대로)")
            for span in result["symptom_spans"]
        ],
        "json": message.model_dump_json(exclude_none=True, indent=2),
        "seconds": result["seconds"],
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
        self.extractor: HmmExtractor | None = None
        self.recorder: MicRecorder | None = None
        self.live: LiveTranscriber | None = None
        self.shown = 0
        self.meter_pos = 0
        self.results: queue.Queue = queue.Queue()

        root.title("Qwen3-ASR → HMM 시뮬레이터")
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
        box = ttk.LabelFrame(top, text="summary 6필드 (hub로 가는 값)", padding=4)
        box.pack(side="left", fill="both", expand=True)
        self.fields_table = make_table(box, [("필드", 90), ("값", 300), ("근거", 260)], 6)
        box = ttk.LabelFrame(top, text="모델 판정 중간값 (조립 전)", padding=4)
        box.pack(side="left", fill="both", expand=True, padx=(8, 0))
        self.details_table = make_table(box, [("판정", 80), ("값", 200), ("처리", 200)], 8)

        middle = ttk.Frame(right)
        middle.pack(fill="both", expand=True, pady=(8, 0))
        box = ttk.LabelFrame(middle, text="발화별 인식", padding=4)
        box.pack(side="left", fill="both", expand=True)
        self.utterance_table = make_table(box, [("시작(초)", 60), ("끝(초)", 60), ("인식 텍스트", 480)], 10)
        box = ttk.LabelFrame(middle, text="증상 구간 (AI 태깅)", padding=4)
        box.pack(side="left", fill="both", expand=True, padx=(8, 0))
        self.spans_table = make_table(box, [("증상 구간 원문", 220), ("있음/없음", 70), ("표준명", 150)], 10)

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
        for table in (self.fields_table, self.details_table, self.utterance_table, self.spans_table):
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
        fill_table(self.details_table, view["details"])
        fill_table(self.spans_table, view["spans"])
        self.json_text.delete("1.0", "end")
        self.json_text.insert("1.0", view["json"])
        self._set_status(f"{note} · 발화 {len(segments)}건 · 통화 {duration:.1f}초 · HMM {view['seconds']:.2f}초")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--device", choices=["auto", "cuda", "mps", "cpu"], default="auto")
    args = parser.parse_args()

    root = tk.Tk()
    SimulatorApp(root, args.device)
    root.mainloop()


if __name__ == "__main__":
    main()
