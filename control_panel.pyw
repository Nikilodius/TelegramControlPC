"""
Telegram PC Control — Панель управления.

Графическое окно для:
- смены BOT_TOKEN / ALLOWED_USER_ID / APP_PASSWORD / MINI_APP_URL (пишет их в .env)
- запуска/остановки bot.py в фоне (без окна консоли)
- сворачивания в системный трей
- включения автозапуска вместе с Windows

Запускать через pythonw.exe (или дважды кликнуть ControlPanel.vbs),
чтобы не мелькало окно консоли.
"""

import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import tkinter as tk
from tkinter import messagebox, ttk

try:
    from PIL import Image, ImageDraw, ImageTk
except Exception:
    Image = None
    ImageDraw = None
    ImageTk = None

try:
    import pystray
except Exception:
    pystray = None

# ---------------------------------------------------------------- пути/константы

BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR / ".env"
ENV_EXAMPLE_PATH = BASE_DIR / ".env.example"
BOT_SCRIPT = BASE_DIR / "bot.py"
PID_FILE = BASE_DIR / "bot.pid"
LOG_FILE = BASE_DIR / "bot.log"
ICON_PATH = BASE_DIR / "app_icon.ico"

VENV_PYTHONW = BASE_DIR / ".venv" / "Scripts" / "pythonw.exe"
VENV_PYTHON = BASE_DIR / ".venv" / "Scripts" / "python.exe"

STARTUP_DIR = Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
STARTUP_VBS = STARTUP_DIR / "TelegramPCControl.vbs"

CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# ---------------------------------------------------------------- тема

BG = "#0e0e16"
CARD_BG = "#1a1a26"
INPUT_BG = "#26263a"
TEXT = "#eef0fb"
MUTED = "#8a8aa3"
ACCENT = "#8b7cff"
ACCENT_LIGHT = "#a698ff"
ACCENT_DARK = "#6f5fe0"
GREEN = "#4ade80"
RED = "#f87171"
FONT = "Segoe UI"
RADIUS = 16


# ================================================================== .env helpers

def read_env():
    values = {}
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            k, _, v = stripped.partition("=")
            values[k.strip()] = v.strip()
    return values


def write_env(updates: dict):
    if not ENV_PATH.exists() and ENV_EXAMPLE_PATH.exists():
        ENV_PATH.write_text(ENV_EXAMPLE_PATH.read_text(encoding="utf-8"), encoding="utf-8")

    lines = ENV_PATH.read_text(encoding="utf-8").splitlines() if ENV_PATH.exists() else []
    seen = set()
    new_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in updates:
                new_lines.append(f"{key}={updates[key]}")
                seen.add(key)
                continue
        new_lines.append(line)

    for key, val in updates.items():
        if key not in seen:
            new_lines.append(f"{key}={val}")

    ENV_PATH.write_text("\n".join(new_lines) + "\n", encoding="utf-8")


# ================================================================== процесс бота

def python_hidden_exe():
    if VENV_PYTHONW.exists():
        return str(VENV_PYTHONW)
    return "pythonw"


def read_pid():
    if PID_FILE.exists():
        try:
            return int(PID_FILE.read_text(encoding="utf-8").strip())
        except ValueError:
            return None
    return None


def is_running():
    pid = read_pid()
    if pid is None:
        return False
    try:
        out = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}"],
            capture_output=True, text=True, creationflags=CREATE_NO_WINDOW,
        )
        return str(pid) in out.stdout
    except Exception:
        return False


def start_bot():
    if is_running():
        return
    with open(LOG_FILE, "a", encoding="utf-8") as log:
        log.write(f"\n--- запуск {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n")
        log.flush()
        proc = subprocess.Popen(
            [python_hidden_exe(), str(BOT_SCRIPT)],
            cwd=str(BASE_DIR),
            stdout=log, stderr=log,
            creationflags=CREATE_NO_WINDOW,
        )
    PID_FILE.write_text(str(proc.pid), encoding="utf-8")


def stop_bot():
    pid = read_pid()
    if pid is not None:
        try:
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/F"],
                capture_output=True, creationflags=CREATE_NO_WINDOW,
            )
        except Exception:
            pass
    try:
        PID_FILE.unlink(missing_ok=True)
    except Exception:
        pass


