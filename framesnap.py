"""
FrameSnap – 화면 녹화 & 프레임 추출기
"""
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import threading, time, os
import numpy as np
from PIL import Image, ImageTk

try:
    import mss
    HAS_MSS = True
except ImportError:
    HAS_MSS = False


# ────────────────────────────────────────────────
# DPI 배율: 앱 시작 시 1회 계산
# ────────────────────────────────────────────────
def get_dpi(root):
    """Windows 물리픽셀 / tkinter 논리픽셀 = DPI 배율"""
    try:
        import ctypes
        phys = ctypes.windll.user32.GetSystemMetrics(0)  # 물리 가로
        logic = root.winfo_screenwidth()                  # 논리 가로
        d = phys / logic if logic > 0 else 1.0
        return d if 0.5 <= d <= 4.0 else 1.0
    except Exception:
        return 1.0


# ────────────────────────────────────────────────
# 녹화 스레드
# ────────────────────────────────────────────────
class Recorder:
    def __init__(self, region, fps, on_frame, paused_fn):
        self.region    = region
        self.fps       = fps
        self.on_frame  = on_frame
        self.paused_fn = paused_fn
        self.running   = False

    def start(self):
        self.running = True
        threading.Thread(target=self._run, daemon=True).start()

    def stop(self):
        self.running = False

    def _run(self):
        interval = 1.0 / self.fps
        idx = 0
        with mss.mss() as sct:
            while self.running:
                t0 = time.perf_counter()
                if not self.paused_fn():
                    raw = sct.grab(self.region)
                    arr = np.frombuffer(raw.raw, dtype=np.uint8
                          ).reshape(raw.height, raw.width, 4)
                    self.on_frame(arr[:, :, [2, 1, 0]], idx)
                    idx += 1
                wait = interval - (time.perf_counter() - t0)
                if wait > 0:
                    time.sleep(wait)


