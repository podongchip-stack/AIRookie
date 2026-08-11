# -*- coding: utf-8 -*-
"""음성 파일 -> STT -> 텍스트 기반 교정 -> SBAR 요약 시뮬레이션 GUI (tkinter).

처리 로직은 pipeline.py에 있고, 이 파일은 화면/스레드 처리만 담당한다.
hub 전송 등 통신은 하지 않는다.

실행 (Anaconda Prompt):
    conda activate AIRookieProject
    cd C:\\Dev\\Project\\AIRookieLocal\\simulation3
    python stt_summary_gui.py
"""

from __future__ import annotations

import json
import queue
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from pipeline import DEFAULT_MAX_NGRAM, STRUCTURE_SYSTEM_PROMPT, run_pipeline

AUDIO_FILETYPES = [
    ("오디오 파일", "*.wav *.mp3 *.m4a *.flac *.ogg *.webm *.mp4 *.aac"),
    ("모든 파일", "*.*"),
]

STT_MODELS = ["tiny", "base", "small", "medium", "large-v3"]
LLM_MODELS = ["qwen3:14b", "gpt-oss:20b", "qwen3.6:27b"]


class App:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        root.title("골든링크 음성 시뮬레이터 — STT → 텍스트 교정 → SBAR 요약")
        root.geometry("1040x760")

        self.queue: queue.Queue = queue.Queue()
        self.result: dict | None = None
        self.running = False
        self.started_at = 0.0

        self._build_widgets()
        self._poll_queue()

    # ------------------------------------------------------------------ UI
    def _build_widgets(self) -> None:
        top = ttk.Frame(self.root, padding=8)
        top.pack(fill="x")

        ttk.Label(top, text="음성 파일:").grid(row=0, column=0, sticky="w")
        self.path_var = tk.StringVar()
        ttk.Entry(top, textvariable=self.path_var).grid(
            row=0, column=1, sticky="ew", padx=4
        )
        ttk.Button(top, text="찾아보기...", command=self._browse).grid(row=0, column=2)
        top.columnconfigure(1, weight=1)

        # 모델 관련 옵션 (1줄) / 교정 관련 옵션 (2줄)로 나눠 담는다 — 한 줄에 다 넣으면
        # 옵션이 많아 창 폭을 줄였을 때 잘린다.
        models = ttk.Frame(self.root, padding=(8, 0, 8, 4))
        models.pack(fill="x")

        ttk.Label(models, text="STT 모델:").pack(side="left")
        self.stt_var = tk.StringVar(value="medium")
        ttk.Combobox(
            models, textvariable=self.stt_var, values=STT_MODELS, width=9, state="readonly"
        ).pack(side="left", padx=(2, 10))

        ttk.Label(models, text="장치:").pack(side="left")
        self.device_var = tk.StringVar(value="auto")
        ttk.Combobox(
            models,
            textvariable=self.device_var,
            values=["auto", "cuda", "cpu"],
            width=6,
            state="readonly",
        ).pack(side="left", padx=(2, 10))

        ttk.Label(models, text="요약 LLM:").pack(side="left")
        self.llm_var = tk.StringVar(value="qwen3:14b")
        ttk.Combobox(
            models, textvariable=self.llm_var, values=LLM_MODELS, width=12, state="readonly"
        ).pack(side="left", padx=(2, 10))

        self.run_button = ttk.Button(models, text="실행", command=self._start)
        self.run_button.pack(side="left", padx=4)
        self.save_button = ttk.Button(
            models, text="결과 JSON 저장", command=self._save, state="disabled"
        )
        self.save_button.pack(side="left")

        options = ttk.Frame(self.root, padding=(8, 0, 8, 8))
        options.pack(fill="x")

        self.correction_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            options, text="오인식 교정 (corrections.json)", variable=self.correction_var
        ).pack(side="left", padx=(0, 12))

        ttk.Label(options, text="최대 n-gram:").pack(side="left")
        self.ngram_var = tk.IntVar(value=DEFAULT_MAX_NGRAM)
        ttk.Spinbox(
            options, textvariable=self.ngram_var, from_=1, to=5, increment=1, width=4
        ).pack(side="left", padx=(2, 8))

        self.status_var = tk.StringVar(value="대기 중")
        ttk.Label(self.root, textvariable=self.status_var, padding=(8, 0)).pack(fill="x")

        # 환자 상태 한두 줄 요약 — 탭 안에 묻히지 않게 항상 보이는 자리에 둔다
        brief_box = ttk.LabelFrame(self.root, text="환자 상태 요약", padding=6)
        brief_box.pack(fill="x", padx=8, pady=(6, 0))
        self.brief_var = tk.StringVar(value="(실행 후 표시)")
        ttk.Label(
            brief_box,
            textvariable=self.brief_var,
            wraplength=980,
            justify="left",
            font=("Malgun Gothic", 11, "bold"),
        ).pack(fill="x")

        notebook = ttk.Notebook(self.root)
        notebook.pack(fill="both", expand=True, padx=8, pady=8)

        self.tabs: dict[str, ScrolledText] = {}
        self.frames: dict[str, ttk.Frame] = {}
        for name in ["진행 로그", "STT 원문", "교정 결과", "SBAR 요약"]:
            frame = ttk.Frame(notebook)
            notebook.add(frame, text=name)
            text = ScrolledText(frame, wrap="word", font=("Malgun Gothic", 10))
            text.pack(fill="both", expand=True)
            text.configure(state="disabled")
            self.tabs[name] = text
            self.frames[name] = frame
        self.notebook = notebook

        # 시스템 프롬프트 탭은 입력이라 self.tabs에 넣지 않는다
        # (실행할 때 self.tabs를 전부 비우므로 같이 지워진다).
        prompt_frame = ttk.Frame(notebook)
        notebook.add(prompt_frame, text="시스템 프롬프트")
        bar = ttk.Frame(prompt_frame, padding=(0, 4))
        bar.pack(fill="x")
        ttk.Label(
            bar, text="SBAR 구조화에 쓰는 시스템 프롬프트. 고쳐서 실행하면 그대로 반영된다."
        ).pack(side="left")
        ttk.Button(bar, text="기본값 복원", command=self._reset_prompt).pack(side="right")
        self.prompt_text = ScrolledText(prompt_frame, wrap="word", font=("Malgun Gothic", 10))
        self.prompt_text.pack(fill="both", expand=True)
        self.prompt_text.insert("end", STRUCTURE_SYSTEM_PROMPT)

    def _append(self, tab: str, content: str) -> None:
        widget = self.tabs[tab]
        widget.configure(state="normal")
        widget.insert("end", content + "\n")
        widget.see("end")
        widget.configure(state="disabled")

    def _set_tab(self, tab: str, content: str) -> None:
        widget = self.tabs[tab]
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("end", content)
        widget.configure(state="disabled")

    # ------------------------------------------------------------- actions
    def _reset_prompt(self) -> None:
        self.prompt_text.delete("1.0", "end")
        self.prompt_text.insert("end", STRUCTURE_SYSTEM_PROMPT)

    def _browse(self) -> None:
        path = filedialog.askopenfilename(filetypes=AUDIO_FILETYPES)
        if path:
            self.path_var.set(path)

    def _start(self) -> None:
        if self.running:
            return
        audio = self.path_var.get().strip()
        if not audio:
            messagebox.showwarning("입력 필요", "음성 파일을 선택하세요.")
            return
        if not Path(audio).exists():
            messagebox.showerror("오류", f"파일이 없습니다:\n{audio}")
            return
        system_prompt = self.prompt_text.get("1.0", "end").strip()
        if not system_prompt:
            messagebox.showwarning(
                "입력 필요", "시스템 프롬프트가 비어 있습니다.\n[기본값 복원]을 누르거나 직접 채우세요."
            )
            return

        self.running = True
        self.result = None
        self.started_at = time.perf_counter()
        self.run_button.configure(state="disabled")
        self.save_button.configure(state="disabled")
        for tab in self.tabs:
            self._set_tab(tab, "")
        self.brief_var.set("(요약 대기 중...)")
        self.notebook.select(self.frames["진행 로그"])

        params = {
            "audio_path": audio,
            "stt_model": self.stt_var.get(),
            "device": self.device_var.get(),
            "llm_model": self.llm_var.get(),
            "system_prompt": system_prompt,
            "use_correction": self.correction_var.get(),
            "max_ngram": int(self.ngram_var.get()),
        }
        threading.Thread(target=self._worker, args=(params,), daemon=True).start()

    def _worker(self, params: dict) -> None:
        try:
            result = run_pipeline(progress=lambda msg: self.queue.put(("log", msg)), **params)
            self.queue.put(("done", result))
        except Exception as e:
            self.queue.put(("error", str(e)))

    # ------------------------------------------------------------- polling
    def _poll_queue(self) -> None:
        try:
            while True:
                kind, payload = self.queue.get_nowait()
                if kind == "log":
                    self._append("진행 로그", payload)
                elif kind == "done":
                    self._on_done(payload)
                elif kind == "error":
                    self._on_error(payload)
        except queue.Empty:
            pass

        if self.running:
            elapsed = time.perf_counter() - self.started_at
            self.status_var.set(f"처리 중... {elapsed:.0f}초 경과")
        self.root.after(150, self._poll_queue)

    def _on_done(self, result: dict) -> None:
        self.running = False
        self.result = result
        self.run_button.configure(state="normal")
        self.save_button.configure(state="normal")
        elapsed = time.perf_counter() - self.started_at
        self.status_var.set(f"완료 ({elapsed:.0f}초)")
        self._append("진행 로그", f"\n전체 완료 ({elapsed:.0f}초)")
        self.brief_var.set(result["patient_brief"] or "(요약 없음 — LLM 요약이 꺼져 있습니다)")

        stt_lines = [
            f"[{row['start']:7.2f}s ~ {row['end']:7.2f}s] {row['text']}"
            for row in result["segments"]
        ]
        self._set_tab("STT 원문", "\n".join(stt_lines))

        post = result["text_postprocess"]
        message = result["call_summary_message"]
        if post:
            lines = [
                "== 교정 전 (STT 원문) ==",
                message["transcript"]["raw_text"],
                "",
                "== 교정 후 (LLM 입력) ==",
                message["transcript"]["filtered_text"],
                "",
                f"== 교정 내역 ({len(post['corrections'])}건) ==",
            ]
            for c in post["corrections"]:
                lines.append(
                    f'  "{c["original"]}" -> "{c["corrected"]}" '
                    f'({c["ngram"]}어절, 위치 {c["start"]}~{c["end"]})'
                )
            if not post["corrections"]:
                lines.append("  (교정된 구간 없음 — corrections.json에 등록된 오인식이 없었음)")
            if post["llm_notice"]:
                lines += ["", post["llm_notice"]]
            self._set_tab("교정 결과", "\n".join(lines))
        else:
            self._set_tab("교정 결과", "(오인식 교정 비활성화됨)")

        self._set_tab("SBAR 요약", json.dumps(message, ensure_ascii=False, indent=2))
        self.notebook.select(self.frames["SBAR 요약"])

    def _on_error(self, error: str) -> None:
        self.running = False
        self.run_button.configure(state="normal")
        self.status_var.set("오류 발생")
        self.brief_var.set("(오류로 요약하지 못했습니다)")
        self._append("진행 로그", f"\n오류: {error}")
        messagebox.showerror("오류", error)

    def _save(self) -> None:
        if not self.result:
            return
        default_name = Path(self.path_var.get()).stem + "_result.json"
        path = filedialog.asksaveasfilename(
            defaultextension=".json",
            initialfile=default_name,
            filetypes=[("JSON", "*.json")],
        )
        if not path:
            return
        Path(path).write_text(
            json.dumps(self.result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        self.status_var.set(f"저장됨: {path}")


def main() -> None:
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
