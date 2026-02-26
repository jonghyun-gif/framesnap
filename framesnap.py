"""
FrameSnap – 화면 영역 녹화 & 프레임 추출기
추가 기능: 프레임 크게보기 / 녹화중 빨간 테두리 표시
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import threading
import time
import os
import numpy as np
from PIL import Image, ImageTk

try:
    import mss
    MSS_AVAILABLE = True
except ImportError:
    MSS_AVAILABLE = False


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


class RecordingBorder:
    """녹화 중 빨간 테두리 + REC 라벨 (꿀캠 스타일)"""
    B = 4

    def __init__(self, region: dict):
        self.region = region
        self._wins = []
        self._blink_on = True
        self._after_id = None
        self._create()

    def _create(self):
        r = self.region
        b = self.B
        sides = [
            (r['left'] - b,           r['top'] - b,            r['width'] + b*2, b),
            (r['left'] - b,           r['top'] + r['height'],  r['width'] + b*2, b),
            (r['left'] - b,           r['top'],                 b, r['height']),
            (r['left'] + r['width'],  r['top'],                 b, r['height']),
        ]
        for x, y, w, h in sides:
            win = tk.Toplevel()
            win.overrideredirect(True)
            win.attributes('-topmost', True)
            win.geometry(f'{max(w,1)}x{max(h,1)}+{x}+{y}')
            win.configure(bg='red')
            self._wins.append(win)

        # REC 뱃지
        rec = tk.Toplevel()
        rec.overrideredirect(True)
        rec.attributes('-topmost', True)
        rec.geometry(f'+{r["left"]}+{r["top"]}')
        rec.configure(bg='red')
        tk.Label(rec, text=' ⏺ REC ', bg='red', fg='white',
                 font=('Consolas', 9, 'bold')).pack()
        self._wins.append(rec)

        self._blink()

    def _blink(self):
        self._blink_on = not self._blink_on
        color = 'red' if self._blink_on else '#880000'
        for win in self._wins:
            try:
                win.configure(bg=color)
                for c in win.winfo_children():
                    c.configure(bg=color)
            except Exception:
                pass
        try:
            self._after_id = self._wins[0].after(500, self._blink)
        except Exception:
            pass

    def destroy(self):
        try:
            if self._after_id and self._wins:
                self._wins[0].after_cancel(self._after_id)
        except Exception:
            pass
        for win in self._wins:
            try:
                win.destroy()
            except Exception:
                pass
        self._wins.clear()


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
                rgb = arr[:, :, [2, 1, 0]]
                self.on_frame(rgb, idx)
                idx += 1
                wait = interval - (time.perf_counter() - t0)
                if wait > 0:
                    time.sleep(wait)


class PreviewWindow:
    """프레임 크게보기 팝업 (더블클릭으로 열기, 좌우 키로 탐색)"""
    MAX_W = 960
    MAX_H = 700

    def __init__(self, parent, frames: list, start_idx: int):
        self.frames = frames
        self.idx = start_idx

        self.win = tk.Toplevel(parent)
        self.win.title(f'미리보기')
        self.win.configure(bg='#0e0e14')
        self.win.grab_set()

        self.win.bind('<Left>',  lambda e: self._nav(-1))
        self.win.bind('<Right>', lambda e: self._nav(1))
        self.win.bind('<Escape>', lambda e: self.win.destroy())

        self._ref = None
        self._build()
        self._show()

    def _build(self):
        nav = tk.Frame(self.win, bg='#18181f', height=44)
        nav.pack(fill='x')
        nav.pack_propagate(False)

        tk.Button(nav, text='◀  이전', command=lambda: self._nav(-1),
                  bg='#2e2e3e', fg='white', relief='flat',
                  font=('맑은 고딕', 9, 'bold'), padx=12, pady=6,
                  cursor='hand2').pack(side='left', padx=10, pady=7)

        self.nav_lbl = tk.Label(nav, text='', bg='#18181f', fg='#e4e4f0',
                                 font=('Consolas', 11, 'bold'))
        self.nav_lbl.pack(side='left', padx=10)

        tk.Button(nav, text='다음  ▶', command=lambda: self._nav(1),
                  bg='#2e2e3e', fg='white', relief='flat',
                  font=('맑은 고딕', 9, 'bold'), padx=12, pady=6,
                  cursor='hand2').pack(side='left', padx=4, pady=7)

        tk.Label(nav, text='← → 키로 이동   /   ESC 닫기',
                 bg='#18181f', fg='#5a5a72', font=('맑은 고딕', 8)).pack(side='right', padx=16)

        self.img_lbl = tk.Label(self.win, bg='#0e0e14')
        self.img_lbl.pack(fill='both', expand=True, padx=10, pady=10)

    def _show(self):
        if not self.frames:
            return
        rgb = self.frames[self.idx]
        img = Image.fromarray(rgb)
        iw, ih = img.size
        scale = min(self.MAX_W / iw, self.MAX_H / ih, 1.0)
        img = img.resize((int(iw * scale), int(ih * scale)), Image.LANCZOS)
        self._ref = ImageTk.PhotoImage(img)
        self.img_lbl.config(image=self._ref)
        self.nav_lbl.config(text=f'#{self.idx + 1}  /  {len(self.frames)}')
        self.win.title(f'미리보기  –  #{self.idx + 1} / {len(self.frames)}')
        nw, nh = img.size
        self.win.geometry(f'{nw + 20}x{nh + 64}')

    def _nav(self, d: int):
        new = self.idx + d
        if 0 <= new < len(self.frames):
            self.idx = new
            self._show()


class App:
    THUMB_W = 192
    THUMB_H = 120
    COLS    = 4

    BG    = '#0e0e14'
    PANEL = '#18181f'
    CARD  = '#1f1f29'
    ACCENT= '#00FFB3'
    RED   = '#FF4E6A'
    TEXT  = '#e4e4f0'
    MUTED = '#5a5a72'
    SEL   = '#00FFB3'
    DESEL = '#2e2e3e'

    def __init__(self):
        self.root = tk.Tk()
        self.root.title('FrameSnap')
        self.root.geometry('900x700')
        self.root.minsize(700, 500)
        self.root.configure(bg=self.BG)

        self.recorder: Recorder | None         = None
        self.rec_border: RecordingBorder | None = None
        self.region: dict | None               = None
        self.fps_var   = tk.IntVar(value=5)
        self.frames: list                      = []
        self.selected: set                     = set()
        self._refs                             = []
        self._cells: list                      = []

        self._build()

        if not MSS_AVAILABLE:
            messagebox.showerror('패키지 누락', 'pip install mss 후 다시 실행하세요.')

    def _btn(self, parent, text, cmd, bg=None, fg=None, state='normal', **kw):
        return tk.Button(parent, text=text, command=cmd,
                         bg=bg or self.CARD, fg=fg or self.TEXT,
                         relief='flat', activebackground=bg or self.CARD,
                         activeforeground=fg or self.TEXT,
                         font=('맑은 고딕', 9, 'bold'), padx=12, pady=6,
                         cursor='hand2', state=state, bd=0, **kw)

    def _build(self):
        # ── 탑바
        bar = tk.Frame(self.root, bg=self.PANEL, height=64)
        bar.pack(fill='x')
        bar.pack_propagate(False)

        tk.Label(bar, text='⬛ FrameSnap', bg=self.PANEL, fg=self.ACCENT,
                 font=('Consolas', 15, 'bold')).pack(side='left', padx=18)

        fps_f = tk.Frame(bar, bg=self.PANEL)
        fps_f.pack(side='left', padx=8)
        tk.Label(fps_f, text='FPS', bg=self.PANEL, fg=self.MUTED,
                 font=('Consolas', 9)).pack(side='left')
        tk.Spinbox(fps_f, from_=1, to=30, textvariable=self.fps_var, width=3,
                   bg='#252530', fg=self.TEXT, insertbackground=self.TEXT,
                   relief='flat', font=('Consolas', 12), justify='center',
                   buttonbackground='#252530').pack(side='left', padx=6)

        self.btn_stop = self._btn(bar, '⏹  중지', self.stop_recording,
                                   bg=self.RED, fg='white', state='disabled')
        self.btn_stop.pack(side='right', padx=10, pady=14)

        self.btn_start = self._btn(bar, '⏺  영역 선택 후 녹화', self.start_recording,
                                    bg=self.ACCENT, fg=self.BG)
        self.btn_start.pack(side='right', padx=4, pady=14)

        self._btn(bar, '🗑  초기화', self.clear_all).pack(side='right', padx=4, pady=14)

        # ── 상태바
        sbar = tk.Frame(self.root, bg='#111118', height=28)
        sbar.pack(fill='x')
        sbar.pack_propagate(False)
        self.status_var = tk.StringVar(value='준비됨  –  영역 선택 후 녹화 버튼을 누르세요')
        self.cnt_var    = tk.StringVar(value='프레임 0')
        tk.Label(sbar, textvariable=self.status_var, bg='#111118', fg=self.MUTED,
                 font=('Consolas', 8)).pack(side='left', padx=12)
        tk.Label(sbar, textvariable=self.cnt_var, bg='#111118', fg=self.ACCENT,
                 font=('Consolas', 8, 'bold')).pack(side='right', padx=12)

        # ── 갤러리
        wrap = tk.Frame(self.root, bg=self.BG)
        wrap.pack(fill='both', expand=True)
        self.gc = tk.Canvas(wrap, bg=self.BG, highlightthickness=0)
        vsb = ttk.Scrollbar(wrap, orient='vertical', command=self.gc.yview)
        self.gc.configure(yscrollcommand=vsb.set)
        vsb.pack(side='right', fill='y')
        self.gc.pack(fill='both', expand=True)
        self.gf = tk.Frame(self.gc, bg=self.BG)
        self._gw = self.gc.create_window((0, 0), window=self.gf, anchor='nw')
        self.gf.bind('<Configure>', lambda e: self.gc.configure(scrollregion=self.gc.bbox('all')))
        self.gc.bind('<Configure>', lambda e: self.gc.itemconfig(self._gw, width=e.width))
        self.gc.bind_all('<MouseWheel>', lambda e: self.gc.yview_scroll(int(-e.delta/120), 'units'))

        self.empty_lbl = tk.Label(self.gf,
                                   text='녹화를 시작하면 여기에\n프레임 썸네일이 나타납니다.\n\n더블클릭으로 크게 볼 수 있습니다.',
                                   bg=self.BG, fg=self.MUTED, font=('맑은 고딕', 12))
        self.empty_lbl.grid(row=0, column=0, columnspan=self.COLS, pady=80)

        # ── 바텀바
        bot = tk.Frame(self.root, bg=self.PANEL, height=52)
        bot.pack(fill='x')
        bot.pack_propagate(False)
        self.sel_var = tk.StringVar(value='선택된 프레임: 0개')
        tk.Label(bot, textvariable=self.sel_var, bg=self.PANEL, fg=self.MUTED,
                 font=('맑은 고딕', 9)).pack(side='left', padx=16, pady=14)
        self._btn(bot, '전체 선택', self.select_all).pack(side='left', padx=4, pady=12)
        self._btn(bot, '선택 해제', self.deselect_all).pack(side='left', padx=4, pady=12)
        self._btn(bot, '💾  선택한 프레임 PNG 저장', self.save_selected,
                  bg=self.ACCENT, fg=self.BG).pack(side='right', padx=16, pady=10)

    # ── 녹화
    def start_recording(self):
        if not MSS_AVAILABLE:
            messagebox.showerror('오류', 'pip install mss 후 재실행하세요.')
            return
        self.root.iconify()
        time.sleep(0.35)
        RegionSelector(self._on_region)

    def _on_region(self, region):
        self.root.deiconify()
        if region is None:
            return
        self.region = region
        self.rec_border = RecordingBorder(region)
        self.recorder = Recorder(region, self.fps_var.get(), self._on_frame)
        self.btn_start.config(state='disabled')
        self.btn_stop.config(state='normal')
        self.status_var.set(f'🔴 녹화 중  –  {region["width"]}×{region["height"]}  |  {self.fps_var.get()} FPS')
        self.recorder.start()

    def stop_recording(self):
        if self.recorder:
            self.recorder.stop()
            self.recorder = None
        if self.rec_border:
            self.rec_border.destroy()
            self.rec_border = None
        self.btn_start.config(state='normal')
        self.btn_stop.config(state='disabled')
        self.status_var.set(f'녹화 완료  –  총 {len(self.frames)}개 프레임')

    def _on_frame(self, rgb, idx):
        self.frames.append(rgb)
        self.root.after(0, self._add_thumb, rgb, idx)

    # ── 썸네일
    def _add_thumb(self, rgb, idx):
        if self.empty_lbl.winfo_ismapped():
            self.empty_lbl.grid_forget()

        img = Image.fromarray(rgb)
        img.thumbnail((self.THUMB_W, self.THUMB_H), Image.LANCZOS)
        photo = ImageTk.PhotoImage(img)
        self._refs.append(photo)

        row, col = divmod(idx, self.COLS)
        cell = tk.Frame(self.gf, bg=self.CARD,
                         highlightthickness=2, highlightbackground=self.DESEL,
                         cursor='hand2')
        cell.grid(row=row, column=col, padx=7, pady=7, sticky='nsew')
        self._cells.append(cell)

        il = tk.Label(cell, image=photo, bg=self.CARD)
        il.pack()
        nl = tk.Label(cell, text=f'#{idx+1}', bg=self.CARD, fg=self.MUTED,
                       font=('Consolas', 8))
        nl.pack(pady=2)

        for w in (cell, il, nl):
            w.bind('<Button-1>',        lambda e, i=idx: self._toggle(i))
            w.bind('<Double-Button-1>', lambda e, i=idx: self._preview(i))

        self.cnt_var.set(f'프레임 {len(self.frames)}')

    def _toggle(self, idx):
        if idx in self.selected:
            self.selected.discard(idx)
            self._cells[idx].config(highlightbackground=self.DESEL)
        else:
            self.selected.add(idx)
            self._cells[idx].config(highlightbackground=self.SEL)
        self.sel_var.set(f'선택된 프레임: {len(self.selected)}개')

    def _preview(self, idx):
        PreviewWindow(self.root, self.frames, idx)

    # ── 선택/저장
    def select_all(self):
        for i in range(len(self.frames)):
            self.selected.add(i)
            if i < len(self._cells):
                self._cells[i].config(highlightbackground=self.SEL)
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
                    os.path.join(folder, f'frame_{idx+1:04d}.png'))
                saved += 1
        messagebox.showinfo('저장 완료', f'✅ {saved}개 프레임 저장 완료\n\n📁 {folder}')

    def clear_all(self):
        if self.frames and not messagebox.askyesno('초기화', '모든 프레임을 삭제할까요?'):
            return
        if self.recorder:
            self.stop_recording()
        self.frames.clear()
        self.selected.clear()
        self._refs.clear()
        self._cells.clear()
        for w in self.gf.winfo_children():
            w.destroy()
        self.empty_lbl = tk.Label(self.gf,
                                   text='녹화를 시작하면 여기에\n프레임 썸네일이 나타납니다.\n\n더블클릭으로 크게 볼 수 있습니다.',
                                   bg=self.BG, fg=self.MUTED, font=('맑은 고딕', 12))
        self.empty_lbl.grid(row=0, column=0, columnspan=self.COLS, pady=80)
        self.cnt_var.set('프레임 0')
        self.sel_var.set('선택된 프레임: 0개')
        self.status_var.set('초기화됨')

    def run(self):
        self.root.mainloop()


if __name__ == '__main__':
    App().run()
