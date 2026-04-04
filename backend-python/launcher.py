#!/usr/bin/env python3
"""
NewFinder 제어판
실행: python launcher.py
"""

import re
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from tkinter import font as tkfont
from tkinter import scrolledtext
import tkinter as tk

BASE_DIR = Path(__file__).parent
PORT = 8000


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("NewFinder 제어판")
        self.root.geometry("760x580")
        self.root.configure(bg="#0f1117")
        self.root.resizable(True, True)

        self._server_proc: subprocess.Popen | None = None
        self._build_ui()
        self._set_status(False)

    # ── UI 구성 ───────────────────────────────────────────────────────────────

    def _build_ui(self):
        # ── 헤더
        hdr = tk.Frame(self.root, bg="#1a1d2e", pady=14)
        hdr.pack(fill="x")

        tk.Label(hdr, text="NewFinder", font=("Arial", 18, "bold"),
                 bg="#1a1d2e", fg="#6366f1").pack(side="left", padx=20)
        tk.Label(hdr, text="뉴스 크롤러 제어판", font=("Arial", 11),
                 bg="#1a1d2e", fg="#64748b").pack(side="left")

        # ── 상태 표시줄
        sf = tk.Frame(self.root, bg="#252840", pady=9)
        sf.pack(fill="x")

        self._dot = tk.Label(sf, text="●", font=("Arial", 16),
                              bg="#252840", fg="#ef4444")
        self._dot.pack(side="left", padx=(16, 5))

        self._status_lbl = tk.Label(sf, text="서버 중단됨",
                                     font=("Arial", 10, "bold"),
                                     bg="#252840", fg="#94a3b8")
        self._status_lbl.pack(side="left")

        self._url_lbl = tk.Label(sf, text="",
                                  font=("Arial", 10, "underline"),
                                  bg="#252840", fg="#6366f1", cursor="hand2")
        self._url_lbl.pack(side="left", padx=10)
        self._url_lbl.bind("<Button-1>", lambda _: self._open_browser())

        # ── 버튼 행
        bf = tk.Frame(self.root, bg="#0f1117", pady=14)
        bf.pack(fill="x", padx=18)

        btn_cfg = dict(font=("Arial", 11, "bold"), relief="flat",
                       padx=18, pady=10, cursor="hand2", bd=0)

        self._btn_start = tk.Button(
            bf, text="▶  서버 시작",
            bg="#22c55e", fg="white", activebackground="#16a34a",
            command=self.start_server, **btn_cfg)
        self._btn_start.pack(side="left", padx=(0, 8))

        self._btn_stop = tk.Button(
            bf, text="■  서버 중단",
            bg="#ef4444", fg="white", activebackground="#dc2626",
            command=self.stop_server, **btn_cfg)
        self._btn_stop.pack(side="left", padx=(0, 8))

        self._btn_crawl = tk.Button(
            bf, text="⟳  크롤링 실행",
            bg="#6366f1", fg="white", activebackground="#4f46e5",
            command=self.run_crawl, **btn_cfg)
        self._btn_crawl.pack(side="left", padx=(0, 8))

        tk.Button(bf, text="🌐  브라우저",
                  bg="#0ea5e9", fg="white", activebackground="#0284c7",
                  command=self._open_browser, **btn_cfg).pack(side="left")

        tk.Button(bf, text="로그 지우기",
                  bg="#2d3148", fg="#94a3b8", activebackground="#3d4166",
                  command=self._clear_log,
                  font=("Arial", 9), relief="flat", padx=10, pady=10,
                  cursor="hand2").pack(side="right")

        # ── 로그 영역
        tk.Label(self.root, text="  로그", font=("Arial", 9, "bold"),
                 bg="#0f1117", fg="#475569").pack(anchor="w")

        self._log = scrolledtext.ScrolledText(
            self.root,
            bg="#090c14", fg="#94a3b8",
            insertbackground="#e2e8f0",
            font=("Consolas", 9),
            relief="flat", bd=0, wrap="word",
        )
        self._log.pack(fill="both", expand=True, padx=18, pady=(2, 18))
        self._log.configure(state="disabled")

        # 색상 태그 정의
        for tag, color in [
            ("green",  "#22c55e"),
            ("red",    "#ef4444"),
            ("yellow", "#f59e0b"),
            ("purple", "#a78bfa"),
            ("gray",   "#475569"),
        ]:
            self._log.tag_config(tag, foreground=color)

    # ── 상태 업데이트 ──────────────────────────────────────────────────────────

    def _set_status(self, running: bool):
        if running:
            self._dot.config(fg="#22c55e")
            self._status_lbl.config(text="서버 실행 중", fg="#22c55e")
            self._url_lbl.config(text=f"http://localhost:{PORT}")
            self._btn_start.config(state="disabled")
            self._btn_stop.config(state="normal")
        else:
            self._dot.config(fg="#ef4444")
            self._status_lbl.config(text="서버 중단됨", fg="#94a3b8")
            self._url_lbl.config(text="")
            self._btn_start.config(state="normal")
            self._btn_stop.config(state="disabled")

    # ── 로그 출력 ─────────────────────────────────────────────────────────────

    def _log_write(self, msg: str, tag: str = ""):
        def _do():
            self._log.configure(state="normal")
            ts   = time.strftime("%H:%M:%S")
            line = f"[{ts}] {msg}\n"
            self._log.insert("end", line, tag or "")
            self._log.see("end")
            self._log.configure(state="disabled")
        self.root.after(0, _do)

    def _clear_log(self):
        self._log.configure(state="normal")
        self._log.delete("1.0", "end")
        self._log.configure(state="disabled")

    def _strip_ansi(self, s: str) -> str:
        return re.sub(r"\x1b\[[0-9;]*m", "", s)

    # ── 서버 시작 ─────────────────────────────────────────────────────────────

    def start_server(self):
        if self._server_proc and self._server_proc.poll() is None:
            return

        self._log_write("서버 시작 중...", "green")
        self.root.after(0, lambda: self._set_status(True))

        def _run():
            try:
                self._server_proc = subprocess.Popen(
                    [sys.executable, "-m", "uvicorn", "main:app",
                     "--host", "0.0.0.0", "--port", str(PORT), "--reload"],
                    cwd=str(BASE_DIR),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True, encoding="utf-8", errors="ignore",
                    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
                    if sys.platform == "win32" else 0,
                )
                for line in self._server_proc.stdout:
                    line = self._strip_ansi(line.rstrip())
                    if not line:
                        continue
                    tag = "gray"
                    if "ERROR" in line or "error" in line.lower():
                        tag = "red"
                    elif "CRON" in line:
                        tag = "purple"
                    elif "complete" in line.lower() or "완료" in line:
                        tag = "green"
                    self._log_write(line, tag)

                self._server_proc.wait()
                self.root.after(0, lambda: self._set_status(False))
                self._log_write("서버가 중단됐습니다.", "red")

            except Exception as e:
                self._log_write(f"서버 오류: {e}", "red")
                self.root.after(0, lambda: self._set_status(False))

        threading.Thread(target=_run, daemon=True).start()
        self.root.after(2500, self._open_browser)

    # ── 서버 중단 ─────────────────────────────────────────────────────────────

    def stop_server(self):
        if not self._server_proc:
            return
        self._log_write("서버 중단 중...", "yellow")
        try:
            if sys.platform == "win32":
                self._server_proc.send_signal(signal.CTRL_BREAK_EVENT)
            else:
                self._server_proc.terminate()
            self._server_proc.wait(timeout=6)
        except Exception:
            self._server_proc.kill()
        self._server_proc = None
        self._set_status(False)
        self._log_write("서버가 중단됐습니다.", "red")

    # ── 크롤링 실행 ───────────────────────────────────────────────────────────

    def run_crawl(self):
        self._log_write("크롤링 시작...", "purple")
        self._btn_crawl.config(state="disabled", text="⟳  크롤링 중...")

        def _run():
            try:
                proc = subprocess.Popen(
                    [sys.executable, "crawler.py"],
                    cwd=str(BASE_DIR),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True, encoding="utf-8", errors="ignore",
                )
                for line in proc.stdout:
                    line = line.rstrip()
                    if not line:
                        continue
                    tag = "green" if ("신규" in line or "수집" in line) else ""
                    tag = "red"   if "ERROR" in line else tag
                    self._log_write(line, tag)
                proc.wait()
                self._log_write("크롤링 완료!", "green")
            except Exception as e:
                self._log_write(f"크롤링 오류: {e}", "red")
            finally:
                self.root.after(0, lambda: self._btn_crawl.config(
                    state="normal", text="⟳  크롤링 실행"))

        threading.Thread(target=_run, daemon=True).start()

    # ── 브라우저 열기 ─────────────────────────────────────────────────────────

    def _open_browser(self):
        import webbrowser
        webbrowser.open(f"http://localhost:{PORT}")

    # ── 종료 ─────────────────────────────────────────────────────────────────

    def on_close(self):
        self.stop_server()
        self.root.destroy()


def main():
    root = tk.Tk()
    app  = App(root)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()


if __name__ == "__main__":
    main()
