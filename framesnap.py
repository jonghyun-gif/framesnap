"""
FrameSnap – 화면 영역 녹화 & 프레임 추출기
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


# ──────────────────────────────────────────────────────────────
# 영역 선택 오버레이 (개선: 빨간 굵은 선 + 크기 실시간 표시)
# ──────────────────────────────────────────────────────────────
class RegionSelector:
    def __init__(self, callback):
        self.callback = callback

        # 반투명 검은 오버레이
        self.win = tk.Toplevel()
        self.win.attributes('-fullscreen', True)
        self.win.attributes('-topmost', True)
        self.win.configure(bg='black')
        self.win.attributes('-alpha', 0.45)
        self.win.lift()
        self.win.focus_force()

        self.canvas = tk.Canvas(self.win, cursor='cross', bg='black', highlightthickness=0)
        self.canvas.pack(fill='both', expand=True)

        # 안내 텍스트
        self.guide = tk.Label(self.win,
                               text='드래그하여 녹화 영역을 선택하세요  [ ESC = 취소 ]',
                               bg='black', fg='white', font=('맑은 고딕', 14, 'bold'))
        self.guide.place(relx=0.5, rely=0.05, anchor='center')

        # 크기 표시 라벨
        self.size_lbl = tk.Label(self.win, text='', bg='#cc0000', fg='white',
                                  font=('Consolas', 11, 'bold'), padx=8, pady=3)

        self.sx = self.sy = 0
        self.rect = None

        self.canvas.bind('<ButtonPress-1>',   self._press)
        self.canvas.bind('<B1-Motion>',       self._drag)
        self.canvas.bind('<ButtonRelease-1>', self._release)
        self.win.bind('<Escape>', lambda e: self._cancel())

    def _press(self, e):
        self.sx, self.sy = e.x, e.y
        # 빨간색 굵은 선으로 사각형
        self.rect = self.canvas.create_rectangle(
            e.x, e.y, e.x, e.y,
            outline='red', width=3
        )

    def _drag(self, e):
        self.canvas.coords(self.rect, self.sx, self.sy, e.x, e.y)
        w = abs(e.x - self.sx)
        h = abs(e.y - self.sy)
        # 크기 라벨을 마우스 커서 근처에 표시
        self.size_lbl.config(text=f' {w} × {h} ')
        lx = e.x + 14
        ly = e.y + 14
        self.size_lbl.place(x=lx, y=ly)

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
# 3초 카운트다운 오버레이
# ──────────────────────────────────────────────────────────────
class Countdown:
    def __init__(self, region: dict, on_done):
        self.on_done = on_done
        self.count = 3

        # 반투명 오버레이 (녹화 영역 위에만)
        self.win = tk.Toplevel()
        self.win.overrideredirect(True)
        self.win.attributes('-topmost', True)
        self.win.attributes('-alpha', 0.75)
        r = region
        self.win.geometry(f'{r["width"]}x{r["height"]}+{r["left"]}+{r["top"]}')
        self.win.configure(bg='black')

        self.lbl = tk.Label(self.win, text='3', bg='black', fg='red',
                             font=('Consolas', min(r['height']//2, 200), 'bold'))
        self.lbl.place(relx=0.5, rely=0.5, anchor='center')

        sub = tk.Label(self.win, text='녹화 시작까지...', bg='black', fg='white',
                        font=('맑은 고딕', 14))
        sub.place(relx=0.5, rely=0.72, anchor='center')

        self._tick()

    def _tick(self):
        if self.count > 0:
            self.lbl.config(text=str(self.count))
            self.count -= 1
            self.win.after(1000, self._tick)
        else:
            self.win.destroy()
            self.on_done()


# ──────────────────────────────────────────────────────────────
# 녹화 중 플로팅 컨트롤 바
# ──────────────────────────────────────────────────────────────
class FloatingControls:
    def __init__(self, region: dict, on_stop):
        self.region = region
        self.paused = False

        self.win = tk.Toplevel()
        self.win.overrideredirect(True)
        self.win.attributes('-topmost', True)
        self.win.configure(bg='#1a1a1a')

        bw, bh = 340, 56
        cx = region['left'] + region['width'] // 2 - bw // 2
        cy = region['top'] - bh - 8
        if cy < 0:
            cy = region['top'] + 8
        self.win.geometry(f'{bw}x{bh}+{cx}+{cy}')

        frame = tk.Frame(self.win, bg='#1a1a1a')
        frame.pack(fill='both', expand=True, padx=6, pady=6)

        self.rec_lbl = tk.Label(frame, text='⏺ REC', bg='#1a1a1a', fg='red',
                                 font=('Consolas', 14, 'bold'))
        self.rec_lbl.pack(side='left', padx=10)

        self.btn_pause = tk.Button(frame, text='⏸ 일시정지', command=self._toggle_pause,
                                    bg='#444', fg='white', relief='flat',
                                    font=('맑은 고딕', 11, 'bold'), padx=10, pady=6,
                                    cursor='hand2', bd=0)
        self.btn_pause.pack(side='left', padx=4)

        tk.Button(frame, text='⏹ 중지', command=on_stop,
                  bg='#FF4E6A', fg='white', relief='flat',
                  font=('맑은 고딕', 11, 'bold'), padx=14, pady=6,
                  cursor='hand2', bd=0
                  ).pack(side='left', padx=4)

        # 드래그
        for w in (frame, self.rec_lbl):
            w.bind('<ButtonPress-1>', self._drag_start)
            w.bind('<B1-Motion>',     self._drag_move)
        self._dx = self._dy = 0

        # 테두리
        self._borders = []
        self._create_border()

        # 깜빡임
        self._blink_on = True
        self._blink()

    def _create_border(self):
        r = self.region
        b = 3
        sides = [
            (r['left']-b,           r['top']-b,          r['width']+b*2, b),
            (r['left']-b,           r['top']+r['height'], r['width']+b*2, b),
            (r['left']-b,           r['top'],             b, r['height']),
            (r['left']+r['width'],  r['top'],             b, r['height']),
        ]
        for x, y, w, h in sides:
            bw = tk.Toplevel()
            bw.overrideredirect(True)
            bw.attributes('-topmost', True)
            bw.geometry(f'{max(w,1)}x{max(h,1)}+{x}+{y}')
            bw.configure(bg='red')
            self._borders.append(bw)

    def _blink(self):
        self._blink_on = not self._blink_on
        c = 'red' if self._blink_on else '#660000'
        try:
            self.rec_lbl.config(fg=c)
            for b in self._borders:
                b.configure(bg=c)
            self.win.after(500, self._blink)
        except Exception:
            pass

    def _toggle_pause(self):
        self.paused = not self.paused
        if self.paused:
            self.btn_pause.config(text='▶ 재개', bg='#00FFB3', fg='#0e0e14')
            self.rec_lbl.config(text='⏸ 일시중지', fg='#aaa')
        else:
            self.btn_pause.config(text='⏸ 일시정지', bg='#444', fg='white')
            self.rec_lbl.config(text='⏺ REC', fg='red')

    def _drag_start(self, e):
        self._dx, self._dy = e.x, e.y

    def _drag_move(self, e):
        x = self.win.winfo_x() + e.x - self._dx
        y = self.win.winfo_y() + e.y - self._dy
        self.win.geometry(f'+{x}+{y}')

    def destroy(self):
        try: self.win.destroy()
        except: pass
        for b in self._borders:
            try: b.destroy()
            except: pass
        self._borders.clear()


# ──────────────────────────────────────────────────────────────
# 녹화 엔진
# ──────────────────────────────────────────────────────────────
class Recorder:
    def __init__(self, region: dict, fps: int, on_frame, get_paused):
        self.region     = region
        self.fps        = fps
        self.on_frame   = on_frame
        self.get_paused = get_paused
        self.running    = False
        self._thread    = None

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
                if not self.get_paused():
                    raw = sct.grab(self.region)
                    arr = np.frombuffer(raw.raw, dtype=np.uint8).reshape(raw.height, raw.width, 4)
                    rgb = arr[:, :, [2, 1, 0]]
                    self.on_frame(rgb, idx)
                    idx += 1
                wait = interval - (time.perf_counter() - t0)
                if wait > 0:
                    time.sleep(wait)


# ──────────────────────────────────────────────────────────────
# 메인 GUI
# ──────────────────────────────────────────────────────────────
class App:
    THUMB_W = 160
    THUMB_H = 100
    COLS    = 3

    BG      = '#0e0e14'
    PANEL   = '#18181f'
    CARD    = '#1f1f29'
    ACCENT  = '#00FFB3'
    RED     = '#FF4E6A'
    TEXT    = '#e4e4f0'
    MUTED   = '#5a5a72'
    SEL     = '#00FFB3'
    DESEL   = '#2e2e3e'
    PREV_BG = '#13131e'

    def __init__(self):
        self.root = tk.Tk()
        self.root.title('FrameSnap')
        self.root.geometry('1100x700')
        self.root.minsize(800, 500)
        self.root.configure(bg=self.BG)

        self.recorder:   Recorder | None         = None
        self.float_ctrl: FloatingControls | None = None
        self.region:     dict | None             = None
        self.fps_var     = tk.IntVar(value=5)
        self.delay_var   = tk.BooleanVar(value=True)   # 3초 딜레이 ON/OFF
        self.frames: list         = []
        self.selected: set        = set()
        self._refs                = []
        self._cells: list         = []
        self._preview_ref         = None
        self._current_preview_idx = -1

        self._build()

        if not MSS_AVAILABLE:
            messagebox.showerror('패키지 누락', 'pip install mss 후 다시 실행하세요.')

    # ── 공통 버튼 헬퍼
    def _btn(self, parent, text, cmd, bg=None, fg=None, state='normal', **kw):
        return tk.Button(parent, text=text, command=cmd,
                         bg=bg or self.CARD, fg=fg or self.TEXT,
                         relief='flat', activebackground=bg or self.CARD,
                         activeforeground=fg or self.TEXT,
                         font=('맑은 고딕', 9, 'bold'), padx=12, pady=6,
                         cursor='hand2', state=state, bd=0, **kw)

    def _build(self):
        # ── 탑바
        bar = tk.Frame(self.root, bg=self.PANEL, height=60)
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

        # 3초 딜레이 체크박스
        delay_f = tk.Frame(bar, bg=self.PANEL)
        delay_f.pack(side='left', padx=12)
        tk.Checkbutton(delay_f, text='3초 후 시작', variable=self.delay_var,
                       bg=self.PANEL, fg=self.TEXT, selectcolor='#252530',
                       activebackground=self.PANEL, activeforeground=self.TEXT,
                       font=('맑은 고딕', 9), cursor='hand2').pack(side='left')

        # 버튼
        self.btn_start = self._btn(bar, '⏺  영역 선택 후 녹화', self.start_recording,
                                    bg=self.ACCENT, fg=self.BG)
        self.btn_start.pack(side='right', padx=14, pady=10)
        self._btn(bar, '🗑  초기화', self.clear_all).pack(side='right', padx=4, pady=10)

        # ── 상태바
        sbar = tk.Frame(self.root, bg='#111118', height=26)
        sbar.pack(fill='x')
        sbar.pack_propagate(False)
        self.status_var = tk.StringVar(value='준비됨  –  영역 선택 후 녹화 버튼을 누르세요')
        self.cnt_var    = tk.StringVar(value='프레임 0')
        tk.Label(sbar, textvariable=self.status_var, bg='#111118', fg=self.MUTED,
                 font=('Consolas', 8)).pack(side='left', padx=12)
        tk.Label(sbar, textvariable=self.cnt_var, bg='#111118', fg=self.ACCENT,
                 font=('Consolas', 8, 'bold')).pack(side='right', padx=12)

        # ── 메인 (좌: 썸네일 / 우: 미리보기)
        main = tk.Frame(self.root, bg=self.BG)
        main.pack(fill='both', expand=True)

        # 좌측 썸네일
        left = tk.Frame(main, bg=self.BG, width=420)
        left.pack(side='left', fill='both')
        left.pack_propagate(False)

        self.gc = tk.Canvas(left, bg=self.BG, highlightthickness=0)
        vsb = ttk.Scrollbar(left, orient='vertical', command=self.gc.yview)
        self.gc.configure(yscrollcommand=vsb.set)
        vsb.pack(side='right', fill='y')
        self.gc.pack(fill='both', expand=True)
        self.gf = tk.Frame(self.gc, bg=self.BG)
        self._gw = self.gc.create_window((0,0), window=self.gf, anchor='nw')
        self.gf.bind('<Configure>', lambda e: self.gc.configure(scrollregion=self.gc.bbox('all')))
        self.gc.bind('<Configure>', lambda e: self.gc.itemconfig(self._gw, width=e.width))
        self.gc.bind_all('<MouseWheel>', lambda e: self.gc.yview_scroll(int(-e.delta/120), 'units'))

        self.empty_lbl = tk.Label(self.gf,
                                   text='녹화를 시작하면\n여기에 프레임이 나타납니다.',
                                   bg=self.BG, fg=self.MUTED, font=('맑은 고딕', 11))
        self.empty_lbl.grid(row=0, column=0, columnspan=self.COLS, pady=60)

        # 우측 미리보기
        right = tk.Frame(main, bg=self.PREV_BG)
        right.pack(side='left', fill='both', expand=True)

        prev_top = tk.Frame(right, bg='#1a1a28', height=36)
        prev_top.pack(fill='x')
        prev_top.pack_propagate(False)
        tk.Label(prev_top, text='미리보기', bg='#1a1a28', fg=self.MUTED,
                 font=('맑은 고딕', 9, 'bold')).pack(side='left', padx=14, pady=8)
        self.prev_title = tk.Label(prev_top, text='', bg='#1a1a28', fg=self.ACCENT,
                                    font=('Consolas', 9, 'bold'))
        self.prev_title.pack(side='left')

        nav_f = tk.Frame(prev_top, bg='#1a1a28')
        nav_f.pack(side='right', padx=8)
        tk.Button(nav_f, text='◀', command=lambda: self._prev_nav(-1),
                  bg='#2e2e3e', fg='white', relief='flat', font=('Consolas', 10),
                  padx=8, pady=2, cursor='hand2', bd=0).pack(side='left', padx=2)
        tk.Button(nav_f, text='▶', command=lambda: self._prev_nav(1),
                  bg='#2e2e3e', fg='white', relief='flat', font=('Consolas', 10),
                  padx=8, pady=2, cursor='hand2', bd=0).pack(side='left', padx=2)

        self.prev_canvas = tk.Canvas(right, bg=self.PREV_BG, highlightthickness=0)
        self.prev_canvas.pack(fill='both', expand=True, padx=10, pady=10)

        self.prev_hint = tk.Label(right,
                                   text='썸네일을 클릭하면\n여기에 크게 표시됩니다.\n\n← → 키로 이동',
                                   bg=self.PREV_BG, fg=self.MUTED, font=('맑은 고딕', 11))
        self.prev_hint.place(relx=0.5, rely=0.5, anchor='center')

        self.root.bind('<Left>',  lambda e: self._prev_nav(-1))
        self.root.bind('<Right>', lambda e: self._prev_nav(1))

        # ── 바텀바
        bot = tk.Frame(self.root, bg=self.PANEL, height=48)
        bot.pack(fill='x')
        bot.pack_propagate(False)
        self.sel_var = tk.StringVar(value='선택된 프레임: 0개')
        tk.Label(bot, textvariable=self.sel_var, bg=self.PANEL, fg=self.MUTED,
                 font=('맑은 고딕', 9)).pack(side='left', padx=16, pady=12)
        self._btn(bot, '전체 선택', self.select_all).pack(side='left', padx=4, pady=10)
        self._btn(bot, '선택 해제', self.deselect_all).pack(side='left', padx=4, pady=10)
        self._btn(bot, '💾  선택한 프레임 PNG 저장', self.save_selected,
                  bg=self.ACCENT, fg=self.BG).pack(side='right', padx=16, pady=8)

    # ── 녹화 흐름
    def start_recording(self):
        if not MSS_AVAILABLE:
            messagebox.showerror('오류', 'pip install mss 후 재실행하세요.')
            return
        self.root.iconify()
        time.sleep(0.3)
        RegionSelector(self._on_region)

    def _on_region(self, region):
        self.root.deiconify()
        if region is None:
            return
        self.region = region
        self.btn_start.config(state='disabled')

        if self.delay_var.get():
            # 3초 카운트다운 후 시작
            self.status_var.set('3초 후 녹화 시작...')
            Countdown(region, self._begin_recording)
        else:
            self._begin_recording()

    def _begin_recording(self):
        region = self.region
        self.float_ctrl = FloatingControls(region, self.stop_recording)
        self.recorder   = Recorder(region, self.fps_var.get(), self._on_frame,
                                    lambda: self.float_ctrl.paused if self.float_ctrl else False)
        self.status_var.set(f'🔴 녹화 중  –  {region["width"]}×{region["height"]}  |  {self.fps_var.get()} FPS')
        self.recorder.start()

    def stop_recording(self):
        if self.recorder:
            self.recorder.stop()
            self.recorder = None
        if self.float_ctrl:
            self.float_ctrl.destroy()
            self.float_ctrl = None
        self.btn_start.config(state='normal')
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
        cell.grid(row=row, column=col, padx=5, pady=5, sticky='nsew')
        self._cells.append(cell)

        il = tk.Label(cell, image=photo, bg=self.CARD)
        il.pack()
        nl = tk.Label(cell, text=f'#{idx+1}', bg=self.CARD, fg=self.MUTED,
                       font=('Consolas', 8))
        nl.pack(pady=2)

        for w in (cell, il, nl):
            w.bind('<Button-1>', lambda e, i=idx: self._click_frame(i))

        self._show_preview(idx)
        self.cnt_var.set(f'프레임 {len(self.frames)}')

    def _click_frame(self, idx):
        if idx in self.selected:
            self.selected.discard(idx)
            self._cells[idx].config(highlightbackground=self.DESEL)
        else:
            self.selected.add(idx)
            self._cells[idx].config(highlightbackground=self.SEL)
        self.sel_var.set(f'선택된 프레임: {len(self.selected)}개')
        self._show_preview(idx)

    # ── 우측 미리보기
    def _show_preview(self, idx):
        if idx < 0 or idx >= len(self.frames):
            return
        self._current_preview_idx = idx
        self.prev_hint.place_forget()

        rgb = self.frames[idx]
        img = Image.fromarray(rgb)

        self.prev_canvas.update_idletasks()
        cw = self.prev_canvas.winfo_width()  - 20
        ch = self.prev_canvas.winfo_height() - 20
        if cw < 50 or ch < 50:
            cw, ch = 500, 550

        iw, ih = img.size
        scale = min(cw / iw, ch / ih, 1.0)
        nw, nh = max(int(iw * scale), 1), max(int(ih * scale), 1)
        img = img.resize((nw, nh), Image.LANCZOS)

        self._preview_ref = ImageTk.PhotoImage(img)
        self.prev_canvas.delete('all')
        self.prev_canvas.create_image(cw//2 + 10, ch//2 + 10,
                                       image=self._preview_ref, anchor='center')
        self.prev_title.config(text=f'#{idx+1} / {len(self.frames)}')

    def _prev_nav(self, d):
        new = self._current_preview_idx + d
        if 0 <= new < len(self.frames):
            self._show_preview(new)

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
        self._current_preview_idx = -1
        self._preview_ref = None
        for w in self.gf.winfo_children():
            w.destroy()
        self.empty_lbl = tk.Label(self.gf,
                                   text='녹화를 시작하면\n여기에 프레임이 나타납니다.',
                                   bg=self.BG, fg=self.MUTED, font=('맑은 고딕', 11))
        self.empty_lbl.grid(row=0, column=0, columnspan=self.COLS, pady=60)
        self.prev_canvas.delete('all')
        self.prev_hint.place(relx=0.5, rely=0.5, anchor='center')
        self.prev_title.config(text='')
        self.cnt_var.set('프레임 0')
        self.sel_var.set('선택된 프레임: 0개')
        self.status_var.set('초기화됨')

    def run(self):
        self.root.mainloop()


if __name__ == '__main__':
    App().run()
