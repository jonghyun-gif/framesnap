"""
FrameSnap – 화면 영역 녹화 & 프레임 추출기
메인화면 = 영상 재생 / 서브팝업 = 프레임 선택 저장
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
# 영역 선택 오버레이
# ──────────────────────────────────────────────────────────────
class RegionSelector:
    def __init__(self, callback):
        self.callback = callback
        # 윈도우가 완전히 최소화될 때까지 충분히 대기 (1번 버그 수정)
        self.win = tk.Toplevel()
        self.win.after(150, self._init_overlay)

    def _init_overlay(self):
        self.win.attributes('-fullscreen', True)
        self.win.attributes('-topmost', True)
        self.win.configure(bg='black')
        self.win.attributes('-alpha', 0.45)
        self.win.lift()
        self.win.focus_force()
        self.canvas = tk.Canvas(self.win, cursor='cross', bg='black', highlightthickness=0)
        self.canvas.pack(fill='both', expand=True)
        tk.Label(self.win, text='드래그하여 녹화 영역을 선택하세요  [ ESC = 취소 ]',
                 bg='black', fg='white', font=('맑은 고딕', 14, 'bold')).place(relx=0.5, rely=0.05, anchor='center')
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
        self.rect = self.canvas.create_rectangle(e.x, e.y, e.x, e.y, outline='red', width=3)

    def _drag(self, e):
        self.canvas.coords(self.rect, self.sx, self.sy, e.x, e.y)
        w, h = abs(e.x - self.sx), abs(e.y - self.sy)
        self.size_lbl.config(text=f' {w} × {h} ')
        self.size_lbl.place(x=e.x + 14, y=e.y + 14)

    def _release(self, e):
        x1, y1 = min(self.sx, e.x), min(self.sy, e.y)
        x2, y2 = max(self.sx, e.x), max(self.sy, e.y)
        self.win.destroy()
        if x2-x1 > 20 and y2-y1 > 20:
            self.callback({'top': y1, 'left': x1, 'width': x2-x1, 'height': y2-y1})
        else:
            self.callback(None)

    def _cancel(self):
        self.win.destroy()
        self.callback(None)


# ──────────────────────────────────────────────────────────────
# 3초 카운트다운
# ──────────────────────────────────────────────────────────────
class Countdown:
    def __init__(self, region: dict, on_done):
        self.on_done = on_done
        self.count   = 3
        self.win     = tk.Toplevel()
        self.win.overrideredirect(True)
        self.win.attributes('-topmost', True)
        self.win.attributes('-alpha', 0.75)
        r = region
        self.win.geometry(f'{r["width"]}x{r["height"]}+{r["left"]}+{r["top"]}')
        self.win.configure(bg='black')
        self.lbl = tk.Label(self.win, text='3', bg='black', fg='red',
                             font=('Consolas', min(r['height']//2, 200), 'bold'))
        self.lbl.place(relx=0.5, rely=0.45, anchor='center')
        tk.Label(self.win, text='녹화 시작까지...', bg='black', fg='white',
                 font=('맑은 고딕', 14)).place(relx=0.5, rely=0.72, anchor='center')
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
        self.win    = tk.Toplevel()
        self.win.overrideredirect(True)
        self.win.attributes('-topmost', True)
        self.win.configure(bg='#1a1a1a')
        bw, bh = 340, 56
        cx = region['left'] + region['width'] // 2 - bw // 2
        cy = region['top'] - bh - 8
        if cy < 0: cy = region['top'] + 8
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
                  cursor='hand2', bd=0).pack(side='left', padx=4)
        for w in (frame, self.rec_lbl):
            w.bind('<ButtonPress-1>', self._drag_start)
            w.bind('<B1-Motion>',     self._drag_move)
        self._dx = self._dy = 0
        self._borders = []
        self._create_border()
        self._blink_on = True
        self._blink()

    def _create_border(self):
        r, b = self.region, 3
        for x, y, w, h in [
            (r['left']-b, r['top']-b, r['width']+b*2, b),
            (r['left']-b, r['top']+r['height'], r['width']+b*2, b),
            (r['left']-b, r['top'], b, r['height']),
            (r['left']+r['width'], r['top'], b, r['height']),
        ]:
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
            for b in self._borders: b.configure(bg=c)
            self.win.after(500, self._blink)
        except Exception: pass

    def _toggle_pause(self):
        self.paused = not self.paused
        if self.paused:
            self.btn_pause.config(text='▶ 재개', bg='#00FFB3', fg='#0e0e14')
            self.rec_lbl.config(text='⏸ 일시중지', fg='#aaa')
        else:
            self.btn_pause.config(text='⏸ 일시정지', bg='#444', fg='white')
            self.rec_lbl.config(text='⏺ REC', fg='red')

    def _drag_start(self, e): self._dx, self._dy = e.x, e.y
    def _drag_move(self, e):
        self.win.geometry(f'+{self.win.winfo_x()+e.x-self._dx}+{self.win.winfo_y()+e.y-self._dy}')

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
    def __init__(self, region, fps, on_frame, get_paused):
        self.region, self.fps = region, fps
        self.on_frame, self.get_paused = on_frame, get_paused
        self.running = False

    def start(self):
        self.running = True
        threading.Thread(target=self._loop, daemon=True).start()

    def stop(self): self.running = False

    def _loop(self):
        interval = 1.0 / self.fps
        idx = 0
        with mss.mss() as sct:
            while self.running:
                t0 = time.perf_counter()
                if not self.get_paused():
                    raw = sct.grab(self.region)
                    arr = np.frombuffer(raw.raw, dtype=np.uint8).reshape(raw.height, raw.width, 4)
                    self.on_frame(arr[:, :, [2,1,0]], idx)
                    idx += 1
                wait = interval - (time.perf_counter() - t0)
                if wait > 0: time.sleep(wait)


# ──────────────────────────────────────────────────────────────
# 서브 팝업: 프레임 선택 & 저장
# ──────────────────────────────────────────────────────────────
class FramePickerWindow:
    THUMB_W = 160
    THUMB_H = 100
    COLS    = 3
    BG      = '#0e0e14'
    PANEL   = '#18181f'
    CARD    = '#1f1f29'
    ACCENT  = '#00FFB3'
    GOLD    = '#FFD700'
    TEXT    = '#e4e4f0'
    MUTED   = '#5a5a72'
    SEL     = '#00FFB3'
    DESEL   = '#2e2e3e'
    PREV_BG = '#13131e'

    def __init__(self, parent, frames: list, bookmarks: set):
        self.frames    = frames
        self.bookmarks = bookmarks   # 공유 참조 (메인과 동기화)
        self.selected: set = set()
        self._refs         = []
        self._cells: list  = []
        self._preview_ref  = None
        self._cur_idx      = -1
        self.select_mode   = tk.BooleanVar(value=False)
        self.interval_var  = tk.IntVar(value=5)

        self.win = tk.Toplevel(parent)
        self.win.title('FrameSnap – 프레임 선택 & 저장')
        self.win.geometry('1100x700')
        self.win.minsize(800, 500)
        self.win.configure(bg=self.BG)

        self.win.bind('<Left>',  lambda e: self._prev_nav(-1))
        self.win.bind('<Right>', lambda e: self._prev_nav(1))

        self._build()
        self._load_all_thumbs()

    def _btn(self, parent, text, cmd, bg=None, fg=None, **kw):
        return tk.Button(parent, text=text, command=cmd,
                         bg=bg or self.CARD, fg=fg or self.TEXT,
                         relief='flat', activebackground=bg or self.CARD,
                         activeforeground=fg or self.TEXT,
                         font=('맑은 고딕', 9, 'bold'), padx=10, pady=5,
                         cursor='hand2', bd=0, **kw)

    def _build(self):
        # 툴바
        tools = tk.Frame(self.win, bg='#13131a', height=44)
        tools.pack(fill='x')
        tools.pack_propagate(False)

        self.btn_selmode = tk.Button(tools, text='☐ 선택하기',
                                      command=self._toggle_select_mode,
                                      bg='#2a2a38', fg=self.TEXT, relief='flat',
                                      font=('맑은 고딕', 9, 'bold'), padx=12, pady=6,
                                      cursor='hand2', bd=0)
        self.btn_selmode.pack(side='left', padx=10, pady=7)

        tk.Frame(tools, bg='#2e2e3e', width=1).pack(side='left', fill='y', pady=6, padx=4)

        tk.Label(tools, text='N프레임 간격:', bg='#13131a', fg=self.MUTED,
                 font=('맑은 고딕', 9)).pack(side='left', padx=(10,2))
        tk.Spinbox(tools, from_=1, to=100, textvariable=self.interval_var, width=4,
                   bg='#252530', fg=self.TEXT, insertbackground=self.TEXT,
                   relief='flat', font=('Consolas', 10), justify='center',
                   buttonbackground='#252530').pack(side='left', pady=8)
        self._btn(tools, '적용', self._apply_interval, bg='#3a3a50').pack(side='left', padx=6, pady=7)

        tk.Frame(tools, bg='#2e2e3e', width=1).pack(side='left', fill='y', pady=6, padx=4)
        self._btn(tools, '전체 선택', self.select_all, bg='#2a2a38').pack(side='left', padx=4, pady=7)
        self._btn(tools, '선택 해제', self.deselect_all, bg='#2a2a38').pack(side='left', padx=4, pady=7)
        tk.Frame(tools, bg='#2e2e3e', width=1).pack(side='left', fill='y', pady=6, padx=4)
        self._btn(tools, '🔖 책갈피만 저장', self.save_bookmarks,
                  bg='#3a3010', fg=self.GOLD).pack(side='left', padx=6, pady=7)
        self._btn(tools, '💾 선택 저장', self.save_selected,
                  bg=self.ACCENT, fg=self.BG).pack(side='right', padx=14, pady=7)

        self.sel_var = tk.StringVar(value='선택 모드 OFF  |  선택: 0개  |  책갈피: 0개')
        tk.Label(tools, textvariable=self.sel_var, bg='#13131a', fg=self.MUTED,
                 font=('맑은 고딕', 8)).pack(side='right', padx=10)

        # 메인: 좌(썸네일) + 우(미리보기)
        main = tk.Frame(self.win, bg=self.BG)
        main.pack(fill='both', expand=True)

        # 좌측 썸네일
        left = tk.Frame(main, bg=self.BG, width=430)
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

        self.empty_lbl = tk.Label(self.gf, text='프레임 로딩 중...',
                                   bg=self.BG, fg=self.MUTED, font=('맑은 고딕', 11))
        self.empty_lbl.grid(row=0, column=0, columnspan=self.COLS, pady=60)

        # 우측 미리보기
        right = tk.Frame(main, bg=self.PREV_BG)
        right.pack(side='left', fill='both', expand=True)

        prev_top = tk.Frame(right, bg='#1a1a28', height=40)
        prev_top.pack(fill='x')
        prev_top.pack_propagate(False)
        tk.Label(prev_top, text='미리보기', bg='#1a1a28', fg=self.MUTED,
                 font=('맑은 고딕', 9, 'bold')).pack(side='left', padx=14, pady=10)
        self.prev_title = tk.Label(prev_top, text='', bg='#1a1a28', fg=self.ACCENT,
                                    font=('Consolas', 9, 'bold'))
        self.prev_title.pack(side='left')
        self.btn_bm = tk.Button(prev_top, text='🔖', command=self._toggle_bookmark_current,
                                 bg='#1a1a28', fg=self.MUTED, relief='flat',
                                 font=('Consolas', 14), padx=6, cursor='hand2', bd=0)
        self.btn_bm.pack(side='left', padx=6)

        nav_f = tk.Frame(prev_top, bg='#1a1a28')
        nav_f.pack(side='right', padx=8)
        tk.Button(nav_f, text='◀', command=lambda: self._prev_nav(-1),
                  bg='#2e2e3e', fg='white', relief='flat', font=('Consolas', 10),
                  padx=8, pady=3, cursor='hand2', bd=0).pack(side='left', padx=2)
        tk.Button(nav_f, text='▶', command=lambda: self._prev_nav(1),
                  bg='#2e2e3e', fg='white', relief='flat', font=('Consolas', 10),
                  padx=8, pady=3, cursor='hand2', bd=0).pack(side='left', padx=2)

        self.prev_canvas = tk.Canvas(right, bg=self.PREV_BG, highlightthickness=0)
        self.prev_canvas.pack(fill='both', expand=True, padx=10, pady=10)

        self.prev_hint = tk.Label(right,
                                   text='썸네일을 클릭하면\n여기에 크게 표시됩니다.\n\n← → 키로 이동',
                                   bg=self.PREV_BG, fg=self.MUTED, font=('맑은 고딕', 11))
        self.prev_hint.place(relx=0.5, rely=0.5, anchor='center')

    def _load_all_thumbs(self):
        """열릴 때 전체 썸네일 한 번에 로드"""
        if self.empty_lbl.winfo_ismapped():
            self.empty_lbl.grid_forget()
        for idx, rgb in enumerate(self.frames):
            self._add_thumb(rgb, idx)

    def _add_thumb(self, rgb, idx):
        img = Image.fromarray(rgb)
        img.thumbnail((self.THUMB_W, self.THUMB_H), Image.LANCZOS)
        photo = ImageTk.PhotoImage(img)
        self._refs.append(photo)
        row, col = divmod(idx, self.COLS)
        cell = tk.Frame(self.gf, bg=self.CARD,
                         highlightthickness=2, highlightbackground=self.DESEL,
                         cursor='hand2')
        cell.grid(row=row, column=col, padx=5, pady=5, sticky='nsew')
        il = tk.Label(cell, image=photo, bg=self.CARD)
        il.pack()
        bot = tk.Frame(cell, bg=self.CARD)
        bot.pack(fill='x', pady=2)
        tk.Label(bot, text=f'#{idx+1}', bg=self.CARD, fg=self.MUTED,
                  font=('Consolas', 8)).pack(side='left', padx=6)
        # 이미 책갈피면 아이콘 표시
        bm_text = '🔖' if idx in self.bookmarks else ''
        bm_lbl = tk.Label(bot, text=bm_text, bg=self.CARD, fg=self.GOLD, font=('Consolas', 9))
        bm_lbl.pack(side='right', padx=4)
        self._cells.append((cell, bm_lbl))
        for w in (cell, il, bot, bm_lbl):
            w.bind('<Button-1>', lambda e, i=idx: self._click_frame(i))

    def _toggle_select_mode(self):
        self.select_mode.set(not self.select_mode.get())
        if self.select_mode.get():
            self.btn_selmode.config(text='☑ 선택하기 ON', bg=self.ACCENT, fg=self.BG)
        else:
            self.btn_selmode.config(text='☐ 선택하기', bg='#2a2a38', fg=self.TEXT)
        self._update_status()

    def _apply_interval(self):
        if not self.frames:
            messagebox.showwarning('알림', '프레임이 없습니다.')
            return
        n = max(1, self.interval_var.get())
        total = len(self.frames)
        self.selected.clear()
        for c, _ in self._cells: c.config(highlightbackground=self.DESEL)
        targets = set(range(0, total, n))
        targets.add(total - 1)
        for i in targets:
            self.selected.add(i)
            if i < len(self._cells):
                self._cells[i][0].config(highlightbackground=self.SEL)
        self._update_status()
        messagebox.showinfo('간격 선택', f'{n}프레임 간격으로 {len(targets)}개 선택됨\n(마지막 프레임 #{total} 포함)')

    def _click_frame(self, idx):
        self._show_preview(idx)
        if self.select_mode.get():
            if idx in self.selected:
                self.selected.discard(idx)
                self._cells[idx][0].config(highlightbackground=self.DESEL)
            else:
                self.selected.add(idx)
                self._cells[idx][0].config(highlightbackground=self.SEL)
            self._update_status()

    def _toggle_bookmark_current(self):
        idx = self._cur_idx
        if idx < 0 or idx >= len(self.frames): return
        if idx in self.bookmarks:
            self.bookmarks.discard(idx)
            if idx < len(self._cells): self._cells[idx][1].config(text='')
            self.btn_bm.config(fg=self.MUTED)
        else:
            self.bookmarks.add(idx)
            if idx < len(self._cells): self._cells[idx][1].config(text='🔖', fg=self.GOLD)
            self.btn_bm.config(fg=self.GOLD)
        self._update_status()

    def _update_status(self):
        mode = '선택 모드 ON ' if self.select_mode.get() else '선택 모드 OFF'
        self.sel_var.set(f'{mode}  |  선택: {len(self.selected)}개  |  책갈피: {len(self.bookmarks)}개')

    def _show_preview(self, idx):
        if idx < 0 or idx >= len(self.frames): return
        self._cur_idx = idx
        self.prev_hint.place_forget()
        rgb = self.frames[idx]
        img = Image.fromarray(rgb)
        self.prev_canvas.update_idletasks()
        cw = max(self.prev_canvas.winfo_width()-20, 100)
        ch = max(self.prev_canvas.winfo_height()-20, 100)
        iw, ih = img.size
        scale = min(cw/iw, ch/ih, 1.0)
        img = img.resize((max(int(iw*scale),1), max(int(ih*scale),1)), Image.LANCZOS)
        self._preview_ref = ImageTk.PhotoImage(img)
        self.prev_canvas.delete('all')
        self.prev_canvas.create_image(cw//2+10, ch//2+10, image=self._preview_ref, anchor='center')
        self.prev_title.config(text=f'#{idx+1} / {len(self.frames)}')
        self.btn_bm.config(fg=self.GOLD if idx in self.bookmarks else self.MUTED)

    def _prev_nav(self, d):
        new = self._cur_idx + d
        if 0 <= new < len(self.frames):
            self._show_preview(new)

    def select_all(self):
        for i in range(len(self.frames)):
            self.selected.add(i)
            if i < len(self._cells): self._cells[i][0].config(highlightbackground=self.SEL)
        self._update_status()

    def deselect_all(self):
        self.selected.clear()
        for c, _ in self._cells: c.config(highlightbackground=self.DESEL)
        self._update_status()

    def save_selected(self):
        if not self.selected:
            messagebox.showwarning('알림', '선택된 프레임이 없습니다.\n선택하기 버튼을 켜고 프레임을 선택하세요.')
            return
        self._save_frames(sorted(self.selected), '선택')

    def save_bookmarks(self):
        if not self.bookmarks:
            messagebox.showwarning('알림', '책갈피된 프레임이 없습니다.\n🔖 버튼으로 책갈피를 추가하세요.')
            return
        self._save_frames(sorted(self.bookmarks), '책갈피')

    def _save_frames(self, indices, label):
        folder = filedialog.askdirectory(title='저장 폴더 선택')
        if not folder: return
        saved = 0
        for idx in indices:
            if idx < len(self.frames):
                Image.fromarray(self.frames[idx]).save(
                    os.path.join(folder, f'frame_{idx+1:04d}.png'))
                saved += 1
        messagebox.showinfo('저장 완료', f'✅ {label} {saved}개 저장 완료\n\n📁 {folder}')


# ──────────────────────────────────────────────────────────────
# 메인 앱 = 영상 재생 화면
# ──────────────────────────────────────────────────────────────
class App:
    BG    = '#0e0e14'
    PANEL = '#18181f'
    CARD  = '#1f1f29'
    ACCENT= '#00FFB3'
    RED   = '#FF4E6A'
    GOLD  = '#FFD700'
    TEXT  = '#e4e4f0'
    MUTED = '#5a5a72'

    def __init__(self):
        self.root = tk.Tk()
        self.root.title('FrameSnap')
        self.root.geometry('960x680')
        self.root.minsize(700, 480)
        self.root.configure(bg=self.BG)

        self.recorder:   Recorder | None         = None
        self.float_ctrl: FloatingControls | None = None
        self.region:     dict | None             = None
        self.fps_var     = tk.IntVar(value=5)
        self.delay_var   = tk.BooleanVar(value=True)
        self.auto_folder = tk.StringVar(value='')

        self.frames:    list = []
        self.bookmarks: set  = set()   # FramePicker와 공유
        self._ref            = None
        self.idx             = 0
        self.playing         = False
        self.speed           = 1.0
        self._after_id       = None
        self.screenshot_count = 0

        self._build()
        if not MSS_AVAILABLE:
            messagebox.showerror('패키지 누락', 'pip install mss 후 다시 실행하세요.')

    def _btn(self, parent, text, cmd, bg=None, fg=None, state='normal', **kw):
        return tk.Button(parent, text=text, command=cmd,
                         bg=bg or self.CARD, fg=fg or self.TEXT,
                         relief='flat', activebackground=bg or self.CARD,
                         activeforeground=fg or self.TEXT,
                         font=('맑은 고딕', 9, 'bold'), padx=10, pady=5,
                         cursor='hand2', state=state, bd=0, **kw)

    def _build(self):
        # ── 탑바 (녹화 컨트롤)
        bar = tk.Frame(self.root, bg=self.PANEL, height=58)
        bar.pack(fill='x')
        bar.pack_propagate(False)

        tk.Label(bar, text='⬛ FrameSnap', bg=self.PANEL, fg=self.ACCENT,
                 font=('Consolas', 14, 'bold')).pack(side='left', padx=16)

        fps_f = tk.Frame(bar, bg=self.PANEL)
        fps_f.pack(side='left', padx=6)
        tk.Label(fps_f, text='FPS', bg=self.PANEL, fg=self.MUTED,
                 font=('Consolas', 9)).pack(side='left')
        tk.Spinbox(fps_f, from_=1, to=30, textvariable=self.fps_var, width=3,
                   bg='#252530', fg=self.TEXT, insertbackground=self.TEXT,
                   relief='flat', font=('Consolas', 12), justify='center',
                   buttonbackground='#252530').pack(side='left', padx=5)

        tk.Checkbutton(bar, text='3초 후 시작', variable=self.delay_var,
                       bg=self.PANEL, fg=self.TEXT, selectcolor='#252530',
                       activebackground=self.PANEL, font=('맑은 고딕', 9),
                       cursor='hand2').pack(side='left', padx=10)

        # 오른쪽: 녹화 + 초기화 + 프레임저장
        self._btn(bar, '🗑  초기화', self.clear_all).pack(side='right', padx=6, pady=10)
        self._btn(bar, '🖼  프레임 저장', self._open_picker,
                  bg='#2a2a50').pack(side='right', padx=4, pady=10)
        self.btn_start = self._btn(bar, '⏺  영역 선택 후 녹화', self.start_recording,
                                    bg=self.ACCENT, fg=self.BG)
        self.btn_start.pack(side='right', padx=4, pady=10)

        # ── 상태바
        sbar = tk.Frame(self.root, bg='#111118', height=24)
        sbar.pack(fill='x')
        sbar.pack_propagate(False)
        self.status_var = tk.StringVar(value='준비됨  –  영역 선택 후 녹화 버튼을 누르세요')
        self.cnt_var    = tk.StringVar(value='프레임 0')
        tk.Label(sbar, textvariable=self.status_var, bg='#111118', fg=self.MUTED,
                 font=('Consolas', 8)).pack(side='left', padx=12)
        tk.Label(sbar, textvariable=self.cnt_var, bg='#111118', fg=self.ACCENT,
                 font=('Consolas', 8, 'bold')).pack(side='right', padx=12)

        # ── 영상 캔버스 (메인)
        self.canvas = tk.Canvas(self.root, bg='#080810', highlightthickness=0)
        self.canvas.pack(fill='both', expand=True, padx=8, pady=(6,0))

        # ── 진행바
        bar_f = tk.Frame(self.root, bg=self.BG)
        bar_f.pack(fill='x', padx=8, pady=4)
        self.progress = ttk.Scale(bar_f, from_=0, to=1, orient='horizontal')
        self.progress.pack(fill='x')
        self.progress.bind('<ButtonRelease-1>', self._on_seek)
        self.progress.bind('<B1-Motion>',       self._on_seek)

        # 프레임 번호 / 스크린샷 카운트
        info_f = tk.Frame(self.root, bg=self.BG)
        info_f.pack(fill='x', padx=10)
        self.frame_lbl = tk.Label(info_f, text='녹화 후 재생 가능합니다',
                                   bg=self.BG, fg=self.MUTED, font=('Consolas', 9))
        self.frame_lbl.pack(side='left')
        self.shot_lbl = tk.Label(info_f, text='', bg=self.BG, fg=self.GOLD,
                                  font=('Consolas', 9, 'bold'))
        self.shot_lbl.pack(side='right')

        # ── 재생 컨트롤 바
        ctrl = tk.Frame(self.root, bg=self.PANEL, height=58)
        ctrl.pack(fill='x', pady=(4,0))
        ctrl.pack_propagate(False)

        # 속도
        spd_f = tk.Frame(ctrl, bg=self.PANEL)
        spd_f.pack(side='left', padx=10, pady=8)
        tk.Label(spd_f, text='속도', bg=self.PANEL, fg=self.MUTED,
                 font=('맑은 고딕', 8)).pack(side='left', padx=(0,4))
        for spd, lbl in [(0.25,'¼x'),(0.5,'½x'),(1.0,'1x'),(2.0,'2x'),(4.0,'4x')]:
            tk.Button(spd_f, text=lbl, command=lambda s=spd: self._set_speed(s),
                      bg='#2a2a38', fg=self.TEXT, relief='flat',
                      font=('Consolas', 8, 'bold'), padx=7, pady=3,
                      cursor='hand2', bd=0).pack(side='left', padx=2)

        # 재생 버튼들
        play_f = tk.Frame(ctrl, bg=self.PANEL)
        play_f.pack(side='left', padx=16, pady=6)
        for txt, cmd in [('⏮', lambda: self._jump(0)),
                          ('◀◀', lambda: self._step(-10)),
                          ('◀',  lambda: self._step(-1))]:
            tk.Button(play_f, text=txt, command=cmd,
                      bg='#2a2a38', fg=self.TEXT, relief='flat',
                      font=('Consolas', 12), padx=8, pady=4,
                      cursor='hand2', bd=0).pack(side='left', padx=2)

        self.btn_play = tk.Button(play_f, text='▶ 재생', command=self._toggle_play,
                                   bg=self.ACCENT, fg=self.BG, relief='flat',
                                   font=('맑은 고딕', 11, 'bold'), padx=16, pady=6,
                                   cursor='hand2', bd=0)
        self.btn_play.pack(side='left', padx=6)

        for txt, cmd in [('▶',  lambda: self._step(1)),
                          ('▶▶', lambda: self._step(10)),
                          ('⏭', lambda: self._jump_end())]:
            tk.Button(play_f, text=txt, command=cmd,
                      bg='#2a2a38', fg=self.TEXT, relief='flat',
                      font=('Consolas', 12), padx=8, pady=4,
                      cursor='hand2', bd=0).pack(side='left', padx=2)

        # 저장폴더 + 📸 스크린샷
        right_f = tk.Frame(ctrl, bg=self.PANEL)
        right_f.pack(side='right', padx=10, pady=6)

        folder_f = tk.Frame(right_f, bg=self.PANEL)
        folder_f.pack(side='top', anchor='e')
        tk.Label(folder_f, text='저장폴더:', bg=self.PANEL, fg=self.MUTED,
                 font=('맑은 고딕', 7)).pack(side='left')
        self.folder_lbl = tk.Label(folder_f, textvariable=self.auto_folder,
                                    bg=self.PANEL, fg=self.TEXT,
                                    font=('Consolas', 7), width=22, anchor='w')
        self.folder_lbl.pack(side='left', padx=3)
        tk.Button(folder_f, text='📁', command=self._change_folder,
                  bg='#2a2a38', fg=self.TEXT, relief='flat',
                  font=('Consolas', 9), padx=4, pady=1,
                  cursor='hand2', bd=0).pack(side='left')

        tk.Button(right_f, text='📸  스크린샷  [S]',
                  command=self._take_screenshot,
                  bg=self.RED, fg='white', relief='flat',
                  font=('맑은 고딕', 11, 'bold'), padx=16, pady=6,
                  cursor='hand2', bd=0).pack(side='bottom', pady=2)

        # 키 바인딩
        self.root.bind('<space>', lambda e: self._toggle_play())
        self.root.bind('<Left>',  lambda e: self._step(-1))
        self.root.bind('<Right>', lambda e: self._step(1))
        self.root.bind('<s>',     lambda e: self._take_screenshot())
        self.root.bind('<S>',     lambda e: self._take_screenshot())

        # 초기 안내 이미지
        self._draw_empty()

    def _draw_empty(self):
        self.canvas.update_idletasks()
        cw = max(self.canvas.winfo_width(), 200)
        ch = max(self.canvas.winfo_height(), 200)
        self.canvas.delete('all')
        self.canvas.create_text(cw//2, ch//2,
                                 text='⏺ 녹화 버튼으로 시작하세요',
                                 fill=self.MUTED, font=('맑은 고딕', 14))

    # ── 재생
    def _show_frame(self):
        if not self.frames: return
        self.idx = max(0, min(self.idx, len(self.frames)-1))
        rgb = self.frames[self.idx]
        img = Image.fromarray(rgb)
        self.canvas.update_idletasks()
        cw = max(self.canvas.winfo_width(), 10)
        ch = max(self.canvas.winfo_height(), 10)
        iw, ih = img.size
        scale = min(cw/iw, ch/ih, 1.0)
        img = img.resize((max(int(iw*scale),1), max(int(ih*scale),1)), Image.LANCZOS)
        self._ref = ImageTk.PhotoImage(img)
        self.canvas.delete('all')
        self.canvas.create_image(cw//2, ch//2, image=self._ref, anchor='center')
        try: self.progress.set(self.idx)
        except: pass
        self.frame_lbl.config(
            text=f'프레임 #{self.idx+1} / {len(self.frames)}   |   Space: 재생/정지   ←→: 이동   S: 스크린샷')

    def _toggle_play(self):
        if not self.frames: return
        self.playing = not self.playing
        if self.playing:
            self.btn_play.config(text='⏸ 일시정지', bg=self.RED, fg='white')
            self._play_loop()
        else:
            self.btn_play.config(text='▶ 재생', bg=self.ACCENT, fg=self.BG)
            if self._after_id:
                try: self.root.after_cancel(self._after_id)
                except: pass

    def _play_loop(self):
        if not self.playing: return
        if self.idx >= len(self.frames) - 1:
            self.idx = len(self.frames) - 1
            self._show_frame()
            self._toggle_play()
            return
        self.idx += 1
        self._show_frame()
        interval = max(int(1000 / (self.speed * 10)), 16)
        self._after_id = self.root.after(interval, self._play_loop)

    def _step(self, d):
        if not self.frames: return
        if self.playing: self._toggle_play()
        self.idx = max(0, min(self.idx + d, len(self.frames)-1))
        self._show_frame()

    def _jump(self, idx):
        if not self.frames: return
        if self.playing: self._toggle_play()
        self.idx = max(0, min(idx, len(self.frames)-1))
        self._show_frame()

    def _jump_end(self):
        self._jump(len(self.frames)-1)

    def _on_seek(self, event=None):
        try:
            self.idx = int(self.progress.get())
            self._show_frame()
        except: pass

    def _set_speed(self, spd):
        self.speed = spd

    # ── 스크린샷
    def _take_screenshot(self):
        if not self.frames: return
        folder = self.auto_folder.get()
        if not folder or not os.path.isdir(folder):
            folder = filedialog.askdirectory(title='스크린샷 저장 폴더 선택')
            if not folder: return
            self.auto_folder.set(folder)
        self.screenshot_count += 1
        path = os.path.join(folder, f'screenshot_{self.screenshot_count:04d}_f{self.idx+1}.png')
        Image.fromarray(self.frames[self.idx]).save(path)
        self.canvas.configure(bg='white')
        self.root.after(80, lambda: self.canvas.configure(bg='#080810'))
        self.shot_lbl.config(text=f'📸 스크린샷 {self.screenshot_count}장 저장됨')
        self.status_var.set(f'📸 저장  →  {path}')

    def _change_folder(self):
        folder = filedialog.askdirectory(title='저장 폴더 선택')
        if folder: self.auto_folder.set(folder)

    # ── 프레임 저장 팝업
    def _open_picker(self):
        if not self.frames:
            messagebox.showwarning('알림', '먼저 녹화를 진행하세요.')
            return
        FramePickerWindow(self.root, self.frames, self.bookmarks)

    # ── 녹화
    def start_recording(self):
        if not MSS_AVAILABLE:
            messagebox.showerror('오류', 'pip install mss 후 재실행하세요.')
            return
        self.root.iconify()
        # 창이 완전히 최소화될 때까지 대기 후 선택 오버레이 열기 (1번 버그 수정)
        self.root.after(400, lambda: RegionSelector(self._on_region))

    def _on_region(self, region):
        self.root.deiconify()
        if region is None: return
        self.region = region
        self.btn_start.config(state='disabled')
        if self.delay_var.get():
            self.status_var.set('3초 후 녹화 시작...')
            Countdown(region, self._begin_recording)
        else:
            self._begin_recording()

    def _begin_recording(self):
        r = self.region
        self.float_ctrl = FloatingControls(r, self.stop_recording)
        self.recorder   = Recorder(r, self.fps_var.get(), self._on_frame,
                                    lambda: self.float_ctrl.paused if self.float_ctrl else False)
        self.status_var.set(f'🔴 녹화 중  –  {r["width"]}×{r["height"]}  |  {self.fps_var.get()} FPS')
        # 진행바 범위 업데이트
        self.progress.configure(to=1)
        self.recorder.start()

    def stop_recording(self):
        if self.recorder:
            self.recorder.stop()
            self.recorder = None
        if self.float_ctrl:
            self.float_ctrl.destroy()
            self.float_ctrl = None
        self.btn_start.config(state='normal')
        total = len(self.frames)
        if total > 1:
            self.progress.configure(to=total-1)
        self.status_var.set(f'녹화 완료  –  총 {total}개 프레임  |  재생 버튼을 누르세요')

    def _on_frame(self, rgb, idx):
        self.frames.append(rgb)
        self.root.after(0, self._on_frame_ui, idx)

    def _on_frame_ui(self, idx):
        self.cnt_var.set(f'프레임 {len(self.frames)}')
        # 녹화 중 최신 프레임 실시간 표시
        self.idx = idx
        self._show_frame()

    # ── 초기화
    def clear_all(self):
        if self.frames and not messagebox.askyesno('초기화', '모든 프레임을 삭제할까요?'):
            return
        if self.recorder: self.stop_recording()
        if self.playing: self._toggle_play()
        self.frames.clear()
        self.bookmarks.clear()
        self.idx = 0
        self.screenshot_count = 0
        self._ref = None
        self.progress.configure(to=1)
        self.progress.set(0)
        self.cnt_var.set('프레임 0')
        self.shot_lbl.config(text='')
        self.status_var.set('초기화됨')
        self.frame_lbl.config(text='녹화 후 재생 가능합니다')
        self._draw_empty()

    def run(self):
        self.root.mainloop()


if __name__ == '__main__':
    App().run()
