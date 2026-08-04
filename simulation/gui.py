"""병원 서류(PDF·이미지)를 끌어놓으면 처리 과정을 눈으로 보여주는 창.

    끌어놓기 → 페이지 렌더링 → 영역 검출·인식 → 필드 추출 → 필드 표 · 최종 JSON

CLI(`ocr/scripts/run_extract.py`)와 결과는 같다. 다른 것은 **과정이 보인다**는 점뿐이다.
어느 영역을 어떤 태스크로 읽었는지, 어떤 값이 어떤 근거로 채택·기각됐는지를
끝나고 나서가 아니라 진행 중에 본다.

화면에 AI와 규칙을 구분해 찍는다 (CLAUDE.md 핵심 AI 활용 원칙).
`[AI]`는 값을 **찾는** 단계, `[규칙]`은 그 값을 **받아들일지 정하는** 단계다.

실행:
    python simulation/gui.py
"""

from __future__ import annotations

import queue
import sys
import tkinter as tk
from collections import Counter
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageTk

sys.path.insert(0, str(Path(__file__).resolve().parent))

import ollama_service  # noqa: E402
from runner import DocumentRunner, llm_host  # noqa: E402

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
except ImportError:
    raise SystemExit(
        "tkinterdnd2가 없다 — 끌어놓기에 필요하다.\n"
        f"  {sys.executable} -m pip install tkinterdnd2"
    ) from None

FONT = ("맑은 고딕", 9)
FONT_HEAD = ("맑은 고딕", 10, "bold")
#: JSON은 들여쓰기가 줄마다 맞아야 읽힌다. 고정폭이 아니면 계층이 눈에 안 들어온다
FONT_MONO = ("Consolas", 9)

#: 영역 박스 색. 아직 안 읽음 / 읽음 / 검토 필요
STATE_COLOR = {"pending": "#9aa0a6", "done": "#2e7d32", "review": "#ef6c00"}

#: 큐를 비우는 주기(ms). 사람이 끊김을 못 느끼면서 메인 스레드를 놀리지 않는 값
POLL_MS = 50