# ────────────────────────────────────────────────
# 3초 카운트다운
# ────────────────────────────────────────────────
class Countdown:
    def __init__(self, region, dpi, on_done):
        self.on_done = on_done
        self.count = 3
        # 물리픽셀 region → tkinter geometry 논리픽셀
        lw = int(region['width']  / dpi)
        lh = int(region['height'] / dpi)
        lx = int(region['left']   / dpi)
        ly = int(region['top']    / dpi)
        self.win = tk.Toplevel()
        self.win.overrideredirect(True)
        self.win.attributes('-topmost', True)
        self.win.attributes('-alpha', 0.7)
        self.win.geometry(f'{lw}x{lh}+{lx}+{ly}')
        self.win.configure(bg='black')
        self.lbl = tk.Label(self.win, text='3', bg='black', fg='#e74c3c',
                             font=('Consolas', min(lh // 2, 160), 'bold'))
        self.lbl.place(relx=0.5, rely=0.4, anchor='center')
        tk.Label(self.win, text='녹화 시작까지...', bg='black', fg='white',
                 font=('맑은 고딕', 12)).place(relx=0.5, rely=0.75, anchor='center')
        self._tick()

    def _tick(self):
        if self.count > 0:
            self.lbl.config(text=str(self.count))
            self.count -= 1
            self.win.after(1000, self._tick)
        else:
            self.win.destroy()
            self.on_done()


# ────────────────────────────────────────────────
# 녹화 중 플로팅 컨트롤 바
# ────────────────────────────────────────────────
class RecBar:
    def __init__(self, region, dpi, on_stop):
        self.paused = False
        # 물리픽셀 → 논리픽셀
        lx = int(region['left']   / dpi)
        ly = int(region['top']    / dpi)
        lw = int(region['width']  / dpi)
        lh = int(region['height'] / dpi)

        # 컨트롤 바
        self.win = tk.Toplevel()
        self.win.overrideredirect(True)
        self.win.attributes('-topmost', True)
        self.win.configure(bg='#1a1a1a')

        frm = tk.Frame(self.win, bg='#1a1a1a')
        frm.pack(padx=8, pady=5)

        self.lbl_rec = tk.Label(frm, text='⏺ REC', bg='#1a1a1a', fg='#e74c3c',
                                 font=('Consolas', 11, 'bold'))
        self.lbl_rec.pack(side='left', padx=6)

        self.btn_pause = tk.Button(frm, text='⏸ 일시정지', command=self._toggle,
                                    bg='#333', fg='white', relief='flat',
                                    font=('맑은 고딕', 10, 'bold'), padx=10, pady=4,
                                    cursor='hand2', bd=0)
        self.btn_pause.pack(side='left', padx=3)

        tk.Button(frm, text='⏹ 중지', command=on_stop,
                  bg='#e74c3c', fg='white', relief='flat',
                  font=('맑은 고딕', 10, 'bold'), padx=12, pady=4,
                  cursor='hand2', bd=0).pack(side='left', padx=3)

        # 창 크기 결정 후 위치 계산
        self.win.update_idletasks()
        bw = frm.winfo_reqwidth() + 16
        bh = frm.winfo_reqheight() + 10
        bx = lx + lw // 2 - bw // 2
        by = ly - bh - 6
        if by < 0:
            by = ly + 4
        self.win.geometry(f'{bw}x{bh}+{bx}+{by}')

        # 드래그
        self._dx = self._dy = 0
        for w in (frm, self.lbl_rec):
            w.bind('<ButtonPress-1>', lambda e: (setattr(self, '_dx', e.x),
                                                  setattr(self, '_dy', e.y)))
            w.bind('<B1-Motion>', lambda e: self.win.geometry(
                f'+{self.win.winfo_x()+e.x-self._dx}+{self.win.winfo_y()+e.y-self._dy}'))

        # 빨간 테두리
        self._borders = []
        b = 3
        for bx2, by2, bw2, bh2 in [
            (lx - b, ly - b, lw + b*2, b),
            (lx - b, ly + lh, lw + b*2, b),
            (lx - b, ly,     b,         lh),
            (lx + lw, ly,    b,         lh),
        ]:
            bwin = tk.Toplevel()
            bwin.overrideredirect(True)
            bwin.attributes('-topmost', True)
            bwin.geometry(f'{max(bw2,1)}x{max(bh2,1)}+{bx2}+{by2}')
            bwin.configure(bg='#e74c3c')
            self._borders.append(bwin)

        self._blink_on = True
        self._blink()

    def _blink(self):
        self._blink_on = not self._blink_on
        c = '#e74c3c' if self._blink_on else '#7b241c'
        try:
            self.lbl_rec.config(fg=c)
            for b in self._borders:
                b.configure(bg=c)
            self.win.after(500, self._blink)
        except Exception:
            pass

    def _toggle(self):
        self.paused = not self.paused
        if self.paused:
            self.btn_pause.config(text='▶ 재개', bg='#00c896', fg='#000')
            self.lbl_rec.config(text='⏸ 일시중지', fg='#888')
        else:
            self.btn_pause.config(text='⏸ 일시정지', bg='#333', fg='white')
            self.lbl_rec.config(text='⏺ REC', fg='#e74c3c')

    def destroy(self):
        try:
            self.win.destroy()
        except Exception:
            pass
        for b in self._borders:
            try:
                b.destroy()
            except Exception:
                pass


# ────────────────────────────────────────────────
# 프레임 선택 팝업
# ────────────────────────────────────────────────
class PickerWindow:
    TW, TH, COLS = 150, 94, 3
    BG   = '#0d0d12'
    CARD = '#1a1a22'
    ACC  = '#00ffb3'
    MUTED= '#505060'
    GOLD = '#ffd700'

    def __init__(self, parent, frames, bookmarks):
        self.frames    = frames
        self.bookmarks = bookmarks
        self.selected  = set()
        self._refs     = []
        self._cells    = []
        self._cur      = -1
        self._pref     = None
        self.sel_mode  = tk.BooleanVar(value=False)
        self.interval  = tk.IntVar(value=5)

        self.win = tk.Toplevel(parent)
        self.win.title('FrameSnap – 프레임 선택')
        self.win.geometry('960x660')
        self.win.configure(bg=self.BG)
        self.win.bind('<Left>',  lambda e: self._nav(-1))
        self.win.bind('<Right>', lambda e: self._nav(1))
        self._build()
        self._load_thumbs()

    def _btn(self, p, t, cmd, bg=None, fg='white', **kw):
        return tk.Button(p, text=t, command=cmd,
                         bg=bg or '#2a2a38', fg=fg, relief='flat',
                         font=('맑은 고딕', 9, 'bold'), padx=9, pady=4,
                         cursor='hand2', bd=0, **kw)

    def _build(self):
        tb = tk.Frame(self.win, bg='#111')
        tb.pack(fill='x')

        self.btn_sm = tk.Button(tb, text='☐ 선택모드', command=self._toggle_sel,
                                 bg='#2a2a38', fg='white', relief='flat',
                                 font=('맑은 고딕', 9, 'bold'), padx=10, pady=5,
                                 cursor='hand2', bd=0)
        self.btn_sm.pack(side='left', padx=8, pady=5)

        tk.Label(tb, text='N간격:', bg='#111', fg=self.MUTED,
                 font=('맑은 고딕', 8)).pack(side='left', padx=(6,2))
        tk.Spinbox(tb, from_=1, to=999, textvariable=self.interval, width=4,
                   bg='#252530', fg='white', relief='flat',
                   font=('Consolas', 9), justify='center').pack(side='left', pady=5)
        self._btn(tb, '적용', self._apply_interval).pack(side='left', padx=3, pady=5)

        sep = tk.Frame(tb, bg='#333', width=1)
        sep.pack(side='left', fill='y', padx=6, pady=3)
        self._btn(tb, '전체선택', self._sel_all).pack(side='left', padx=2, pady=5)
        self._btn(tb, '선택해제', self._desel_all).pack(side='left', padx=2, pady=5)

        sep2 = tk.Frame(tb, bg='#333', width=1)
        sep2.pack(side='left', fill='y', padx=6, pady=3)
        self._btn(tb, '🔖 책갈피 저장', self._save_bm,
                  bg='#3a2e00', fg=self.GOLD).pack(side='left', padx=3, pady=5)
        self._btn(tb, '💾 선택 저장', self._save_sel,
                  bg=self.ACC, fg='#000').pack(side='right', padx=10, pady=5)

        self.stat_var = tk.StringVar(value='선택:0  책갈피:0')
        tk.Label(tb, textvariable=self.stat_var, bg='#111', fg=self.MUTED,
                 font=('맑은 고딕', 8)).pack(side='right', padx=8)

        main = tk.Frame(self.win, bg=self.BG)
        main.pack(fill='both', expand=True)

        # 좌: 썸네일
        lf = tk.Frame(main, bg=self.BG, width=360)
        lf.pack(side='left', fill='both')
        lf.pack_propagate(False)
        gc = tk.Canvas(lf, bg=self.BG, highlightthickness=0)
        vsb = ttk.Scrollbar(lf, orient='vertical', command=gc.yview)
        gc.configure(yscrollcommand=vsb.set)
        vsb.pack(side='right', fill='y')
        gc.pack(fill='both', expand=True)
        self.gf = tk.Frame(gc, bg=self.BG)
        gw = gc.create_window((0, 0), window=self.gf, anchor='nw')
        self.gf.bind('<Configure>',
                      lambda e: gc.configure(scrollregion=gc.bbox('all')))
        gc.bind('<Configure>',
                 lambda e: gc.itemconfig(gw, width=e.width))
        gc.bind_all('<MouseWheel>',
                     lambda e: gc.yview_scroll(int(-e.delta / 120), 'units'))

        # 우: 미리보기
        rf = tk.Frame(main, bg='#0a0a10')
        rf.pack(side='left', fill='both', expand=True)

        rh = tk.Frame(rf, bg='#111', height=34)
        rh.pack(fill='x')
        rh.pack_propagate(False)
        tk.Label(rh, text='미리보기', bg='#111', fg=self.MUTED,
                 font=('맑은 고딕', 9, 'bold')).pack(side='left', padx=10, pady=7)
        self.ptitle = tk.Label(rh, text='', bg='#111', fg=self.ACC,
                                font=('Consolas', 9, 'bold'))
        self.ptitle.pack(side='left')
        self.bm_btn = tk.Button(rh, text='🔖', command=self._toggle_bm,
                                 bg='#111', fg=self.MUTED, relief='flat',
                                 font=('Consolas', 12), padx=4,
                                 cursor='hand2', bd=0)
        self.bm_btn.pack(side='left', padx=3)
        nf = tk.Frame(rh, bg='#111')
        nf.pack(side='right', padx=6)
        for t, d in [('◀', -1), ('▶', 1)]:
            tk.Button(nf, text=t, command=lambda x=d: self._nav(x),
                      bg='#2a2a38', fg='white', relief='flat',
                      font=('Consolas', 10), padx=7, pady=2,
                      cursor='hand2', bd=0).pack(side='left', padx=2)

        self.pcanvas = tk.Canvas(rf, bg='#0a0a10', highlightthickness=0)
        self.pcanvas.pack(fill='both', expand=True, padx=8, pady=8)
        self.pcanvas.bind('<Configure>', lambda e: self._show_preview(self._cur))
        self.phint = tk.Label(rf, text='썸네일을 클릭하면 크게 표시됩니다',
                               bg='#0a0a10', fg=self.MUTED, font=('맑은 고딕', 11))
        self.phint.place(relx=0.5, rely=0.5, anchor='center')

    def _load_thumbs(self):
        for i, rgb in enumerate(self.frames):
            img = Image.fromarray(rgb)
            img.thumbnail((self.TW, self.TH), Image.LANCZOS)
            ph = ImageTk.PhotoImage(img)
            self._refs.append(ph)
            r, c = divmod(i, self.COLS)
            cell = tk.Frame(self.gf, bg=self.CARD,
                             highlightthickness=2,
                             highlightbackground='#2a2a38',
                             cursor='hand2')
            cell.grid(row=r, column=c, padx=3, pady=3, sticky='nsew')
            tk.Label(cell, image=ph, bg=self.CARD).pack()
            bf = tk.Frame(cell, bg=self.CARD)
            bf.pack(fill='x', pady=1)
            tk.Label(bf, text=f'#{i+1}', bg=self.CARD, fg=self.MUTED,
                      font=('Consolas', 7)).pack(side='left', padx=3)
            bml = tk.Label(bf, text='🔖' if i in self.bookmarks else '',
                            bg=self.CARD, fg=self.GOLD, font=('Consolas', 8))
            bml.pack(side='right', padx=2)
            self._cells.append((cell, bml))
            for w in [cell] + cell.winfo_children():
                w.bind('<Button-1>', lambda e, idx=i: self._click(idx))

    def _click(self, i):
        self._show_preview(i)
        if self.sel_mode.get():
            if i in self.selected:
                self.selected.discard(i)
                self._cells[i][0].config(highlightbackground='#2a2a38')
            else:
                self.selected.add(i)
                self._cells[i][0].config(highlightbackground=self.ACC)
            self._upd_stat()

    def _show_preview(self, i):
        if i < 0 or i >= len(self.frames):
            return
        self._cur = i
        self.phint.place_forget()
        img = Image.fromarray(self.frames[i])
        self.pcanvas.update_idletasks()
        cw = max(self.pcanvas.winfo_width() - 10, 50)
        ch = max(self.pcanvas.winfo_height() - 10, 50)
        iw, ih = img.size
        s = min(cw / iw, ch / ih)
        img = img.resize((max(int(iw*s), 1), max(int(ih*s), 1)), Image.LANCZOS)
        self._pref = ImageTk.PhotoImage(img)
        self.pcanvas.delete('all')
        self.pcanvas.create_image(cw // 2 + 5, ch // 2 + 5,
                                   image=self._pref, anchor='center')
        self.ptitle.config(text=f'#{i+1} / {len(self.frames)}')
        self.bm_btn.config(fg=self.GOLD if i in self.bookmarks else self.MUTED)

    def _nav(self, d):
        n = self._cur + d
        if 0 <= n < len(self.frames):
            self._show_preview(n)

    def _toggle_sel(self):
        self.sel_mode.set(not self.sel_mode.get())
        if self.sel_mode.get():
            self.btn_sm.config(text='☑ 선택모드 ON', bg=self.ACC, fg='#000')
        else:
            self.btn_sm.config(text='☐ 선택모드', bg='#2a2a38', fg='white')
        self._upd_stat()

    def _toggle_bm(self):
        i = self._cur
        if i < 0 or i >= len(self.frames):
            return
        if i in self.bookmarks:
            self.bookmarks.discard(i)
            self._cells[i][1].config(text='')
            self.bm_btn.config(fg=self.MUTED)
        else:
            self.bookmarks.add(i)
            self._cells[i][1].config(text='🔖', fg=self.GOLD)
            self.bm_btn.config(fg=self.GOLD)
        self._upd_stat()

    def _apply_interval(self):
        if not self.frames:
            return
        n = max(1, self.interval.get())
        total = len(self.frames)
        self.selected.clear()
        for c, _ in self._cells:
            c.config(highlightbackground='#2a2a38')
        targets = set(range(0, total, n))
        targets.add(total - 1)
        for i in targets:
            self.selected.add(i)
            self._cells[i][0].config(highlightbackground=self.ACC)
        self._upd_stat()

    def _sel_all(self):
        for i in range(len(self.frames)):
            self.selected.add(i)
            self._cells[i][0].config(highlightbackground=self.ACC)
        self._upd_stat()

    def _desel_all(self):
        self.selected.clear()
        for c, _ in self._cells:
            c.config(highlightbackground='#2a2a38')
        self._upd_stat()

    def _upd_stat(self):
        m = 'ON' if self.sel_mode.get() else 'OFF'
        self.stat_var.set(
            f'선택모드:{m}  선택:{len(self.selected)}  책갈피:{len(self.bookmarks)}')

    def _do_save(self, indices, label):
        folder = filedialog.askdirectory(title='저장 폴더')
        if not folder:
            return
        n = 0
        for i in sorted(indices):
            if i < len(self.frames):
                Image.fromarray(self.frames[i]).save(
                    os.path.join(folder, f'frame_{i+1:04d}.png'))
                n += 1
        messagebox.showinfo('저장 완료', f'✅ {label} {n}개 저장\n📁 {folder}')

    def _save_sel(self):
        if not self.selected:
            messagebox.showwarning('알림', '선택된 프레임이 없습니다.')
            return
        self._do_save(self.selected, '선택')

    def _save_bm(self):
        if not self.bookmarks:
            messagebox.showwarning('알림', '책갈피된 프레임이 없습니다.')
            return
        self._do_save(self.bookmarks, '책갈피')


# ────────────────────────────────────────────────
# 메인 앱
# ────────────────────────────────────────────────
class App:
    BG    = '#0d0d12'
    PANEL = '#15151e'
    CARD  = '#1e1e28'
    ACC   = '#00ffb3'
    RED   = '#e74c3c'
    GOLD  = '#ffd700'
    TEXT  = '#dde0ee'
    MUTED = '#50506a'

    def __init__(self):
        self.root = tk.Tk()
        self.root.title('FrameSnap')
        self.root.configure(bg=self.BG)
        self.root.state('zoomed')
        self.root.minsize(700, 500)

        # 상태
        self.dpi          = 1.0
        self.recorder     = None
        self.recbar       = None
        self.region       = None
        self.fps_var      = tk.IntVar(value=5)
        self.delay_var    = tk.BooleanVar(value=True)
        self.frames       = []
        self.bookmarks    = set()
        self.idx          = 0
        self.playing      = False
        self.speed        = 1.0
        self._play_after  = None
        self._img_ref     = None
        self.auto_folder  = tk.StringVar(value='')
        self.filename_var = tk.StringVar(value='screenshot')
        self.shot_count   = 0

        self._build_ui()
        # DPI: 창이 완전히 뜬 후 계산
        self.root.after(200, self._calc_dpi)

        if not HAS_MSS:
            messagebox.showerror('오류', 'pip install mss 를 먼저 실행하세요.')

    def _calc_dpi(self):
        self.dpi = get_dpi(self.root)

    # ── UI ──────────────────────────────────────
    def _btn(self, parent, text, cmd, bg=None, fg=None, **kw):
        return tk.Button(parent, text=text, command=cmd,
                         bg=bg or self.CARD, fg=fg or self.TEXT,
                         relief='flat', activebackground=bg or self.CARD,
                         font=('맑은 고딕', 9, 'bold'), padx=9, pady=5,
                         cursor='hand2', bd=0, **kw)

    def _build_ui(self):
        # 탑바
        top = tk.Frame(self.root, bg=self.PANEL)
        top.pack(fill='x')

        tk.Label(top, text='⬛ FrameSnap', bg=self.PANEL, fg=self.ACC,
                 font=('Consolas', 13, 'bold')).pack(side='left', padx=12, pady=8)

        fps_f = tk.Frame(top, bg=self.PANEL)
        fps_f.pack(side='left', padx=4)
        tk.Label(fps_f, text='FPS', bg=self.PANEL, fg=self.MUTED,
                 font=('Consolas', 8)).pack(side='left')
        tk.Spinbox(fps_f, from_=1, to=30, textvariable=self.fps_var,
                   width=3, bg='#252530', fg=self.TEXT,
                   insertbackground=self.TEXT, relief='flat',
                   font=('Consolas', 10), justify='center',
                   buttonbackground='#252530').pack(side='left', padx=4)

        tk.Checkbutton(top, text='3초 후 시작', variable=self.delay_var,
                       bg=self.PANEL, fg=self.TEXT, selectcolor='#252530',
                       activebackground=self.PANEL,
                       font=('맑은 고딕', 8), cursor='hand2').pack(side='left', padx=8)

        self._btn(top, '🗑 초기화',     self.clear_all).pack(side='right', padx=5, pady=7)
        self._btn(top, '🖼 프레임 저장', self._open_picker,
                  bg='#22224a').pack(side='right', padx=4, pady=7)
        self.btn_rec = self._btn(top, '⏺ 영역 선택 후 녹화',
                                  self.start_recording,
                                  bg=self.ACC, fg='#000')
        self.btn_rec.pack(side='right', padx=4, pady=7)

        # 상태바
        sb = tk.Frame(self.root, bg='#0a0a10', height=20)
        sb.pack(fill='x')
        sb.pack_propagate(False)
        self.stat_var = tk.StringVar(value='준비됨')
        self.cnt_var  = tk.StringVar(value='프레임 0')
        tk.Label(sb, textvariable=self.stat_var,
                 bg='#0a0a10', fg=self.MUTED,
                 font=('Consolas', 8)).pack(side='left', padx=10)
        tk.Label(sb, textvariable=self.cnt_var,
                 bg='#0a0a10', fg=self.ACC,
                 font=('Consolas', 8, 'bold')).pack(side='right', padx=10)

        # 재생 캔버스
        self.canvas = tk.Canvas(self.root, bg='#07070d', highlightthickness=0)
        self.canvas.pack(fill='both', expand=True, padx=6, pady=(4, 0))
        self.canvas.bind('<Configure>', self._on_resize)
        self.canvas.bind('<Button-1>',  lambda e: self.root.focus_set())

        # 진행바
        pf = tk.Frame(self.root, bg=self.BG)
        pf.pack(fill='x', padx=6, pady=(3, 1))
        sty = ttk.Style()
        sty.theme_use('clam')
        sty.configure('FS.Horizontal.TScale',
                       troughcolor='#252530', sliderthickness=14)
        self.progress = ttk.Scale(pf, from_=0, to=1,
                                   orient='horizontal',
                                   style='FS.Horizontal.TScale')
        self.progress.pack(fill='x', ipady=3)
        self.progress.bind('<ButtonRelease-1>', self._seek)
        self.progress.bind('<B1-Motion>',       self._seek)

        info = tk.Frame(self.root, bg=self.BG)
        info.pack(fill='x', padx=10)
        self.frm_lbl = tk.Label(info, text='녹화 후 재생 가능합니다',
                                  bg=self.BG, fg=self.MUTED,
                                  font=('맑은 고딕', 8))
        self.frm_lbl.pack(side='left')
        self.shot_lbl = tk.Label(info, text='', bg=self.BG, fg=self.GOLD,
                                  font=('맑은 고딕', 8, 'bold'))
        self.shot_lbl.pack(side='right')

        # 컨트롤 바 (높이 자동 – pack_propagate 없음)
        ctrl = tk.Frame(self.root, bg=self.PANEL)
        ctrl.pack(fill='x', pady=(2, 0))

        sf = tk.Frame(ctrl, bg=self.PANEL)
        sf.pack(side='left', padx=10, pady=6)
        tk.Label(sf, text='속도', bg=self.PANEL, fg=self.MUTED,
                 font=('맑은 고딕', 8)).pack(side='left', padx=(0, 4))
        for s, lbl in [(0.25, '¼x'), (0.5, '½x'), (1.0, '1x'),
                        (2.0, '2x'), (4.0, '4x')]:
            tk.Button(sf, text=lbl,
                      command=lambda x=s: setattr(self, 'speed', x),
                      bg=self.CARD, fg=self.TEXT, relief='flat',
                      font=('Consolas', 9, 'bold'), padx=8, pady=3,
                      cursor='hand2', bd=0).pack(side='left', padx=2)

        play_f = tk.Frame(ctrl, bg=self.PANEL)
        play_f.pack(side='left', padx=10, pady=5)
        for txt, cmd in [('⏮', lambda: self._jump(0)),
                          ('◀◀', lambda: self._step(-10)),
                          ('◀',  lambda: self._step(-1))]:
            tk.Button(play_f, text=txt, command=cmd,
                      bg=self.CARD, fg=self.TEXT, relief='flat',
                      font=('Consolas', 12), padx=8, pady=4,
                      cursor='hand2', bd=0).pack(side='left', padx=2)

        self.btn_play = tk.Button(play_f, text='▶ 재생',
                                   command=self._toggle_play,
                                   bg=self.ACC, fg='#000', relief='flat',
                                   font=('맑은 고딕', 10, 'bold'),
                                   padx=14, pady=5, cursor='hand2', bd=0)
        self.btn_play.pack(side='left', padx=6)

        for txt, cmd in [('▶',  lambda: self._step(1)),
                          ('▶▶', lambda: self._step(10)),
                          ('⏭', lambda: self._jump(len(self.frames) - 1))]:
            tk.Button(play_f, text=txt, command=cmd,
                      bg=self.CARD, fg=self.TEXT, relief='flat',
                      font=('Consolas', 12), padx=8, pady=4,
                      cursor='hand2', bd=0).pack(side='left', padx=2)

        # 저장 + 스크린샷
        right = tk.Frame(ctrl, bg=self.PANEL)
        right.pack(side='right', padx=10, pady=5)

        cfg = tk.Frame(right, bg=self.PANEL)
        cfg.pack(side='top', anchor='e')
        tk.Label(cfg, text='📁', bg=self.PANEL, fg=self.MUTED,
                 font=('맑은 고딕', 8)).grid(row=0, column=0, sticky='e', padx=(0, 2))
        tk.Label(cfg, textvariable=self.auto_folder,
                 bg='#252530', fg=self.TEXT, font=('Consolas', 8),
                 width=16, anchor='w', padx=3).grid(row=0, column=1)
        self._btn(cfg, '변경', self._chg_folder, bg=self.CARD
                  ).grid(row=0, column=2, padx=(3, 0))

        tk.Label(cfg, text='📄', bg=self.PANEL, fg=self.MUTED,
                 font=('맑은 고딕', 8)).grid(row=1, column=0, sticky='e',
                                              padx=(0, 2), pady=2)
        tk.Entry(cfg, textvariable=self.filename_var,
                 bg='#252530', fg=self.TEXT, insertbackground=self.TEXT,
                 relief='flat', font=('Consolas', 8), width=16
                 ).grid(row=1, column=1, pady=2, ipady=2)
        tk.Label(cfg, text='_0001.png', bg=self.PANEL, fg=self.MUTED,
                 font=('Consolas', 8)).grid(row=1, column=2,
                                             padx=(3, 0), sticky='w')

        tk.Button(right, text='📸 스크린샷  [S]',
                  command=self._screenshot,
                  bg=self.RED, fg='white', relief='flat',
                  font=('맑은 고딕', 9, 'bold'), padx=12, pady=5,
                  cursor='hand2', bd=0).pack(side='bottom', pady=(3, 0))

        # 키 바인딩
        def guard(fn):
            def h(e):
                if isinstance(e.widget, (tk.Entry, tk.Spinbox)):
                    return
                fn()
            return h

        self.root.bind('<space>', guard(self._toggle_play))
        self.root.bind('<Left>',  guard(lambda: self._step(-1)))
        self.root.bind('<Right>', guard(lambda: self._step(1)))
        self.root.bind('<s>',     guard(self._screenshot))
        self.root.bind('<S>',     guard(self._screenshot))

        self._draw_hint()

    def _draw_hint(self):
        self.canvas.update_idletasks()
        cw = max(self.canvas.winfo_width(), 10)
        ch = max(self.canvas.winfo_height(), 10)
        self.canvas.delete('all')
        self.canvas.create_text(cw // 2, ch // 2,
                                 text='⏺  영역 선택 후 녹화 버튼을 누르세요',
                                 fill=self.MUTED, font=('맑은 고딕', 14))

    def _on_resize(self, e=None):
        if self.frames:
            self._show_frame()
        else:
            self._draw_hint()

    def _show_frame(self):
        if not self.frames:
            return
        self.idx = max(0, min(self.idx, len(self.frames) - 1))
        img = Image.fromarray(self.frames[self.idx])
        self.canvas.update_idletasks()
        cw = max(self.canvas.winfo_width(), 10)
        ch = max(self.canvas.winfo_height(), 10)
        iw, ih = img.size
        s = min(cw / iw, ch / ih)
        img = img.resize((max(int(iw*s), 1), max(int(ih*s), 1)),
                          Image.LANCZOS)
        self._img_ref = ImageTk.PhotoImage(img)
        self.canvas.delete('all')
        self.canvas.create_image(cw // 2, ch // 2,
                                  image=self._img_ref, anchor='center')
        try:
            self.progress.set(self.idx)
        except Exception:
            pass
        self.frm_lbl.config(
            text=f'프레임 #{self.idx+1}/{len(self.frames)}'
                 f'  Space:재생/정지  ←→:이동  S:스크린샷')

    # ── 재생 ────────────────────────────────────
    def _toggle_play(self):
        if not self.frames:
            return
        self.playing = not self.playing
        if self.playing:
            self.btn_play.config(text='⏸ 정지', bg=self.RED, fg='white')
            self._play_loop()
        else:
            self.btn_play.config(text='▶ 재생', bg=self.ACC, fg='#000')
            if self._play_after:
                try:
                    self.root.after_cancel(self._play_after)
                except Exception:
                    pass

    def _play_loop(self):
        if not self.playing:
            return
        if self.idx >= len(self.frames) - 1:
            self._toggle_play()
            return
        self.idx += 1
        self._show_frame()
        ms = max(int(1000 / (self.fps_var.get() * self.speed)), 16)
        self._play_after = self.root.after(ms, self._play_loop)

    def _step(self, d):
        if not self.frames:
            return
        if self.playing:
            self._toggle_play()
        self.idx = max(0, min(self.idx + d, len(self.frames) - 1))
        self._show_frame()

    def _jump(self, i):
        if not self.frames:
            return
        if self.playing:
            self._toggle_play()
        self.idx = max(0, min(i, len(self.frames) - 1))
        self._show_frame()

    def _seek(self, e=None):
        try:
            self.idx = int(self.progress.get())
            self._show_frame()
        except Exception:
            pass

    # ── 녹화 ────────────────────────────────────
    def start_recording(self):
        if not HAS_MSS:
            messagebox.showerror('오류', 'pip install mss 를 먼저 실행하세요.')
            return
        self.root.withdraw()
        self.root.after(300, self._sel_region)

    def _sel_region(self):
        dpi = self.dpi  # 앱 시작 시 계산한 값

        sel = tk.Toplevel()
        sel.attributes('-fullscreen', True)   # 현재 모니터에 fullscreen
        sel.attributes('-alpha', 0.35)
        sel.attributes('-topmost', True)
        sel.configure(bg='black')
        sel.lift()
        sel.focus_force()

        canvas = tk.Canvas(sel, cursor='cross',
                            bg='black', highlightthickness=0)
        canvas.pack(fill='both', expand=True)

        tk.Label(sel,
                 text='드래그하여 녹화 영역을 선택하세요  [ ESC = 취소 ]',
                 bg='black', fg='white',
                 font=('맑은 고딕', 14, 'bold')).place(
            relx=0.5, rely=0.05, anchor='center')

        size_lbl = tk.Label(sel, text='', bg='#c0392b', fg='white',
                             font=('Consolas', 11, 'bold'), padx=8, pady=3)

        st = {'sx': 0, 'sy': 0, 'rect': None}

        def press(e):
            st['sx'], st['sy'] = e.x, e.y
            st['rect'] = canvas.create_rectangle(
                e.x, e.y, e.x, e.y, outline='#e74c3c', width=3)

        def drag(e):
            canvas.coords(st['rect'], st['sx'], st['sy'], e.x, e.y)
            w = int(abs(e.x - st['sx']) * dpi)
            h = int(abs(e.y - st['sy']) * dpi)
            size_lbl.config(text=f'  {w} × {h}  ')
            lx = min(e.x + 10, sel.winfo_width() - 150)
            ly = min(e.y + 10, sel.winfo_height() - 35)
            size_lbl.place(x=lx, y=ly)

        def release(e):
            x1 = min(st['sx'], e.x)
            y1 = min(st['sy'], e.y)
            x2 = max(st['sx'], e.x)
            y2 = max(st['sy'], e.y)
            sel.destroy()
            self.root.deiconify()
            if x2 - x1 > 10 and y2 - y1 > 10:
                # tkinter 논리좌표 * dpi = mss 물리좌표
                self._on_region({
                    'left':   int(x1 * dpi),
                    'top':    int(y1 * dpi),
                    'width':  int((x2 - x1) * dpi),
                    'height': int((y2 - y1) * dpi),
                })
            else:
                self._on_region(None)

        def cancel(e=None):
            sel.destroy()
            self.root.deiconify()
            self._on_region(None)

        canvas.bind('<ButtonPress-1>',   press)
        canvas.bind('<B1-Motion>',       drag)
        canvas.bind('<ButtonRelease-1>', release)
        sel.bind('<Escape>',             cancel)

    def _on_region(self, region):
        self.root.deiconify()
        if region is None:
            return
        self.region = region
        self.btn_rec.config(state='disabled')
        if self.delay_var.get():
            self.stat_var.set('3초 후 녹화 시작...')
            Countdown(region, self.dpi, self._begin_rec)
        else:
            self._begin_rec()

    def _begin_rec(self):
        r = self.region
        self.recbar = RecBar(r, self.dpi, self.stop_recording)
        self.recorder = Recorder(
            r, self.fps_var.get(), self._on_frame,
            lambda: self.recbar.paused if self.recbar else False)
        self.progress.configure(to=max(1, len(self.frames)))
        self.stat_var.set(
            f'🔴 녹화 중 – {r["width"]}×{r["height"]}  |  {self.fps_var.get()} FPS')
        self.recorder.start()

    def stop_recording(self):
        if self.recorder:
            self.recorder.stop()
            self.recorder = None
        if self.recbar:
            self.recbar.destroy()
            self.recbar = None
        self.btn_rec.config(state='normal')
        n = len(self.frames)
        if n > 1:
            self.progress.configure(to=n - 1)
        self.stat_var.set(f'녹화 완료 – 총 {n}개 프레임')

    def _on_frame(self, rgb, idx):
        self.frames.append(rgb)
        self.root.after(0, self._on_frame_ui, idx)

    def _on_frame_ui(self, idx):
        self.cnt_var.set(f'프레임 {len(self.frames)}')
        self.idx = idx
        self._show_frame()

    # ── 스크린샷 ─────────────────────────────────
    def _screenshot(self):
        if not self.frames:
            return
        folder = self.auto_folder.get()
        if not folder or not os.path.isdir(folder):
            folder = filedialog.askdirectory(title='저장 폴더')
            if not folder:
                return
            self.auto_folder.set(folder)
        self.shot_count += 1
        base = self.filename_var.get().strip() or 'screenshot'
        base = ''.join(c if c not in r'\/:*?"<>|' else '_' for c in base)
        path = os.path.join(folder, f'{base}_{self.shot_count:04d}.png')
        Image.fromarray(self.frames[self.idx]).save(path)
        self.canvas.configure(bg='white')
        self.root.after(60, lambda: self.canvas.configure(bg='#07070d'))
        self.shot_lbl.config(text=f'📸 {self.shot_count}장')
        self.stat_var.set(f'📸 저장 → {path}')

    def _chg_folder(self):
        f = filedialog.askdirectory()
        if f:
            self.auto_folder.set(f)

    def _open_picker(self):
        if not self.frames:
            messagebox.showwarning('알림', '먼저 녹화를 진행하세요.')
            return
        PickerWindow(self.root, self.frames, self.bookmarks)

    def clear_all(self):
        if self.frames and not messagebox.askyesno(
                '초기화', '모든 프레임을 삭제할까요?'):
            return
        if self.recorder:
            self.stop_recording()
        if self.playing:
            self._toggle_play()
        self.frames.clear()
        self.bookmarks.clear()
        self.idx = 0
        self.shot_count = 0
        self._img_ref = None
        self.progress.configure(to=1)
        self.progress.set(0)
        self.cnt_var.set('프레임 0')
        self.shot_lbl.config(text='')
        self.stat_var.set('초기화됨')
        self.frm_lbl.config(text='녹화 후 재생 가능합니다')
        self._draw_hint()

    def run(self):
        self.root.mainloop()


if __name__ == '__main__':
    App().run()