# ================================================================== автозапуск с Windows

def autostart_enabled():
    return STARTUP_VBS.exists()


def set_autostart(enabled: bool):
    if enabled:
        content = (
            'Set objShell = CreateObject("WScript.Shell")\n'
            f'objShell.Run """{VENV_PYTHONW}"" ""{BASE_DIR / "control_panel.pyw"}""", 0, False\n'
        )
        STARTUP_DIR.mkdir(parents=True, exist_ok=True)
        STARTUP_VBS.write_text(content, encoding="utf-8")
    else:
        try:
            STARTUP_VBS.unlink(missing_ok=True)
        except Exception:
            pass


# ================================================================== мелкие анимационные утилиты

def _clamp(v, lo=0, hi=255):
    return max(lo, min(hi, int(v)))


def _lerp_color(c1, c2, t):
    """t от 0 до 1: линейно смешивает два HEX-цвета."""
    c1 = c1.lstrip("#")
    c2 = c2.lstrip("#")
    r1, g1, b1 = int(c1[0:2], 16), int(c1[2:4], 16), int(c1[4:6], 16)
    r2, g2, b2 = int(c2[0:2], 16), int(c2[2:4], 16), int(c2[4:6], 16)
    r = _clamp(r1 + (r2 - r1) * t)
    g = _clamp(g1 + (g2 - g1) * t)
    b = _clamp(b1 + (b2 - b1) * t)
    return f"#{r:02x}{g:02x}{b:02x}"


