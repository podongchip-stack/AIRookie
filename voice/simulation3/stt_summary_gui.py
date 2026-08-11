# -*- coding: utf-8 -*-
"""음성 -> STT -> 오인식 교정 -> SBAR 요약 시연/실험 GUI (tkinter).

처리 로직은 pipeline.py에 있고, 이 파일은 화면과 스레드만 담당한다.
hub 전송 등 통신은 하지 않는다.

화면은 두 층으로 나뉜다.
    시연 영역 - 단계 표시등 / 환자 상태 / SBAR 카드 / 교정 전후 대비.
               팀 시연 중에 그대로 띄우는 화면이라 글씨를 키우고 군더더기를 뺐다.
    개발자 영역 - 모델·장치·n-gram 설정, 진행 로그, 결과 JSON, 시스템 프롬프트 편집.
               [개발자 옵션] 버튼으로 접었다 편다. 사전 튜닝 기능은 하나도 안 뺐다.

실측(RTX 5080, medium + qwen3:14b): 108초 통화 기준 STT 14.6초 + 교정 0.0초 +
구조화 9.7초 + 요약 4.2초 = 약 28초. 실시간으로 돌려도 시연이 끊기지 않는
수준이라, 미리 돌려둔 결과를 재생하는 장치는 두지 않았다.

실행 (Anaconda Prompt):
    conda activate AIRookieProject
    cd C:\\Dev\\Project\\AIRookie\\voice\\simulation3
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

SCRIPT_DIR = Path(__file__).resolve().parent
VOICE_DIR = SCRIPT_DIR.parent

# 통화 선택 드롭다운을 채울 폴더들. 시연 중에 파일 탐색기를 여는 건 산만해서,
# 여기 있는 오디오를 미리 목록에 올려둔다(찾아보기로 다른 파일도 열 수 있다).
#   - voice/data/origin_data      : 손으로 넣어둔 통화 녹음
#   - <repo>/data/voice_data/...  : call_capture.py/app.py가 마이크로 녹음한 파일
AUDIO_DIRS = [
    VOICE_DIR / "data" / "origin_data",
    VOICE_DIR.parent / "data" / "voice_data" / "origin_data",
]
AUDIO_SUFFIXES = {".wav", ".mp3", ".m4a", ".flac", ".ogg", ".webm", ".mp4", ".aac"}

AUDIO_FILETYPES = [
    ("오디오 파일", "*.wav *.mp3 *.m4a *.flac *.ogg *.webm *.mp4 *.aac"),
    ("모든 파일", "*.*"),
]

STT_MODELS = ["tiny", "base", "small", "medium", "large-v3"]
LLM_MODELS = ["qwen3:14b", "gpt-oss:20b", "qwen3.6:27b"]

# 프로젝터/화면공유에서 읽히도록 키웠다.
FONT_TITLE = ("Malgun Gothic", 15, "bold")
FONT_BRIEF = ("Malgun Gothic", 14, "bold")
FONT_FIELD = ("Malgun Gothic", 13)
FONT_KEY = ("Malgun Gothic", 11, "bold")
FONT_BODY = ("Malgun Gothic", 12)
FONT_SMALL = ("Malgun Gothic", 10)

COLOR_BEFORE = "#ffd9d9"  # 교정 전 구간 (오인식)
COLOR_AFTER = "#d6f5d6"   # 교정 후 구간
SEVERITY_COLORS = {"high": "#d64545", "medium": "#d98324", "low": "#3f8f4f"}

# 단계 표시등. pipeline.progress가 넘겨주는 문장으로 현재 단계를 판정한다.
STAGES = [("audio", "음성"), ("stt", "STT"), ("correct", "교정"), ("structure", "구조화")]

# run_pipeline이 돌려주는 timings 키 -> 화면에 띄울 이름
TIMING_LABELS = {"stt": "STT", "correction": "교정", "summarize": "구조화", "brief": "요약"}


def _stage_of(message: str) -> str | None:
    """진행 메시지 한 줄이 어느 단계 것인지 판정한다.

    pipeline.run_pipeline은 사람이 읽는 문장만 넘겨주므로 키워드로 가른다.
    pipeline 쪽에 단계 코드를 새로 심는 대신 이쪽에서 해석하는 이유는, 시연용
    화면 사정 때문에 처리 로직의 인터페이스를 바꾸고 싶지 않아서다.
    """
    if "모델 로딩" in message or "변환" in message:
        return "stt"
    if "교정" in message:
        return "correct"
    if "구조화" in message or "요약" in message:
        return "structure"
    return None


def _correction_spans(corrections: list[dict]) -> tuple[list, list]:
    """교정 전/후 텍스트에서 각각 하이라이트할 (시작, 끝) 문자 위치를 만든다.

    corrections의 start/end는 교정 **전** 텍스트 기준이다. 치환하면서 길이가
    달라지므로, 앞선 교정들의 길이 변화를 누적(delta)해 교정 후 위치를 구한다.
    """
    before: list[tuple[int, int]] = []
    after: list[tuple[int, int]] = []
    delta = 0
    for c in corrections:
        before.append((c["start"], c["end"]))
        start = c["start"] + delta
        after.append((start, start + len(c["corrected"])))
        delta += len(c["corrected"]) - len(c["original"])
    return before, after


def _discover_audio() -> list[Path]:
    """드롭다운에 올릴 오디오 파일을 모은다 (이름순, 중복 제거)."""
    found: dict[str, Path] = {}
    for folder in AUDIO_DIRS:
        if not folder.is_dir():
            continue
        for path in sorted(folder.iterdir()):
            if path.is_file() and path.suffix.lower() in AUDIO_SUFFIXES:
                found.setdefault(str(path), path)
    return list(found.values())


class App:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        root.title("골든링크 — 응급이송 통화 자동 구조화")
        root.geometry("1240x920")
        root.minsize(1040, 760)

        self.queue: queue.Queue = queue.Queue()
        self.result: dict | None = None
        self.running = False
        self.started_at = 0.0
        self.current_stage: str | None = None
        self.dev_visible = False
        self.audio_paths: list[Path] = []

        self._build_widgets()
        self._reload_audio_list()
        self._render_stages(None)
        self._poll_queue()

    # ------------------------------------------------------------------ UI
    def _build_widgets(self) -> None:
        # --- 상단: 제목 + 통화 선택 + 실행 -------------------------------
        header = ttk.Frame(self.root, padding=(12, 10, 12, 4))
        header.pack(fill="x")
        ttk.Label(header, text="골든링크 — 응급이송 통화 자동 구조화", font=FONT_TITLE).pack(side="left")
        self.dev_button = ttk.Button(header, text="개발자 옵션 ▾", width=14, command=self._toggle_dev)
        self.dev_button.pack(side="right")

        picker = ttk.Frame(self.root, padding=(12, 0, 12, 8))
        picker.pack(fill="x")
        ttk.Label(picker, text="통화", font=FONT_KEY).pack(side="left", padx=(0, 6))
        self.audio_var = tk.StringVar()
        self.audio_combo = ttk.Combobox(
            picker, textvariable=self.audio_var, state="readonly", font=FONT_BODY
        )
        self.audio_combo.pack(side="left", fill="x", expand=True)
        ttk.Button(picker, text="새로고침", width=9, command=self._reload_audio_list).pack(side="left", padx=(6, 0))
        ttk.Button(picker, text="찾아보기…", width=11, command=self._browse).pack(side="left", padx=(4, 8))
        self.run_button = ttk.Button(picker, text="▶  실행", width=10, command=self._start)
        self.run_button.pack(side="left")

        # --- 개발자 옵션 (접힘) ------------------------------------------
        self.dev_options = ttk.LabelFrame(self.root, text="개발자 옵션", padding=8)

        row1 = ttk.Frame(self.dev_options)
        row1.pack(fill="x", pady=(0, 4))
        ttk.Label(row1, text="STT 모델").pack(side="left")
        self.stt_var = tk.StringVar(value="medium")
        ttk.Combobox(row1, textvariable=self.stt_var, values=STT_MODELS, width=9,
                     state="readonly").pack(side="left", padx=(4, 12))
        ttk.Label(row1, text="장치").pack(side="left")
        self.device_var = tk.StringVar(value="auto")
        ttk.Combobox(row1, textvariable=self.device_var, values=["auto", "cuda", "cpu"], width=6,
                     state="readonly").pack(side="left", padx=(4, 12))
        ttk.Label(row1, text="요약 LLM").pack(side="left")
        self.llm_var = tk.StringVar(value="qwen3:14b")
        ttk.Combobox(row1, textvariable=self.llm_var, values=LLM_MODELS, width=13,
                     state="readonly").pack(side="left", padx=(4, 12))
        self.save_button = ttk.Button(row1, text="결과 JSON 저장", command=self._save, state="disabled")
        self.save_button.pack(side="right")

        row2 = ttk.Frame(self.dev_options)
        row2.pack(fill="x")
        self.correction_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(row2, text="오인식 교정 (corrections.json)",
                        variable=self.correction_var).pack(side="left", padx=(0, 12))
        self.summarize_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(row2, text="LLM 요약", variable=self.summarize_var).pack(side="left", padx=(0, 12))
        ttk.Label(row2, text="최대 n-gram").pack(side="left")
        self.ngram_var = tk.IntVar(value=DEFAULT_MAX_NGRAM)
        ttk.Spinbox(row2, textvariable=self.ngram_var, from_=1, to=5, increment=1,
                    width=4).pack(side="left", padx=(4, 0))

        # --- 단계 표시등 --------------------------------------------------
        # 개발자 옵션을 펼칠 때 이 프레임 바로 앞에 끼워 넣으므로 참조를 들고 있는다.
        stages = ttk.Frame(self.root, padding=(12, 6))
        self.stages_frame = stages
        stages.pack(fill="x")
        self.stage_labels: dict[str, ttk.Label] = {}
        for index, (key, label) in enumerate(STAGES):
            if index:
                ttk.Label(stages, text="──▶", font=FONT_SMALL,
                          foreground="#999").pack(side="left", padx=6)
            widget = ttk.Label(stages, text=f"○ {label}", font=FONT_KEY)
            widget.pack(side="left")
            self.stage_labels[key] = widget
        self.status_var = tk.StringVar(value="대기 중")
        ttk.Label(stages, textvariable=self.status_var, font=FONT_BODY,
                  foreground="#555").pack(side="right")

        # --- 환자 상태 요약 -----------------------------------------------
        brief_box = ttk.LabelFrame(self.root, text="환자 상태", padding=8)
        brief_box.pack(fill="x", padx=12, pady=(2, 6))
        self.brief_var = tk.StringVar(value="(통화를 선택하고 실행하세요)")
        self.brief_label = ttk.Label(brief_box, textvariable=self.brief_var, font=FONT_BRIEF,
                                     wraplength=1160, justify="left")
        self.brief_label.pack(fill="x")
        brief_box.bind("<Configure>",
                       lambda e: self.brief_label.configure(wraplength=max(400, e.width - 30)))

        # --- SBAR 카드 ------------------------------------------------------
        self.card = ttk.LabelFrame(self.root, text="구조화 결과", padding=8)
        self.card.pack(fill="x", padx=12, pady=(0, 6))
        self.card_fields: dict[str, ttk.Frame] = {}
        layout = [("환자", "patient", 0, 0), ("기전", "mechanism", 0, 1),
                  ("증상", "symptoms", 1, 0), ("중증도", "severity_tag", 1, 1),
                  ("처치", "treatment", 2, 0), ("진료과", "required_department", 2, 1)]
        for label, key, row, col in layout:
            ttk.Label(self.card, text=label, font=FONT_KEY, width=7,
                      anchor="w").grid(row=row, column=col * 2, sticky="nw", pady=3)
            holder = ttk.Frame(self.card)
            holder.grid(row=row, column=col * 2 + 1, sticky="new", padx=(4, 24), pady=3)
            self.card_fields[key] = holder
        self.card.columnconfigure(1, weight=1)
        self.card.columnconfigure(3, weight=1)
        self._clear_card()

        # --- 교정 전후 대비 -------------------------------------------------
        compare = ttk.Frame(self.root, padding=(12, 0, 12, 6))
        compare.pack(fill="both", expand=True)
        self.correction_count = tk.StringVar(value="")

        left = ttk.LabelFrame(compare, text="STT 원문 (교정 전)", padding=4)
        left.pack(side="left", fill="both", expand=True, padx=(0, 4))
        self.before_text = ScrolledText(left, wrap="word", font=FONT_FIELD, height=10)
        self.before_text.pack(fill="both", expand=True)
        self.before_text.tag_configure("hit", background=COLOR_BEFORE)
        self.before_text.configure(state="disabled")

        right = ttk.LabelFrame(compare, text="교정 후 (LLM 입력)", padding=4)
        right.pack(side="left", fill="both", expand=True, padx=(4, 0))
        ttk.Label(right, textvariable=self.correction_count, font=FONT_SMALL,
                  foreground="#3f8f4f").pack(anchor="e")
        self.after_text = ScrolledText(right, wrap="word", font=FONT_FIELD, height=10)
        self.after_text.pack(fill="both", expand=True)
        self.after_text.tag_configure("hit", background=COLOR_AFTER)
        self.after_text.configure(state="disabled")

        # --- 개발자 탭 (접힘) -------------------------------------------------
        self.dev_notebook = ttk.Notebook(self.root)
        self.tabs: dict[str, ScrolledText] = {}
        for name in ["진행 로그", "결과 JSON"]:
            frame = ttk.Frame(self.dev_notebook)
            self.dev_notebook.add(frame, text=name)
            widget = ScrolledText(frame, wrap="word", font=FONT_SMALL, height=10)
            widget.pack(fill="both", expand=True)
            widget.configure(state="disabled")
            self.tabs[name] = widget

        # 시스템 프롬프트 탭은 입력이라 self.tabs에 넣지 않는다
        # (실행할 때 self.tabs를 전부 비우므로 같이 지워진다).
        prompt_frame = ttk.Frame(self.dev_notebook)
        self.dev_notebook.add(prompt_frame, text="시스템 프롬프트")
        bar = ttk.Frame(prompt_frame, padding=(0, 4))
        bar.pack(fill="x")
        ttk.Label(bar, text="SBAR 구조화에 쓰는 시스템 프롬프트. 고쳐서 실행하면 그 실행에만 반영된다.",
                  font=FONT_SMALL).pack(side="left")
        ttk.Button(bar, text="기본값 복원", command=self._reset_prompt).pack(side="right")
        self.prompt_text = ScrolledText(prompt_frame, wrap="word", font=FONT_SMALL, height=10)
        self.prompt_text.pack(fill="both", expand=True)
        self.prompt_text.insert("end", STRUCTURE_SYSTEM_PROMPT)

    # --------------------------------------------------------- 화면 갱신
    def _toggle_dev(self) -> None:
        self.dev_visible = not self.dev_visible
        if self.dev_visible:
            # 옵션은 통화 선택 바로 아래(=단계 표시등 앞), 로그 탭은 맨 아래에 끼워 넣는다.
            self.dev_options.pack(fill="x", padx=12, pady=(0, 4), before=self.stages_frame)
            self.dev_notebook.pack(fill="both", expand=True, padx=12, pady=(0, 10))
            self.dev_button.configure(text="개발자 옵션 ▴")
        else:
            self.dev_options.pack_forget()
            self.dev_notebook.pack_forget()
            self.dev_button.configure(text="개발자 옵션 ▾")

    def _render_stages(self, active: str | None, done: bool = False) -> None:
        """단계 표시등을 갱신한다. active 앞 단계는 완료(●), 자신은 진행 중(◐).

        done=True면 전 단계를 완료로 칠한다 (처리가 끝난 시점).
        """
        order = [key for key, _ in STAGES]
        active_index = order.index(active) if active in order else -1
        for index, (key, label) in enumerate(STAGES):
            if done:
                mark, color = "●", "#3f8f4f"
            elif active is None:
                mark, color = "○", "#999"
            elif index < active_index:
                mark, color = "●", "#3f8f4f"
            elif index == active_index:
                mark, color = "◐", "#1a6fd4"
            else:
                mark, color = "○", "#999"
            self.stage_labels[key].configure(text=f"{mark} {label}", foreground=color)

    def _set_stage(self, stage: str | None) -> None:
        if stage and stage != self.current_stage:
            self.current_stage = stage
            self._render_stages(stage)

    def _clear_card(self) -> None:
        for holder in self.card_fields.values():
            for child in holder.winfo_children():
                child.destroy()
            ttk.Label(holder, text="—", font=FONT_FIELD, foreground="#999").pack(side="left")

    def _fill_card(self, summary: dict | None) -> None:
        for holder in self.card_fields.values():
            for child in holder.winfo_children():
                child.destroy()
        if not summary:
            self._clear_card()
            return

        for key in ("patient", "mechanism", "required_department"):
            value = summary.get(key) or "—"
            ttk.Label(self.card_fields[key], text=value, font=FONT_FIELD).pack(side="left")

        for key in ("symptoms", "treatment"):
            items = summary.get(key) or []
            holder = self.card_fields[key]
            if not items:
                ttk.Label(holder, text="—", font=FONT_FIELD, foreground="#999").pack(side="left")
                continue
            for item in items:
                tk.Label(holder, text=f" {item} ", font=FONT_BODY, bg="#e8eef7",
                         fg="#1a3a5c", padx=6, pady=2).pack(side="left", padx=(0, 4))

        severity = summary.get("severity_tag") or "medium"
        tk.Label(self.card_fields["severity_tag"], text=f" {severity.upper()} ", font=FONT_KEY,
                 bg=SEVERITY_COLORS.get(severity, "#888"), fg="white",
                 padx=8, pady=2).pack(side="left")

    def _set_compare(self, before: str, after: str,
                     corrections: list[dict] | None) -> None:
        before_spans, after_spans = _correction_spans(corrections or [])
        for widget, content, spans in (
            (self.before_text, before, before_spans),
            (self.after_text, after, after_spans),
        ):
            widget.configure(state="normal")
            widget.delete("1.0", "end")
            widget.insert("end", content)
            for start, end in spans:
                widget.tag_add("hit", f"1.0 + {start}c", f"1.0 + {end}c")
            widget.configure(state="disabled")
        # 첫 교정 위치로 스크롤 — 긴 통화에서 하이라이트가 화면 밖에 있으면 안 보인다
        if before_spans:
            self.before_text.see(f"1.0 + {before_spans[0][0]}c")
            self.after_text.see(f"1.0 + {after_spans[0][0]}c")

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
    def _reload_audio_list(self) -> None:
        previous = self.audio_var.get()
        self.audio_paths = _discover_audio()
        labels = [f"{p.name}   ({p.parent.name})" for p in self.audio_paths]
        self.audio_combo.configure(values=labels)
        if not labels:
            self.audio_var.set("")
        elif previous in labels:
            self.audio_combo.current(labels.index(previous))  # 새로고침 전 선택 유지
        else:
            self.audio_combo.current(0)

    def _selected_audio(self) -> Path | None:
        index = self.audio_combo.current()
        if 0 <= index < len(self.audio_paths):
            return self.audio_paths[index]
        return None

    def _browse(self) -> None:
        path = filedialog.askopenfilename(filetypes=AUDIO_FILETYPES)
        if not path:
            return
        chosen = Path(path)
        self.audio_paths.append(chosen)
        self.audio_combo.configure(
            values=[f"{p.name}   ({p.parent.name})" for p in self.audio_paths]
        )
        self.audio_combo.current(len(self.audio_paths) - 1)

    def _reset_prompt(self) -> None:
        self.prompt_text.delete("1.0", "end")
        self.prompt_text.insert("end", STRUCTURE_SYSTEM_PROMPT)

    def _start(self) -> None:
        if self.running:
            return
        audio = self._selected_audio()
        if audio is None:
            messagebox.showwarning("입력 필요", "통화를 선택하세요.\n목록이 비어 있으면 [찾아보기…]로 파일을 여세요.")
            return
        if not audio.exists():
            messagebox.showerror("오류", f"파일이 없습니다:\n{audio}")
            return
        system_prompt = self.prompt_text.get("1.0", "end").strip()
        if not system_prompt:
            messagebox.showwarning(
                "입력 필요", "시스템 프롬프트가 비어 있습니다.\n[개발자 옵션] > [시스템 프롬프트] 탭에서 [기본값 복원]을 누르세요."
            )
            return

        self.running = True
        self.result = None
        self.current_stage = None
        self.started_at = time.perf_counter()
        self.run_button.configure(state="disabled")
        self.save_button.configure(state="disabled")
        for tab in self.tabs:
            self._set_tab(tab, "")
        self.brief_var.set("(처리 중…)")
        self.correction_count.set("")
        self._clear_card()
        self._set_compare("", "", [])
        self._render_stages("audio")

        params = {
            "audio_path": str(audio),
            "stt_model": self.stt_var.get(),
            "device": self.device_var.get(),
            "llm_model": self.llm_var.get(),
            "system_prompt": system_prompt,
            "use_correction": self.correction_var.get(),
            "max_ngram": int(self.ngram_var.get()),
            "do_summarize": self.summarize_var.get(),
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
                    self._set_stage(_stage_of(payload))
                elif kind == "done":
                    self._on_done(payload)
                elif kind == "error":
                    self._on_error(payload)
        except queue.Empty:
            pass

        if self.running:
            self.status_var.set(f"처리 중…  {time.perf_counter() - self.started_at:.0f}초 경과")
        self.root.after(150, self._poll_queue)

    def _on_done(self, result: dict) -> None:
        self.running = False
        self.result = result
        self.run_button.configure(state="normal")
        self.save_button.configure(state="normal")
        self._render_stages(None, done=True)

        elapsed = time.perf_counter() - self.started_at
        detail = " · ".join(
            f"{TIMING_LABELS.get(k, k)} {v}초" for k, v in result["timings"].items()
        )
        self.status_var.set(f"완료  {elapsed:.0f}초   ({detail})")
        self._append("진행 로그", f"\n전체 완료 ({elapsed:.1f}초)")

        message = result["call_summary_message"]
        self.brief_var.set(result["patient_brief"] or "(LLM 요약이 꺼져 있습니다)")
        self._fill_card(message["summary"])

        post = result["text_postprocess"]
        if post:
            count = len(post["corrections"])
            self.correction_count.set(f"교정 {count}건" if count else "교정된 구간 없음")
            self._set_compare(
                message["transcript"]["raw_text"],
                message["transcript"]["filtered_text"],
                post["corrections"],
            )
        else:
            self.correction_count.set("교정 비활성화됨")
            self._set_compare(message["transcript"]["raw_text"], "(오인식 교정이 꺼져 있습니다)", [])

        self._set_tab("결과 JSON", json.dumps(message, ensure_ascii=False, indent=2))

    def _on_error(self, error: str) -> None:
        self.running = False
        self.run_button.configure(state="normal")
        self._render_stages(None)
        self.status_var.set("오류 발생")
        self.brief_var.set("(오류로 처리하지 못했습니다)")
        self._append("진행 로그", f"\n오류: {error}")
        messagebox.showerror("오류", error)

    def _save(self) -> None:
        if not self.result:
            return
        selected = self._selected_audio()
        default_name = (selected.stem if selected else "result") + "_result.json"
        path = filedialog.asksaveasfilename(
            defaultextension=".json", initialfile=default_name, filetypes=[("JSON", "*.json")]
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