class SimulationApp:
    def __init__(self, root: tk.Tk) -> None:
        self._root = root
        self._events: queue.Queue = queue.Queue()
        self._runner = DocumentRunner(self._events)

        self._page: Image.Image | None = None
        self._photo: ImageTk.PhotoImage | None = None
        self._regions: list[dict] = []

        root.title("골든링크 — 서류 인식 시뮬레이션")
        root.geometry("1360x900")
        self._build()
        self._refresh_ollama()

        root.drop_target_register(DND_FILES)
        root.dnd_bind("<<Drop>>", self._on_drop)
        root.after(POLL_MS, self._drain)

    # --- 화면 구성 -----------------------------------------------------------

    def _build(self) -> None:
        header = ttk.Frame(self._root, padding=(10, 8))
        header.pack(fill="x")
        ttk.Label(
            header, text="PDF 또는 이미지를 창 안에 끌어놓으세요", font=FONT_HEAD
        ).pack(side="left")
        ttk.Button(header, text="파일 선택…", command=self._choose_file).pack(side="right")

        self._dpi = tk.StringVar(value="200")
        ttk.Spinbox(
            header, from_=100, to=400, increment=50, width=5, textvariable=self._dpi
        ).pack(side="right", padx=(4, 12))
        ttk.Label(header, text="PDF 해상도(dpi)", font=FONT).pack(side="right")

        self._llm = tk.StringVar(value="ollama")
        ttk.Radiobutton(
            header, text="Stub (LLM 없이 로직만)", value="stub", variable=self._llm
        ).pack(side="right", padx=(4, 16))
        ttk.Radiobutton(
            header, text="Ollama (실제 추출)", value="ollama", variable=self._llm
        ).pack(side="right", padx=4)

        # 서버가 꺼진 걸 서류 놓고 30초 뒤에 알게 되면 늦다. 창을 열자마자 보여준다
        self._ollama_label = ttk.Label(header, text="Ollama 확인 중…", font=FONT)
        self._ollama_label.pack(side="right", padx=(12, 6))

        panes = ttk.PanedWindow(self._root, orient="horizontal")
        panes.pack(fill="both", expand=True, padx=10)

        left = ttk.Frame(panes)
        preview = ttk.LabelFrame(left, text="페이지 미리보기 — 박스를 누르면 그 영역 텍스트")
        preview.pack(fill="both", expand=True)
        self._canvas = tk.Canvas(preview, background="#f5f5f5", highlightthickness=0)
        self._canvas.pack(fill="both", expand=True)
        self._canvas.bind("<Configure>", lambda _event: self._render())

        self._region_text = tk.Text(left, height=6, font=FONT, wrap="word", state="disabled")
        self._region_text.pack(fill="x", pady=(6, 0))
        panes.add(left, weight=3)

        right = ttk.LabelFrame(panes, text="진행 — [AI] 값을 찾는다 / [규칙] 받아들일지 정한다")
        self._log_text = tk.Text(right, font=FONT, wrap="word", state="disabled", width=52)
        scroll = ttk.Scrollbar(right, orient="vertical", command=self._log_text.yview)
        self._log_text.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self._log_text.pack(side="left", fill="both", expand=True)
        for tag, color in (
            ("ai", "#1565c0"), ("rule", "#2e7d32"),
            ("warn", "#ef6c00"), ("error", "#c62828"),
        ):
            self._log_text.tag_configure(tag, foreground=color)
        self._log_text.tag_configure("head", font=FONT_HEAD)
        panes.add(right, weight=2)

        # 표와 JSON은 같은 결과를 다르게 본 것뿐이라 한 자리에 탭으로 겹쳐 둔다.
        # 표는 무엇을 왜 버렸는지 보려고, JSON은 hub로 넘어갈 형태 그대로 보려고 쓴다
        results = ttk.Notebook(self._root)
        results.pack(fill="both", expand=False, padx=10, pady=(8, 4))

        table = ttk.Frame(results)
        results.add(table, text="추출 필드 — 값은 AI가 찾고, 채택 여부는 규칙이 정한다")
        columns = ("field", "value", "evidence", "verdict")
        self._tree = ttk.Treeview(table, columns=columns, show="headings", height=9)
        for name, title, width in (
            ("field", "필드", 230), ("value", "값 (AI 제안)", 190),
            ("evidence", "근거 원문 (AI)", 430), ("verdict", "판정 (규칙)", 330),
        ):
            self._tree.heading(name, text=title)
            self._tree.column(name, width=width, anchor="w")
        tree_scroll = ttk.Scrollbar(table, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=tree_scroll.set)
        tree_scroll.pack(side="right", fill="y")
        self._tree.pack(side="left", fill="both", expand=True)
        self._tree.tag_configure("dropped", foreground="#c62828")

        json_tab = ttk.Frame(results)
        results.add(json_tab, text="최종 JSON — 저장된 파일과 같은 내용")
        json_head = ttk.Frame(json_tab)
        json_head.pack(fill="x", padx=4, pady=(4, 2))
        self._json_path = tk.StringVar(value="아직 결과가 없습니다")
        ttk.Label(json_head, textvariable=self._json_path, font=FONT).pack(side="left")
        ttk.Button(json_head, text="복사", command=self._copy_json).pack(side="right")

        self._json_text = tk.Text(
            json_tab, font=FONT_MONO, wrap="none", state="disabled", height=9
        )
        json_y = ttk.Scrollbar(json_tab, orient="vertical", command=self._json_text.yview)
        json_x = ttk.Scrollbar(json_tab, orient="horizontal", command=self._json_text.xview)
        self._json_text.configure(yscrollcommand=json_y.set, xscrollcommand=json_x.set)
        json_x.pack(side="bottom", fill="x")
        json_y.pack(side="right", fill="y")
        self._json_text.pack(side="left", fill="both", expand=True)

        self._status_var = tk.StringVar(value="대기 중 — 서류를 끌어놓으세요")
        ttk.Label(
            self._root, textvariable=self._status_var, font=FONT, relief="sunken", padding=4
        ).pack(fill="x", padx=10, pady=(0, 8))

    # --- 입력 ---------------------------------------------------------------

    def _on_drop(self, event) -> None:
        paths = [path for path in self._root.tk.splitlist(event.data) if path]
        if not paths:
            return
        if len(paths) > 1:
            self._log(f"{len(paths)}개가 들어왔다. 첫 번째만 처리한다.", tag="warn")
        self._start(paths[0])

    def _choose_file(self) -> None:
        path = filedialog.askopenfilename(
            title="서류 선택",
            filetypes=[("서류", "*.pdf *.png *.jpg *.jpeg *.tif *.tiff *.bmp"), ("모든 파일", "*.*")],
        )
        if path:
            self._start(path)

    def _start(self, path: str) -> None:
        use_llm = self._llm.get() == "ollama"
        autostart = False

        if use_llm and not self._refresh_ollama():
            answer = self._ask_ollama_off()
            if answer is None:
                self._log("취소했다.", tag="warn")
                return
            if answer:
                autostart = True
            else:
                # 화면의 선택도 실제와 맞춰준다. Ollama가 켜진 것처럼 보이면 안 된다
                use_llm = False
                self._llm.set("stub")
                self._log("Ollama 없이 Stub으로 진행한다.", tag="warn")

        started = self._runner.submit(
            path, use_llm=use_llm, dpi=int(self._dpi.get()), autostart_ollama=autostart
        )
        if not started:
            self._log("아직 처리 중이다. 끝난 뒤에 다시 놓을 것.", tag="warn")

    def _ask_ollama_off(self) -> bool | None:
        """서버가 꺼져 있을 때 어떻게 할지 묻는다. 예=켠다 / 아니오=Stub / 취소=중단."""
        return messagebox.askyesnocancel(
            "Ollama가 꺼져 있습니다",
            f"Ollama 서버({llm_host()})가 응답하지 않습니다.\n"
            f"이대로 진행하면 실제 필드 추출을 할 수 없습니다.\n\n"
            f"[예]     Ollama를 켜고 실제 추출로 진행 (실측 20여 초 걸립니다)\n"
            f"[아니오]  Stub으로 진행 — LLM 없이 OCR과 검증 로직만\n"
            f"[취소]    아무것도 하지 않음",
            parent=self._root,
        )

    def _refresh_ollama(self) -> bool:
        """서버 상태를 다시 보고 머리말 표시를 갱신한다. 켜져 있으면 True."""
        running = ollama_service.is_running(llm_host())
        self._ollama_label.configure(
            text="Ollama 켜짐" if running else "Ollama 꺼짐",
            foreground="#2e7d32" if running else "#c62828",
        )
        return running

    # --- 이벤트 소비 ---------------------------------------------------------

    def _drain(self) -> None:
        """워커가 큐에 넣어둔 것을 메인 스레드에서 화면에 옮긴다.

        위젯을 만지는 곳은 여기서 갈라져 나간 경로뿐이다. 워커 스레드는 큐에
        넣기만 한다 — Tk는 다른 스레드에서 건드리면 조용히 깨진다.
        """
        try:
            while True:
                self._handle(self._events.get_nowait())
        except queue.Empty:
            pass
        self._root.after(POLL_MS, self._drain)

    def _handle(self, event: dict) -> None:
        stage = event["stage"]

        if stage == "job_start":
            self._reset()
            kind = "PDF" if event["kind"] == "pdf" else "이미지"
            self._log(f"── {event['name']} ({kind} {event['pages']}장)", tag="head")

        elif stage == "loading":
            if event["what"] == "ollama":
                self._status("Ollama 서버 켜는 중…")
                self._log(f"Ollama 서버 켜는 중… ({event['host']})", tag="warn")
            else:
                what = (
                    "OCR 모델(레이아웃 + 인식)" if event["what"] == "ocr"
                    else f"LLM {event.get('model', '')}"
                )
                self._status(f"{what} 로드 중…")
                self._log(f"{what} 로드 중…")
                self._refresh_ollama()

        elif stage == "page_start":
            self._page, self._regions = event["image"], []
            self._render()
            self._status(f"{event['page']}/{event['pages']} 페이지 처리 중")
            self._log(
                f"[{event['page']}/{event['pages']}] 페이지 "
                f"{event['image'].width}×{event['image'].height}px",
                tag="head",
            )

        elif stage == "detect":
            self._log(f"레이아웃 검출 — 영역 {event['count']}개", source="ai")

        elif stage == "route":
            self._regions = [dict(region, state="pending", text="") for region in event["regions"]]
            self._render()
            tasks = Counter(region["task"].rstrip(":") for region in event["regions"])
            detail = ", ".join(f"{task} {count}" for task, count in tasks.items())
            self._log(f"정리·라우팅 — {len(self._regions)}개 ({detail})", source="rule")

        elif stage == "recognize":
            region, index = event["region"], event["index"]
            if index < len(self._regions):
                self._regions[index].update(
                    state="review" if region["needs_review"] else "done",
                    text=region["text"],
                )
                self._render()
            head = (region["text"] or "(빈 결과)").replace("\n", " ")[:44]
            self._log(
                f"인식 {index + 1}/{event['total']} · {region['cls']} — {head}", source="ai"
            )
            if region["needs_review"]:
                self._log(f"    검토 필요: {', '.join(region['review_reasons'])}", tag="warn")

        elif stage == "ocr_done":
            result = event["result"]
            self._log(
                f"OCR 완료 — {len(result['text'])}자 / 영역 {len(result['regions'])}개"
                f"{' / 검토 필요' if result['needs_review'] else ''}",
                tag="warn" if result["needs_review"] else "",
            )

        elif stage == "group_start":
            self._status(f"필드 추출 {event['index'] + 1}/{event['total']} — {event['label']}")
            self._log(
                f"필드 추출 {event['index'] + 1}/{event['total']} · {event['label']} — LLM 호출",
                source="ai",
            )

        elif stage == "group_done":
            taken = sum(1 for item in event["evidence"] if item.grounded)
            dropped = len(event["evidence"]) - taken
            self._log(
                f"근거 대조 · {event['label']} — 채택 {taken}, 버림 {dropped}", source="rule"
            )
            for reason in event["reasons"]:
                self._log(f"    {reason}", tag="warn")

        elif stage == "group_failed":
            self._log(f"'{event['label']}' 실패 — {event['error']}", tag="error")

        elif stage == "page_done":
            self._fill_table(event["fields"])
            self._show_json(event["fields"], event["path"])
            fields = event["fields"]
            self._log(f"저장 — {event['path'].name}", tag="head")
            self._log(f"    채택된 필드: {', '.join(fields.filled_fields()) or '없음'}")
            if fields.needsReview:
                self._log(f"    사람 확인 필요 ({len(fields.reviewReasons)}건)", tag="warn")

        elif stage == "job_done":
            self._status(f"완료 — {event['pages']}장 처리")
            self._log("완료", tag="head")
            self._refresh_ollama()

        elif stage == "error":
            self._status("오류로 중단됨")
            self._refresh_ollama()
            self._log(event["message"], tag="error")
            if event.get("detail"):
                self._log(event["detail"], tag="error")

    # --- 그리기 -------------------------------------------------------------

    def _render(self) -> None:
        """페이지와 영역 박스를 다시 그린다.

        창 크기가 바뀔 때마다 통째로 다시 그린다. 배율이 달라지면 박스 좌표도
        전부 달라지므로 부분 갱신이 오히려 어긋나기 쉽다.
        """
        canvas = self._canvas
        canvas.delete("all")

        width, height = canvas.winfo_width(), canvas.winfo_height()
        if self._page is None:
            canvas.create_text(
                width // 2, height // 2, text="여기에 서류를 끌어놓으세요",
                font=FONT_HEAD, fill="#9aa0a6",
            )
            return
        if width < 50 or height < 50:  # 아직 배치 전이면 크기를 못 구한다
            return

        scale = min(width / self._page.width, height / self._page.height)
        size = (max(int(self._page.width * scale), 1), max(int(self._page.height * scale), 1))
        self._photo = ImageTk.PhotoImage(self._page.resize(size, Image.LANCZOS))
        left, top = (width - size[0]) // 2, (height - size[1]) // 2
        canvas.create_image(left, top, anchor="nw", image=self._photo)

        for index, region in enumerate(self._regions):
            x0, y0, x1, y1 = region["xyxy"]
            box = canvas.create_rectangle(
                left + x0 * scale, top + y0 * scale, left + x1 * scale, top + y1 * scale,
                outline=STATE_COLOR[region["state"]], width=2,
            )
            label = canvas.create_text(
                left + x0 * scale + 10, top + y0 * scale + 8,
                text=str(index + 1), font=FONT_HEAD, fill=STATE_COLOR[region["state"]],
            )
            for item in (box, label):
                canvas.tag_bind(item, "<Button-1>", lambda _event, i=index: self._show_region(i))

    def _show_region(self, index: int) -> None:
        region = self._regions[index]
        body = region["text"] or "(아직 읽지 않았거나 빈 결과)"
        self._set_text(
            self._region_text,
            f"{index + 1}번 영역 · {region['cls']} · {region['task'].rstrip(':')}\n{body}",
        )

    def _fill_table(self, fields) -> None:
        """근거 하나를 한 줄로 놓는다. **버려진 값도 남긴다.**

        무엇을 뽑았는지보다 무엇을 왜 버렸는지가 중요하다 — 환각 필터가 실제로
        걸러내고 있는지를 이 표에서 확인한다.
        """
        self._tree.delete(*self._tree.get_children())

        # 서류 종류는 enum으로 제약돼 근거 대조를 하지 않는다. 표에서 빠지면
        # 안 뽑힌 것처럼 보이므로 따로 넣는다
        if fields.documentType:
            self._tree.insert(
                "", "end",
                values=("documentType", fields.documentType, "— (서류 전체로 판단)", "어휘 enum 통과"),
            )

        for item in fields.evidence:
            verdict = "채택" if item.grounded else f"버림 — {item.groundReason}"
            self._tree.insert(
                "", "end",
                values=(item.field, item.value, item.sourceText.replace("\n", " "), verdict),
                tags=() if item.grounded else ("dropped",),
            )

    def _show_json(self, fields, path: Path) -> None:
        """저장된 결과를 그대로 보여준다.

        디스크의 파일을 다시 읽지 않고 방금 쓴 것과 같은 객체에서 만든다. 파일을
        읽어오면 화면과 파일이 어긋날 여지가 생기는데, 어차피 같은 `to_json()`이
        양쪽에 쓰였으므로 읽을 이유가 없다.
        """
        self._set_text(self._json_text, fields.to_json())
        self._json_path.set(f"저장 위치: {path}")

    def _copy_json(self) -> None:
        body = self._json_text.get("1.0", "end").strip()
        if not body:
            self._log("복사할 결과가 아직 없다.", tag="warn")
            return
        self._root.clipboard_clear()
        self._root.clipboard_append(body)
        self._log(f"최종 JSON {len(body)}자를 클립보드에 복사했다.")

    # --- 잡다 ---------------------------------------------------------------

    def _reset(self) -> None:
        self._page, self._regions = None, []
        self._render()
        self._tree.delete(*self._tree.get_children())
        self._set_text(self._region_text, "")
        self._set_text(self._log_text, "")
        self._set_text(self._json_text, "")
        self._json_path.set("아직 결과가 없습니다")

    def _log(self, message: str, *, source: str | None = None, tag: str = "") -> None:
        badge = {"ai": "[AI]   ", "rule": "[규칙] "}.get(source, "       ")
        self._log_text.configure(state="normal")
        if source:
            self._log_text.insert("end", badge, source)
        else:
            self._log_text.insert("end", badge)
        self._log_text.insert("end", message + "\n", tag)
        self._log_text.see("end")
        self._log_text.configure(state="disabled")

    def _status(self, message: str) -> None:
        self._status_var.set(message)

    @staticmethod
    def _set_text(widget: tk.Text, body: str) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", body)
        widget.configure(state="disabled")


def main() -> int:
    root = TkinterDnD.Tk()
    SimulationApp(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