def animate(root, duration_ms, on_step, steps=14, on_done=None):
    """Простой планировщик анимации: вызывает on_step(t) от 0.0 до 1.0."""
    interval = max(10, duration_ms // steps)

    def _step(i):
        t = min(1.0, i / steps)
        try:
            on_step(t)
        except tk.TclError:
            return
        if i < steps:
            root.after(interval, _step, i + 1)
        elif on_done:
            on_done()

    _step(0)


def round_rect_points(x1, y1, x2, y2, r):
    r = min(r, (x2 - x1) / 2, (y2 - y1) / 2)
    if r < 0:
        r = 0
    return [
        x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r,
        x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2,
        x1, y2, x1, y2 - r, x1, y1 + r, x1, y1,
    ]


# ================================================================== виджеты

class RoundedCard:
    """Карточка со скруглёнными углами: Canvas с полигоном-фоном + вложенный Frame
    поверх него для обычных tk-виджетов."""

    def __init__(self, parent, bg=CARD_BG, radius=RADIUS, pad=18):
        self.bg_root = parent["bg"] if "bg" in parent.keys() else BG
        self.canvas = tk.Canvas(parent, bg=self.bg_root, highlightthickness=0, height=10)
        self.canvas.pack(fill="x", padx=24, pady=(0, 16))
        self.card_bg = bg
        self.radius = radius
        self.pad = pad
        self.inner = tk.Frame(self.canvas, bg=bg)
        self.inner_id = self.canvas.create_window(pad, pad // 2, window=self.inner, anchor="nw")
        self.inner.bind("<Configure>", self._on_inner_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)

    def _redraw(self, width, height):
        self.canvas.delete("bg")
        if width > 4 and height > 4:
            pts = round_rect_points(1, 1, width - 1, height - 1, self.radius)
            self.canvas.create_polygon(pts, smooth=True, fill=self.card_bg, outline="", tags="bg")
            self.canvas.tag_lower("bg")

    def _on_inner_configure(self, _event=None):
        h = self.inner.winfo_reqheight() + self.pad
        self.canvas.config(height=h)
        self.canvas.coords(self.inner_id, self.pad, self.pad // 2)
        self._redraw(self.canvas.winfo_width(), h)

    def _on_canvas_configure(self, event):
        h = self.inner.winfo_reqheight() + self.pad
        self.canvas.coords(self.inner_id, self.pad, self.pad // 2)
        self._redraw(event.width, h)


class AnimatedButton(tk.Canvas):
    """Кнопка со скруглёнными углами и плавным переходом цвета при наведении/нажатии."""

    def __init__(self, parent, text, command, bg=ACCENT, hover=ACCENT_LIGHT, fg="#0e0e16",
                 height=42, font=(FONT, 11, "bold"), root_for_anim=None):
        super().__init__(parent, height=height, highlightthickness=0, bg=parent["bg"])
        self.command = command
        self.bg_color = bg
        self.hover_color = hover
        self.fg = fg
        self.text = text
        self.font = font
        self.height = height
        self.root_for_anim = root_for_anim or parent
        self._cur_color = bg
        self.pack(fill="x")
        self.bind("<Configure>", lambda e: self._redraw())
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Button-1>", lambda e: self.command())
        self.config(cursor="hand2")
        self.after(10, self._redraw)

    def set_colors(self, bg, hover):
        self.bg_color = bg
        self.hover_color = hover
        self._cur_color = bg
        self._redraw()

    def set_text(self, text):
        self.text = text
        self._redraw()

    def _redraw(self):
        w = self.winfo_width() or 400
        self.delete("all")
        pts = round_rect_points(1, 1, w - 1, self.height - 1, self.height / 2.2)
        self.create_polygon(pts, smooth=True, fill=self._cur_color, outline="")
        self.create_text(w / 2, self.height / 2, text=self.text, fill=self.fg, font=self.font)

    def _on_enter(self, _e):
        animate(self.root_for_anim, 120, lambda t: self._set_color(_lerp_color(self.bg_color, self.hover_color, t)))

    def _on_leave(self, _e):
        animate(self.root_for_anim, 120, lambda t: self._set_color(_lerp_color(self.hover_color, self.bg_color, t)))

    def _set_color(self, color):
        self._cur_color = color
        self._redraw()


class ToggleSwitch(tk.Canvas):
    """Анимированный тумблер вкл/выкл, как в мобильных приложениях."""

    W, H = 46, 24

    def __init__(self, parent, initial=False, command=None):
        super().__init__(parent, width=self.W, height=self.H, highlightthickness=0, bg=parent["bg"])
        self.command = command
        self.state = bool(initial)
        self._knob_x = (self.W - self.H / 2 - 2) if self.state else (self.H / 2 + 2)
        self.bind("<Button-1>", self._on_click)
        self.config(cursor="hand2")
        self._draw(self.state)

    def _draw(self, on):
        self.delete("all")
        track_color = GREEN if on else "#3a3a4d"
        pts = round_rect_points(1, 1, self.W - 1, self.H - 1, self.H / 2)
        self.create_polygon(pts, smooth=True, fill=track_color, outline="")
        r = self.H / 2 - 3
        self.create_oval(self._knob_x - r, self.H / 2 - r, self._knob_x + r, self.H / 2 + r,
                          fill="#ffffff", outline="")

    def _on_click(self, _e):
        self.set(not self.state, animated=True)
        if self.command:
            self.command(self.state)

    def set(self, value, animated=False):
        self.state = bool(value)
        target_x = (self.W - self.H / 2 - 2) if self.state else (self.H / 2 + 2)
        if not animated:
            self._knob_x = target_x
            self._draw(self.state)
            return
        start_x = self._knob_x

        def step(t):
            self._knob_x = start_x + (target_x - start_x) * t
            self._draw(self.state)

        animate(self, 140, step)


# ================================================================== главное окно

class ControlPanel:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Telegram PC Control")
        self.root.geometry("480x780")
        self.root.minsize(480, 780)
        self.root.configure(bg=BG)
        self.root.protocol("WM_DELETE_WINDOW", self.hide_window)
        if ICON_PATH.exists():
            try:
                self.root.iconbitmap(str(ICON_PATH))
            except Exception:
                pass

        try:
            self.root.attributes("-alpha", 0.0)
        except tk.TclError:
            pass

        self._header_icon_ref = None
        self._pulse_phase = 0.0

        self._build_style()
        self._build_ui()
        self.tray_icon = self._build_tray()
        self.refresh_status()
        self._fade_in()
        self._animate_pulse()

    # ---- стиль

    def _build_style(self):
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass

    def _header_icon_image(self):
        if Image is None or ImageTk is None or not ICON_PATH.exists():
            return None
        try:
            img = Image.open(ICON_PATH).convert("RGBA").resize((40, 40), Image.LANCZOS)
            return ImageTk.PhotoImage(img)
        except Exception:
            return None

    def _enable_clipboard(self, entry):
        """Копирование/вставка/вырезание работают всегда, даже на русской раскладке
        (Tk по умолчанию привязывает Ctrl+V к латинской 'v', а не к физической клавише —
        поэтому используем keycode, который от раскладки не зависит)."""

        def on_key(event):
            ctrl_pressed = bool(event.state & 0x0004)
            if not ctrl_pressed:
                return None
            if event.keycode == 86:  # V
                entry.event_generate("<<Paste>>")
                return "break"
            if event.keycode == 67:  # C
                entry.event_generate("<<Copy>>")
                return "break"
            if event.keycode == 88:  # X
                entry.event_generate("<<Cut>>")
                return "break"
            if event.keycode == 65:  # A
                entry.selection_range(0, "end")
                return "break"
            return None

        entry.bind("<Key>", on_key, add="+")

        menu = tk.Menu(
            entry, tearoff=0, bg=CARD_BG, fg=TEXT,
            activebackground=ACCENT, activeforeground="#0e0e16",
            bd=0, font=(FONT, 10),
        )
        menu.add_command(label="Вырезать", command=lambda: entry.event_generate("<<Cut>>"))
        menu.add_command(label="Копировать", command=lambda: entry.event_generate("<<Copy>>"))
        menu.add_command(label="Вставить", command=lambda: entry.event_generate("<<Paste>>"))
        menu.add_separator()
        menu.add_command(label="Выделить всё", command=lambda: entry.selection_range(0, "end"))

        def show_menu(event):
            try:
                menu.tk_popup(event.x_root, event.y_root)
            finally:
                menu.grab_release()

        entry.bind("<Button-3>", show_menu)

    def _field(self, parent, label_text, initial="", secret=False):
        wrap = tk.Frame(parent, bg=CARD_BG)
        wrap.pack(fill="x", pady=(0, 12))
        tk.Label(wrap, text=label_text, bg=CARD_BG, fg=MUTED, font=(FONT, 9)).pack(anchor="w")
        row = tk.Frame(wrap, bg=CARD_BG)
        row.pack(fill="x", pady=(4, 0))
        entry = tk.Entry(
            row, bg=INPUT_BG, fg=TEXT, insertbackground=TEXT, relief="flat",
            font=(FONT, 11), show=("•" if secret else ""),
            highlightthickness=1, highlightbackground=INPUT_BG, highlightcolor=ACCENT,
        )
        entry.insert(0, initial)
        entry.pack(side="left", fill="x", expand=True, ipady=7, padx=(0, 6))
        self._enable_clipboard(entry)
        if secret:
            state = {"shown": False}

            def toggle():
                state["shown"] = not state["shown"]
                entry.config(show=("" if state["shown"] else "•"))
                btn.config(text=("🙈" if state["shown"] else "👁"))

            btn = tk.Button(
                row, text="👁", command=toggle, bg=CARD_BG, fg=TEXT,
                activebackground=CARD_BG, activeforeground=TEXT,
                relief="flat", bd=0, font=(FONT, 11), cursor="hand2",
            )
            btn.pack(side="left")
        return entry

    # ---- разметка

    def _build_ui(self):
        header = tk.Frame(self.root, bg=BG)
        header.pack(fill="x", padx=24, pady=(22, 10))
        icon_img = self._header_icon_image()
        if icon_img is not None:
            self._header_icon_ref = icon_img  # держим ссылку, иначе GC соберёт картинку
            tk.Label(header, image=icon_img, bg=BG).pack(side="left", padx=(0, 10))
        title_box = tk.Frame(header, bg=BG)
        title_box.pack(side="left")
        tk.Label(title_box, text="Telegram PC Control", bg=BG, fg=TEXT,
                 font=(FONT, 17, "bold")).pack(anchor="w")
        tk.Label(title_box, text="Панель управления ботом", bg=BG, fg=MUTED,
                 font=(FONT, 10)).pack(anchor="w")

        # -- статус
        status_card = RoundedCard(self.root).inner
        row = tk.Frame(status_card, bg=CARD_BG)
        row.pack(fill="x")
        self.status_dot = tk.Canvas(row, width=18, height=18, bg=CARD_BG, highlightthickness=0)
        self.status_dot.pack(side="left", padx=(0, 8))
        self.status_glow = self.status_dot.create_oval(1, 1, 17, 17, fill=CARD_BG, outline="")
        self.status_dot_item = self.status_dot.create_oval(4, 4, 14, 14, fill=RED, outline="")
        self.status_label = tk.Label(row, text="Бот остановлен", bg=CARD_BG, fg=TEXT, font=(FONT, 11, "bold"))
        self.status_label.pack(side="left")

        btn_wrap = tk.Frame(status_card, bg=CARD_BG)
        btn_wrap.pack(fill="x", pady=(14, 0))
        self.toggle_btn = AnimatedButton(btn_wrap, "▶  Запустить бота", self.on_toggle_bot,
                                          bg=ACCENT, hover=ACCENT_LIGHT, fg="#0e0e16",
                                          root_for_anim=self.root)

        # -- настройки
        settings_header = tk.Frame(self.root, bg=BG)
        settings_header.pack(fill="x", padx=24, pady=(4, 0))
        tk.Label(settings_header, text="НАСТРОЙКИ", bg=BG, fg=MUTED,
                 font=(FONT, 10, "bold")).pack(anchor="w")

        settings_card = RoundedCard(self.root).inner
        env = read_env()
        self.token_entry = self._field(settings_card, "TELEGRAM BOT TOKEN", env.get("BOT_TOKEN", ""), secret=True)
        self.uid_entry = self._field(settings_card, "РАЗРЕШЁННЫЙ TELEGRAM USER ID", env.get("ALLOWED_USER_ID", ""))
        self.pwd_entry = self._field(settings_card, "ПАРОЛЬ ДОСТУПА (APP_PASSWORD)", env.get("APP_PASSWORD", "fura"), secret=True)
        self.miniapp_entry = self._field(settings_card, "MINI APP URL (необязательно)", env.get("MINI_APP_URL", ""))

        save_wrap = tk.Frame(settings_card, bg=CARD_BG)
        save_wrap.pack(fill="x", pady=(4, 0))
        AnimatedButton(save_wrap, "💾  Сохранить настройки", self.on_save,
                        bg="#2a2a3d", hover="#34344a", fg=TEXT, root_for_anim=self.root)

        tk.Label(settings_card, text="Изменения применятся при следующем запуске бота",
                 bg=CARD_BG, fg=MUTED, font=(FONT, 8)).pack(anchor="w", pady=(10, 0))

        # -- автозапуск
        auto_card = RoundedCard(self.root).inner
        auto_row = tk.Frame(auto_card, bg=CARD_BG)
        auto_row.pack(fill="x")
        tk.Label(auto_row, text="Запускать при старте Windows", bg=CARD_BG, fg=TEXT,
                 font=(FONT, 10)).pack(side="left")
        self.autostart_switch = ToggleSwitch(auto_row, initial=autostart_enabled(),
                                              command=self.on_toggle_autostart)
        self.autostart_switch.pack(side="right")

        # -- футер
        footer = tk.Frame(self.root, bg=BG)
        footer.pack(fill="x", padx=24, pady=(4, 16))
        tk.Button(
            footer, text="Свернуть в трей", command=self.hide_window,
            bg=BG, fg=MUTED, activebackground=BG, activeforeground=TEXT,
            relief="flat", bd=0, font=(FONT, 9, "underline"), cursor="hand2",
        ).pack(anchor="w")

    # ---- трей

    def _build_tray(self):
        if pystray is None or Image is None:
            return None
        if ICON_PATH.exists():
            img = Image.open(ICON_PATH).convert("RGBA").resize((64, 64))
        else:
            img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
            d = ImageDraw.Draw(img)
            d.ellipse((2, 2, 62, 62), fill=ACCENT)
            d.ellipse((10, 10, 54, 54), fill=(28, 28, 40, 255))
            d.text((20, 20), "TC", fill=ACCENT)

        menu = pystray.Menu(
            pystray.MenuItem("Открыть панель", lambda: self.root.after(0, self.show_window), default=True),
            pystray.MenuItem("Запустить/остановить бота", lambda: self.root.after(0, self.on_toggle_bot)),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Выход", lambda: self.root.after(0, self.quit_app)),
        )
        icon = pystray.Icon("telegram_pc_control", img, "Telegram PC Control", menu)
        threading.Thread(target=icon.run, daemon=True).start()
        return icon

    def show_window(self):
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()
        self._fade_in()

    def hide_window(self):
        self.root.withdraw()

    def quit_app(self):
        if self.tray_icon is not None:
            try:
                self.tray_icon.stop()
            except Exception:
                pass
        self.root.destroy()

    # ---- анимации окна

    def _fade_in(self):
        try:
            animate(self.root, 220, lambda t: self.root.attributes("-alpha", t), steps=12)
        except tk.TclError:
            pass

    def _animate_pulse(self):
        """Лёгкое 'дыхание' у индикатора статуса, когда бот запущен."""
        import math
        self._pulse_phase += 0.18
        try:
            if is_running():
                t = (math.sin(self._pulse_phase) + 1) / 2  # 0..1
                glow = _lerp_color(CARD_BG, GREEN, 0.18 + 0.22 * t)
                self.status_dot.itemconfig(self.status_glow, fill=glow)
            else:
                self.status_dot.itemconfig(self.status_glow, fill=CARD_BG)
        except tk.TclError:
            pass
        self.root.after(60, self._animate_pulse)

    # ---- действия

    def on_toggle_bot(self):
        if is_running():
            stop_bot()
        else:
            env = read_env()
            if not env.get("BOT_TOKEN") or not env.get("ALLOWED_USER_ID"):
                messagebox.showerror("Нет настроек", "Сначала заполни и сохрани Bot Token и Telegram User ID.")
                return
            start_bot()
        self.root.after(500, self.refresh_status)

    def on_save(self):
        token = self.token_entry.get().strip()
        uid = self.uid_entry.get().strip()
        pwd = self.pwd_entry.get().strip()
        miniapp = self.miniapp_entry.get().strip()

        if not token:
            messagebox.showerror("Ошибка", "Bot Token не может быть пустым.")
            return
        if not uid.isdigit():
            messagebox.showerror("Ошибка", "Telegram User ID должен быть числом.")
            return
        if not pwd:
            messagebox.showerror("Ошибка", "Пароль не может быть пустым.")
            return
        if miniapp and not miniapp.lower().startswith("https://"):
            messagebox.showerror("Ошибка", "Mini App URL должен начинаться с https://")
            return

        write_env({
            "BOT_TOKEN": token, "ALLOWED_USER_ID": uid,
            "APP_PASSWORD": pwd, "MINI_APP_URL": miniapp,
        })
        messagebox.showinfo("Сохранено", "Настройки сохранены.\nЕсли бот уже запущен — перезапусти его, чтобы применить изменения.")

    def on_toggle_autostart(self, value):
        set_autostart(value)

    # ---- статус

    def refresh_status(self):
        running = is_running()
        if running:
            self.status_dot.itemconfig(self.status_dot_item, fill=GREEN)
            self.status_label.config(text="Бот запущен (в фоне)")
            self.toggle_btn.set_text("⏹  Остановить бота")
            self.toggle_btn.set_colors("#2a2a3d", "#34344a")
            self.toggle_btn.fg = TEXT
        else:
            self.status_dot.itemconfig(self.status_dot_item, fill=RED)
            self.status_label.config(text="Бот остановлен")
            self.toggle_btn.set_text("▶  Запустить бота")
            self.toggle_btn.set_colors(ACCENT, ACCENT_LIGHT)
            self.toggle_btn.fg = "#0e0e16"
        self.toggle_btn._redraw()
        self.root.after(2000, self.refresh_status)

    def run(self):
        self.root.mainloop()


def main():
    # если запускают control_panel в первый раз без .env — подготовим его из примера
    if not ENV_PATH.exists() and ENV_EXAMPLE_PATH.exists():
        ENV_PATH.write_text(ENV_EXAMPLE_PATH.read_text(encoding="utf-8"), encoding="utf-8")

    app = ControlPanel()
    if "--autostart" in sys.argv:
        app.hide_window()
        env = read_env()
        if env.get("BOT_TOKEN") and env.get("ALLOWED_USER_ID"):
            start_bot()
    app.run()


if __name__ == "__main__":
    main()
