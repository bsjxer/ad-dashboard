# -*- coding: utf-8 -*-
"""
원고 뽑기 (GUI)
영상 파일이나 링크를 넣으면 한국어 음성을 텍스트로 변환하고 2~5줄로 요약합니다.
- 파일을 창에 드래그&드롭 가능
- 유튜브 봇 차단 시 cookies.txt 자동 인식 / [쿠키 파일] 버튼으로 지정
실행:  python app.py
"""
import os
import threading
import traceback
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext

import core

# 드래그&드롭 지원 (없으면 자동으로 비활성화)
try:
    from tkinterdnd2 import TkinterDnD, DND_FILES
    _DND = True
except Exception:
    _DND = False

VIDEO_TYPES = [
    ("영상/음성 파일", "*.mp4 *.mkv *.mov *.avi *.wmv *.flv *.webm *.m4a *.mp3 *.wav *.aac"),
    ("모든 파일", "*.*"),
]


class App:
    def __init__(self, root):
        self.root = root
        root.title("원고 뽑기 - 영상 음성 → 텍스트 + 요약")
        root.geometry("880x720")
        root.minsize(720, 560)
        self.cookies_path = None

        pad = {"padx": 10, "pady": 6}

        # --- 입력 영역 ---
        top = ttk.Frame(root)
        top.pack(fill="x", **pad)
        ttk.Label(top, text="영상 파일 또는 링크(URL):").pack(anchor="w")

        row = ttk.Frame(top)
        row.pack(fill="x", pady=(4, 0))
        self.src_var = tk.StringVar()
        self.entry = ttk.Entry(row, textvariable=self.src_var)
        self.entry.pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="파일 선택", command=self.pick_file).pack(side="left", padx=(6, 0))

        # --- 드래그&드롭 영역 ---
        dnd_text = "⬇  여기로 영상 파일을 끌어다 놓으세요  (드래그 & 드롭)"
        if not _DND:
            dnd_text = "파일 선택 버튼을 사용하세요  (드래그&드롭 라이브러리 미설치)"
        self.drop = tk.Label(
            root, text=dnd_text, height=3, relief="ridge", bd=2,
            bg="#f2f6ff", fg="#3355aa", font=("Malgun Gothic", 11, "bold"),
        )
        self.drop.pack(fill="x", padx=10, pady=(0, 6))
        if _DND:
            self.drop.drop_target_register(DND_FILES)
            self.drop.dnd_bind("<<Drop>>", self.on_drop)
            # 창 전체에도 드롭 허용
            root.drop_target_register(DND_FILES)
            root.dnd_bind("<<Drop>>", self.on_drop)

        # --- 옵션 영역 ---
        opt = ttk.Frame(root)
        opt.pack(fill="x", **pad)
        ttk.Label(opt, text="정확도(모델):").pack(side="left")
        self.model_var = tk.StringVar(value="small")
        ttk.Combobox(
            opt, textvariable=self.model_var, width=10, state="readonly",
            values=["tiny", "base", "small", "medium", "large-v3"],
        ).pack(side="left", padx=(4, 16))

        ttk.Label(opt, text="요약 줄 수:").pack(side="left")
        self.lines_var = tk.IntVar(value=4)
        ttk.Spinbox(opt, from_=2, to=5, width=5, textvariable=self.lines_var).pack(side="left", padx=(4, 16))

        ttk.Button(opt, text="쿠키 자동감지", command=self.auto_cookies).pack(side="left")
        ttk.Button(opt, text="쿠키 파일", command=self.pick_cookies).pack(side="left", padx=(4, 0))
        self.start_btn = ttk.Button(opt, text="변환 시작", command=self.start)
        self.start_btn.pack(side="left", padx=(8, 0))

        # 쿠키 자동 감지 표시
        auto = core.find_cookies_file()
        if auto:
            self.cookies_path = auto
        self.cookie_lbl = tk.StringVar(value=self._cookie_text())
        ttk.Label(root, textvariable=self.cookie_lbl, foreground="#888").pack(anchor="w", padx=10)

        # --- 상태 표시 ---
        self.status = tk.StringVar(value="대기 중 · 파일을 끌어놓거나 링크를 붙여넣고 [변환 시작]을 누르세요.")
        ttk.Label(root, textvariable=self.status, foreground="#1a6").pack(anchor="w", padx=10)
        self.bar = ttk.Progressbar(root, mode="indeterminate")
        self.bar.pack(fill="x", padx=10, pady=(2, 6))

        # --- 요약 ---
        ttk.Label(root, text="📌 요약 (핵심 2~5줄)").pack(anchor="w", padx=10)
        self.summary_box = scrolledtext.ScrolledText(root, height=7, wrap="word", font=("Malgun Gothic", 11))
        self.summary_box.pack(fill="x", padx=10, pady=(2, 8))

        # --- 전체 원고 ---
        ttk.Label(root, text="📝 전체 원고(받아쓰기)").pack(anchor="w", padx=10)
        self.text_box = scrolledtext.ScrolledText(root, height=14, wrap="word", font=("Malgun Gothic", 11))
        self.text_box.pack(fill="both", expand=True, padx=10, pady=(2, 8))

        # --- 저장 ---
        bottom = ttk.Frame(root)
        bottom.pack(fill="x", padx=10, pady=(0, 10))
        ttk.Button(bottom, text="결과 저장(.txt)", command=self.save).pack(side="left")
        ttk.Button(bottom, text="원고 복사", command=lambda: self.copy(self.text_box)).pack(side="left", padx=6)
        ttk.Button(bottom, text="요약 복사", command=lambda: self.copy(self.summary_box)).pack(side="left")

        self.busy = False

    # ------------------------------------------------------------------
    def _cookie_text(self):
        if self.cookies_path:
            return f"쿠키 파일: {os.path.basename(self.cookies_path)} (유튜브 다운로드에 사용)"
        return "쿠키 파일: 없음 (유튜브가 막히면 [쿠키 파일]로 cookies.txt 지정)"

    def on_drop(self, event):
        # event.data 는 "{경로1} {경로2}" 형태일 수 있음
        data = event.data.strip()
        if data.startswith("{") and data.endswith("}"):
            data = data[1:-1]
        # 여러 개면 첫 번째만
        path = data.split("} {")[0].strip("{}").strip()
        self.src_var.set(path)
        self.set_status(f"파일 선택됨: {os.path.basename(path)}")

    def pick_file(self):
        path = filedialog.askopenfilename(title="영상/음성 파일 선택", filetypes=VIDEO_TYPES)
        if path:
            self.src_var.set(path)

    def pick_cookies(self):
        path = filedialog.askopenfilename(
            title="cookies.txt 선택", filetypes=[("쿠키 파일", "*.txt"), ("모든 파일", "*.*")]
        )
        if path:
            self.cookies_path = path
            self.cookie_lbl.set(self._cookie_text())

    def auto_cookies(self):
        """다운로드/바탕화면에서 방금 내보낸 cookies.txt 를 자동으로 찾아온다."""
        found = core.find_cookies_file()
        if found:
            self.cookies_path = found
            self.cookie_lbl.set(self._cookie_text())
            messagebox.showinfo("쿠키 자동감지", f"쿠키 파일을 찾았습니다:\n{found}\n\n이제 유튜브 링크로 [변환 시작] 하세요.")
        else:
            messagebox.showwarning(
                "쿠키 자동감지",
                "쿠키 파일을 찾지 못했습니다.\n\n"
                "확장프로그램(Get cookies.txt LOCALLY)에서\n"
                "유튜브에 로그인한 채로 cookies.txt 를 내보낸 뒤\n"
                "다시 이 버튼을 눌러 주세요.\n"
                "(보통 '다운로드' 폴더에 저장됩니다.)",
            )

    def set_status(self, msg):
        self.root.after(0, lambda: self.status.set(msg))

    def start(self):
        if self.busy:
            return
        src = self.src_var.get().strip()
        if not src:
            messagebox.showwarning("입력 필요", "영상 파일을 끌어놓거나 링크를 붙여넣어 주세요.")
            return

        self.busy = True
        self.start_btn.config(state="disabled")
        self.summary_box.delete("1.0", "end")
        self.text_box.delete("1.0", "end")
        self.bar.start(12)

        t = threading.Thread(target=self._work, args=(src,), daemon=True)
        t.start()

    def _work(self, src):
        try:
            transcript, summary = core.run(
                src,
                model_size=self.model_var.get(),
                max_lines=self.lines_var.get(),
                progress=self.set_status,
                cookies_file=self.cookies_path,
            )
            self.root.after(0, lambda: self._done(transcript, summary))
        except Exception as e:
            traceback.print_exc()
            err = str(e)
            self.root.after(0, lambda: self._fail(err))

    def _done(self, transcript, summary):
        self.summary_box.insert("1.0", summary)
        self.text_box.insert("1.0", transcript)
        self.set_status("완료 ✅")
        self._reset()

    def _fail(self, err):
        self.set_status("오류 발생 ❌")
        messagebox.showerror("오류", err)
        self._reset()

    def _reset(self):
        self.bar.stop()
        self.start_btn.config(state="normal")
        self.busy = False

    def save(self):
        transcript = self.text_box.get("1.0", "end").strip()
        summary = self.summary_box.get("1.0", "end").strip()
        if not transcript and not summary:
            messagebox.showinfo("저장", "저장할 내용이 없습니다.")
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".txt", filetypes=[("텍스트 파일", "*.txt")], title="결과 저장"
        )
        if not path:
            return
        with open(path, "w", encoding="utf-8") as f:
            f.write("[요약]\n" + summary + "\n\n[전체 원고]\n" + transcript + "\n")
        messagebox.showinfo("저장 완료", f"저장했습니다:\n{path}")

    def copy(self, box):
        txt = box.get("1.0", "end").strip()
        if txt:
            self.root.clipboard_clear()
            self.root.clipboard_append(txt)
            self.set_status("클립보드에 복사했습니다.")


def main():
    root = TkinterDnD.Tk() if _DND else tk.Tk()
    try:
        ttk.Style().theme_use("vista")
    except Exception:
        pass
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
