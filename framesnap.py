"""
FrameSnap – 화면 영역 녹화 & 프레임 추출기
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import threading
import time
import os
import sys
import numpy as np
from PIL import Image, ImageTk

try:
    import mss
    MSS_AVAILABLE = True
except ImportError:
    MSS_AVAILABLE = False


# ──────────────────────────────────────────────────────────────
# 영역 선택 오버레이
# ──────────────────────────────────────────────────────────────
class RegionSelector:
    def __init__(self, callback):
        self.callback = callback
        self.win = tk.Toplevel()
        self.win.attributes('-fullscreen', True)
        self.win.attributes('-alpha', 0.25)
        self.win.attributes('-topmost', True)
        self.win.configure(bg='black')
        self.win.lift()
        self.win.focus_force()

        self.canvas = tk.Canvas(self.win, cursor='cross', bg='black', highlightthickness=0)
        self.canvas.pack(fill='both', expand=True)

        tk.Label(self.win,
                 text='마우스를 드래그하여 녹화 영역을 선택하세요   [ ESC = 취소 ]',
                 bg='black', fg='white', font=('맑은 고딕', 13)).place(relx=0.5, rely=0.04, anchor='center')

        self.sx = self.sy = 0
        self.rect = None

        self.canvas.bind('<ButtonPress-1>', self._press)
        self.canvas.bind('<B1-Motion>', self._drag)
        self.canvas.bind('<ButtonRelease-1>', self._release)
        self.win.bind('<Escape>', lambda e: self._cancel())

    def _press(self, e):
        self.sx, self.sy = e.x, e.y
        self.rect = self.canvas.create_rectangle(e.x, e.y, e.x, e.y,
                                                  outline='#00FFB3', width=2, dash=(5, 3))

    def _drag(self, e):
        self.canvas.coords(self.rect, self.sx, self.sy, e.x, e.y)

    def _release(self, e):
        x1, y1 = min(self.sx, e.x), min(self.sy, e.y)
        x2, y2 = max(self.sx, e.x), max(self.sy, e.y)
        self.win.destroy()
        if x2 - x1 > 20 and y2 - y1 > 20:
            self.callback({'top': y1, 'left': x1, 'width': x2 - x1, 'height': y2 - y1})
        else:
            self.callback(None)

    def _cancel(self):
        self.win.destroy()
        self.callback(None)


# ──────────────────────────────────────────────────────────────
# 녹화 엔진
# ──────────────────────────────────────────────────────────────
class Recorder:
    def __init__(self, region: dict, fps: int, on_frame):
        self.region = region
        self.fps = fps
        self.on_frame = on_frame
        self.running = False
        self._thread = None

    def start(self):
        self.running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self.running = False

    def _loop(self):
        interval = 1.0 / self.fps
        idx = 0
        with mss.mss() as sct:
            while self.running:
                t0 = time.perf_counter()
                raw = sct.grab(self.region)
                arr = np.frombuffer(raw.raw, dtype=np.uint8).reshape(raw.height, raw.width, 4)
                rgb = arr[:, :, [2, 1, 0]]   # BGRA → RGB
                self.on_frame(rgb, idx)
                idx += 1
                wait = interval - (time.perf_counter() - t0)
                if wait > 0:
                    time.sleep(wait)


# ──────────────────────────────────────────────────────────────
# 메인 GUI
# ──────────────────────────────────────────────────────────────
class App:
    THUMB_W = 192
    THUMB_H = 120
    COLS    = 4

    # 색상 테마
    BG      = '#0e0e14'
    PANEL   = '#18181f'
    CARD    = '#1f1f29'
    ACCENT  = '#00FFB3'
    RED     = '#FF4E6A'
    TEXT    = '#e4e4f0'
    MUTED   = '#5a5a72'
    SEL_HL  = '#00FFB3'
    DESEL   = '#2e2e3e'

    def __init__(self):
        self.root = tk.Tk()
        self.root.title('FrameSnap')
        self.root.geometry('900x700')
        self.root.minsize(700, 500)
        self.root.configure(bg=self.BG)

        # 상태
        self.recorder: Recorder | None = None
        self.region: dict | None = None
        self.fps_var    = tk.IntVar(value=5)
        self.frames: list[np.ndarray] = []
        self.selected: set[int]       = set()
        self._thumb_refs              = []   # GC 방지
        self._cells: list[tk.Frame]   = []

        self._build()

        if not MSS_AVAILABLE:
            messagebox.showerror('패키지 누락',
                'mss 패키지가 필요합니다.\n\n'
                '아래 명령어를 실행하세요:\n\n'
                '  pip install mss\n\n그 후 다시 실행하세요.')

    # ── 레이아웃 ───────────────────────────────────────────────
    def _build(self):
        self._build_topbar()
        self._build_statusbar()
        self._build_gallery()
        self._build_bottombar()

    def _btn(self, parent, text, cmd, bg=None, fg=None, state='normal', **kw):
        bg = bg or self.CARD
        fg = fg or self.TEXT
        return tk.Button(parent, text=text, command=cmd, bg=bg, fg=fg,
                         relief='flat', activebackground=bg, activeforeground=fg,
                         font=('맑은 고딕', 9, 'bold'), padx=12, pady=6,
                         cursor='hand2', state=state, bd=0, **kw)

    def _build_topbar(self):
        bar = tk.Frame(self.root, bg=self.PANEL, height=64)
        bar.pack(fill='x')
        bar.pack_propagate(False)

        tk.Label(bar, text='⬛ FrameSnap', bg=self.PANEL, fg=self.ACCENT,
                 font=('Consolas', 15, 'bold')).pack(side='left', padx=18)

        # FPS
        fps_f = tk.Frame(bar, bg=self.PANEL)
        fps_f.pack(side='left', padx=8)
        tk.Label(fps_f, text='FPS', bg=self.PANEL, fg=self.MUTED,
                 font=('Consolas', 9)).pack(side='left')
        tk.Spinbox(fps_f, from_=1, to=30, textvariable=self.fps_var, width=3,
                   bg='#252530', fg=self.TEXT, insertbackground=self.TEXT,
                   relief='flat', font=('Consolas', 12), justify='center',
                   buttonbackground='#252530').pack(side='left', padx=6)

        # 버튼
        self.btn_stop = self._btn(bar, '⏹  중지', self.stop_recording,
                                   bg=self.RED, fg='white', state='disabled')
        self.btn_stop.pack(side='right', padx=10, pady=14)

        self.btn_start = self._btn(bar, '⏺  영역 선택 후 녹화', self.start_recording,
                                    bg=self.ACCENT, fg=self.BG)
        self.btn_start.pack(side='right', padx=4, pady=14)

        self._btn(bar, '🗑  초기화', self.clear_all).pack(side='right', padx=4, pady=14)

    def _build_statusbar(self):
        bar = tk.Frame(self.root, bg='#111118', height=28)
        bar.pack(fill='x')
        bar.pack_propagate(False)

        self.status_var      = tk.StringVar(value='준비됨  –  영역 선택 후 녹화 버튼을 누르세요')
        self.frame_count_var = tk.StringVar(value='프레임 0')

        tk.Label(bar, textvariable=self.status_var, bg='#111118', fg=self.MUTED,
                 font=('Consolas', 8)).pack(side='left', padx=12)
        tk.Label(bar, textvariable=self.frame_count_var, bg='#111118', fg=self.ACCENT,
                 font=('Consolas', 8, 'bold')).pack(side='right', padx=12)

    def _build_gallery(self):
        wrap = tk.Frame(self.root, bg=self.BG)
        wrap.pack(fill='both', expand=True)

        self.gcanvas = tk.Canvas(wrap, bg=self.BG, highlightthickness=0)
        vsb = ttk.Scrollbar(wrap, orient='vertical', command=self.gcanvas.yview)
        self.gcanvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side='right', fill='y')
        self.gcanvas.pack(fill='both', expand=True)

        self.gallery = tk.Frame(self.gcanvas, bg=self.BG)
        self._gwin = self.gcanvas.create_window((0, 0), window=self.gallery, anchor='nw')

        self.gallery.bind('<Configure>',
                          lambda e: self.gcanvas.configure(scrollregion=self.gcanvas.bbox('all')))
        self.gcanvas.bind('<Configure>',
                          lambda e: self.gcanvas.itemconfig(self._gwin, width=e.width))
        self.gcanvas.bind_all('<MouseWheel>',
                              lambda e: self.gcanvas.yview_scroll(int(-e.delta / 120), 'units'))

        # 빈 안내 레이블
        self.empty_label = tk.Label(self.gallery,
                                     text='녹화를 시작하면 여기에\n프레임 썸네일이 나타납니다.',
                                     bg=self.BG, fg=self.MUTED,
                                     font=('맑은 고딕', 12))
        self.empty_label.grid(row=0, column=0, columnspan=self.COLS, pady=80)

    def _build_bottombar(self):
        bar = tk.Frame(self.root, bg=self.PANEL, height=52)
        bar.pack(fill='x')
        bar.pack_propagate(False)

        self.sel_var = tk.StringVar(value='선택된 프레임: 0개')
        tk.Label(bar, textvariable=self.sel_var, bg=self.PANEL, fg=self.MUTED,
                 font=('맑은 고딕', 9)).pack(side='left', padx=16, pady=14)

        self._btn(bar, '전체 선택', self.select_all).pack(side='left', padx=4, pady=12)
        self._btn(bar, '선택 해제', self.deselect_all).pack(side='left', padx=4, pady=12)

        self._btn(bar, '💾  선택한 프레임 PNG 저장', self.save_selected,
                  bg=self.ACCENT, fg=self.BG).pack(side='right', padx=16, pady=10)

    # ── 녹화 ───────────────────────────────────────────────────
    def start_recording(self):
        if not MSS_AVAILABLE:
            messagebox.showerror('오류', 'mss 패키지를 먼저 설치하세요.\npip install mss')
            return
        self.root.iconify()
        time.sleep(0.35)
        RegionSelector(self._on_region)

    def _on_region(self, region):
        self.root.deiconify()
        if region is None:
            return
        self.region = region
        self.recorder = Recorder(region, self.fps_var.get(), self._on_frame)
        self.btn_start.config(state='disabled')
        self.btn_stop.config(state='normal')
        self.status_var.set(f'🔴 녹화 중  –  영역: {region["width"]}×{region["height"]}  |  {self.fps_var.get()} FPS')
        self.recorder.start()

    def stop_recording(self):
        if self.recorder:
            self.recorder.stop()
            self.recorder = None
        self.btn_start.config(state='normal')
        self.btn_stop.config(state='disabled')
        self.status_var.set(f'녹화 완료  –  총 {len(self.frames)}개 프레임')

    def _on_frame(self, rgb: np.ndarray, idx: int):
        self.frames.append(rgb)
        self.root.after(0, self._add_thumb, rgb, idx)

    # ── 썸네일 ─────────────────────────────────────────────────
    def _add_thumb(self, rgb: np.ndarray, idx: int):
        if self.empty_label.winfo_ismapped():
            self.empty_label.grid_forget()

        img = Image.fromarray(rgb)
        img.thumbnail((self.THUMB_W, self.THUMB_H), Image.LANCZOS)
        photo = ImageTk.PhotoImage(img)
        self._thumb_refs.append(photo)

        row, col = divmod(idx, self.COLS)

        cell = tk.Frame(self.gallery, bg=self.CARD,
                         highlightthickness=2, highlightbackground=self.DESEL,
                         cursor='hand2')
        cell.grid(row=row, column=col, padx=7, pady=7, sticky='nsew')
        self._cells.append(cell)

        img_lbl = tk.Label(cell, image=photo, bg=self.CARD)
        img_lbl.pack()

        num_lbl = tk.Label(cell, text=f'#{idx + 1}', bg=self.CARD, fg=self.MUTED,
                            font=('Consolas', 8))
        num_lbl.pack(pady=2)

        for w in (cell, img_lbl, num_lbl):
            w.bind('<Button-1>', lambda e, i=idx: self._toggle(i))

        self.frame_count_var.set(f'프레임 {len(self.frames)}')

    def _toggle(self, idx: int):
        if idx in self.selected:
            self.selected.discard(idx)
            self._cells[idx].config(highlightbackground=self.DESEL)
        else:
            self.selected.add(idx)
            self._cells[idx].config(highlightbackground=self.SEL_HL)
        self.sel_var.set(f'선택된 프레임: {len(self.selected)}개')

    # ── 선택 & 저장 ────────────────────────────────────────────
    def select_all(self):
        for i in range(len(self.frames)):
            self.selected.add(i)
            if i < len(self._cells):
                self._cells[i].config(highlightbackground=self.SEL_HL)
        self.sel_var.set(f'선택된 프레임: {len(self.selected)}개')

    def deselect_all(self):
        self.selected.clear()
        for c in self._cells:
            c.config(highlightbackground=self.DESEL)
        self.sel_var.set('선택된 프레임: 0개')

    def save_selected(self):
        if not self.selected:
            messagebox.showwarning('알림', '저장할 프레임을 클릭해서 선택하세요.')
            return
        folder = filedialog.askdirectory(title='저장 폴더 선택')
        if not folder:
            return
        saved = 0
        for idx in sorted(self.selected):
            if idx < len(self.frames):
                Image.fromarray(self.frames[idx]).save(
                    os.path.join(folder, f'frame_{idx + 1:04d}.png'))
                saved += 1
        messagebox.showinfo('저장 완료', f'✅ {saved}개 프레임 저장 완료\n\n📁 {folder}')

    def clear_all(self):
        if self.frames and not messagebox.askyesno('초기화', '모든 프레임을 삭제할까요?'):
            return
        if self.recorder:
            self.stop_recording()
        self.frames.clear()
        self.selected.clear()
        self._thumb_refs.clear()
        self._cells.clear()
        for w in self.gallery.winfo_children():
            w.destroy()
        self.empty_label = tk.Label(self.gallery,
                                     text='녹화를 시작하면 여기에\n프레임 썸네일이 나타납니다.',
                                     bg=self.BG, fg=self.MUTED, font=('맑은 고딕', 12))
        self.empty_label.grid(row=0, column=0, columnspan=self.COLS, pady=80)
        self.frame_count_var.set('프레임 0')
        self.sel_var.set('선택된 프레임: 0개')
        self.status_var.set('초기화됨')

    def run(self):
        self.root.mainloop()


if __name__ == '__main__':
    app = App()
    app.run()
