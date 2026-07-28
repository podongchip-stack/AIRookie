import os
import queue
import threading
import tkinter as tk
from tkinter import filedialog, ttk

import yt_dlp

DEFAULT_OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")


class AudioDownloaderApp:
    def __init__(self, root):
        self.root = root
        self.root.title("유튜브 오디오 다운로더")
        self.root.geometry("560x420")

        self.event_queue = queue.Queue()
        self.worker_thread = None

        self._build_widgets()
        self.root.after(100, self._poll_queue)

    def _build_widgets(self):
        pad = {"padx": 10, "pady": 6}

        url_frame = ttk.Frame(self.root)
        url_frame.pack(fill="x", **pad)
        ttk.Label(url_frame, text="URL").pack(side="left")
        self.url_entry = ttk.Entry(url_frame)
        self.url_entry.pack(side="left", fill="x", expand=True, padx=(8, 0))

        dir_frame = ttk.Frame(self.root)
        dir_frame.pack(fill="x", **pad)
        ttk.Label(dir_frame, text="저장 폴더").pack(side="left")
        self.dir_var = tk.StringVar(value=DEFAULT_OUTPUT_DIR)
        self.dir_entry = ttk.Entry(dir_frame, textvariable=self.dir_var)
        self.dir_entry.pack(side="left", fill="x", expand=True, padx=(8, 8))
        ttk.Button(dir_frame, text="찾아보기", command=self._browse_dir).pack(side="left")

        self.download_btn = ttk.Button(self.root, text="다운로드", command=self._start_download)
        self.download_btn.pack(pady=6)

        self.progress = ttk.Progressbar(self.root, mode="determinate", maximum=100)
        self.progress.pack(fill="x", **pad)

        self.log_text = tk.Text(self.root, height=14, state="disabled")
        self.log_text.pack(fill="both", expand=True, **pad)

    def _browse_dir(self):
        chosen = filedialog.askdirectory(initialdir=self.dir_var.get() or ".")
        if chosen:
            self.dir_var.set(chosen)

    def _log(self, message):
        self.log_text.configure(state="normal")
        self.log_text.insert("end", message + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _start_download(self):
        url = self.url_entry.get().strip()
        output_dir = self.dir_var.get().strip()

        if not url:
            self._log("URL을 입력하세요.")
            return
        if self.worker_thread and self.worker_thread.is_alive():
            self._log("이미 다운로드가 진행 중입니다.")
            return

        os.makedirs(output_dir, exist_ok=True)
        self.download_btn.configure(state="disabled")
        self.progress["value"] = 0
        self._log(f"다운로드 시작: {url}")

        self.worker_thread = threading.Thread(
            target=self._download_worker, args=(url, output_dir), daemon=True
        )
        self.worker_thread.start()

    def _download_worker(self, url, output_dir):
        def progress_hook(status):
            if status["status"] == "downloading":
                total = status.get("total_bytes") or status.get("total_bytes_estimate")
                downloaded = status.get("downloaded_bytes", 0)
                percent = (downloaded / total * 100) if total else 0
                self.event_queue.put(("progress", percent))
            elif status["status"] == "finished":
                self.event_queue.put(("progress", 100))
                self.event_queue.put(("log", "다운로드 완료, 마무리 중..."))

        ydl_opts = {
            "format": "bestaudio/best",
            "outtmpl": os.path.join(output_dir, "%(title)s.%(ext)s"),
            "progress_hooks": [progress_hook],
            "quiet": True,
            "no_warnings": True,
        }

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                filename = ydl.prepare_filename(info)
            self.event_queue.put(("log", f"저장됨: {filename}"))
            self.event_queue.put(("done", None))
        except Exception as exc:
            self.event_queue.put(("log", f"오류 발생: {exc}"))
            self.event_queue.put(("done", None))

    def _poll_queue(self):
        try:
            while True:
                kind, payload = self.event_queue.get_nowait()
                if kind == "progress":
                    self.progress["value"] = payload
                elif kind == "log":
                    self._log(payload)
                elif kind == "done":
                    self.download_btn.configure(state="normal")
        except queue.Empty:
            pass
        self.root.after(100, self._poll_queue)


if __name__ == "__main__":
    root = tk.Tk()
    AudioDownloaderApp(root)
    root.mainloop()
