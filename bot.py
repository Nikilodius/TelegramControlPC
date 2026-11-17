import asyncio
import ctypes
import json
import os
import platform
import socket
import subprocess
import tempfile
import time
import urllib.request
from datetime import timedelta
from pathlib import Path

from dotenv import load_dotenv
from telegram import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto, Update, WebAppInfo
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# ---- Низкоуровневые Windows API вызовы через ctypes (без доп. зависимостей) ----
user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_WHEEL = 0x0800

VK_MEDIA_NEXT_TRACK = 0xB0
VK_MEDIA_PREV_TRACK = 0xB1
VK_MEDIA_PLAY_PAUSE = 0xB3
VK_VOLUME_MUTE = 0xAD
VK_VOLUME_DOWN = 0xAE
VK_VOLUME_UP = 0xAF
KEYEVENTF_KEYUP = 0x0002

VK_BACK = 0x08
VK_TAB = 0x09
VK_RETURN = 0x0D
VK_SHIFT = 0x10
VK_CONTROL = 0x11
VK_MENU = 0x12  # Alt
VK_ESCAPE = 0x1B
VK_SPACE = 0x20
VK_LEFT = 0x25
VK_UP = 0x26
VK_RIGHT = 0x27
VK_DOWN = 0x28
VK_DELETE = 0x2E
VK_LWIN = 0x5B
VK_KEY_C = 0x43
VK_KEY_V = 0x56
VK_KEY_Z = 0x5A

MOUSE_STEPS = [10, 20, 50, 100]

CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class SYSTEM_POWER_STATUS(ctypes.Structure):
    _fields_ = [
        ("ACLineStatus", ctypes.c_ubyte),
        ("BatteryFlag", ctypes.c_ubyte),
        ("BatteryLifePercent", ctypes.c_ubyte),
        ("Reserved1", ctypes.c_ubyte),
        ("BatteryLifeTime", ctypes.c_ulong),
        ("BatteryFullLifeTime", ctypes.c_ulong),
    ]


# SendInput-структуры (нужны для ввода произвольного unicode-текста)
PUL = ctypes.POINTER(ctypes.c_ulong)


class KeyBdInput(ctypes.Structure):
    _fields_ = [
        ("wVk", ctypes.c_ushort),
        ("wScan", ctypes.c_ushort),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", PUL),
    ]


class Input_I(ctypes.Union):
    _fields_ = [("ki", KeyBdInput)]


class Input(ctypes.Structure):
    _fields_ = [("type", ctypes.c_ulong), ("ii", Input_I)]


INPUT_KEYBOARD = 1
KEYEVENTF_UNICODE = 0x0004


def get_cursor_pos():
    pt = POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y


def move_mouse_relative(dx, dy):
    x, y = get_cursor_pos()
    user32.SetCursorPos(x + dx, y + dy)


def mouse_click(button="left"):
    if button == "left":
        user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
        user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
    elif button == "right":
        user32.mouse_event(MOUSEEVENTF_RIGHTDOWN, 0, 0, 0, 0)
        user32.mouse_event(MOUSEEVENTF_RIGHTUP, 0, 0, 0, 0)


def mouse_scroll(amount):
    user32.mouse_event(MOUSEEVENTF_WHEEL, 0, 0, amount, 0)


def media_key(vk):
    user32.keybd_event(vk, 0, 0, 0)
    user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)


def press_vk(vk):
    user32.keybd_event(vk, 0, 0, 0)
    time.sleep(0.01)
    user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)


def press_combo(vks):
    for vk in vks:
        user32.keybd_event(vk, 0, 0, 0)
    time.sleep(0.03)
    for vk in reversed(vks):
        user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)


def _send_unicode_char(ch, key_up=False):
    extra = ctypes.pointer(ctypes.c_ulong(0))
    flags = KEYEVENTF_UNICODE | (KEYEVENTF_KEYUP if key_up else 0)
    ii_ = Input_I()
    ii_.ki = KeyBdInput(0, ord(ch), flags, 0, extra)
    packet = Input(INPUT_KEYBOARD, ii_)
    user32.SendInput(1, ctypes.pointer(packet), ctypes.sizeof(packet))


def type_text(text):
    """Печатает произвольный unicode-текст в то окно, которое сейчас в фокусе на ПК."""
    for ch in text:
        if ch == "\n":
            press_vk(VK_RETURN)
            continue
        _send_unicode_char(ch, key_up=False)
        _send_unicode_char(ch, key_up=True)
        time.sleep(0.008)


def get_clipboard_text():
    if not user32.OpenClipboard(0):
        return None
    try:
        handle = user32.GetClipboardData(CF_UNICODETEXT)
        if not handle:
            return None
        kernel32.GlobalLock.restype = ctypes.c_void_p
        locked = kernel32.GlobalLock(handle)
        if not locked:
            return None
        text = ctypes.wstring_at(locked)
        kernel32.GlobalUnlock(handle)
        return text
    finally:
        user32.CloseClipboard()


def set_clipboard_text(text):
    data = text.encode("utf-16le") + b"\x00\x00"
    if not user32.OpenClipboard(0):
        raise RuntimeError("Не удалось открыть буфер обмена")
    try:
        user32.EmptyClipboard()
        kernel32.GlobalAlloc.restype = ctypes.c_void_p
        h_mem = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
        kernel32.GlobalLock.restype = ctypes.c_void_p
        locked = kernel32.GlobalLock(h_mem)
        ctypes.memmove(locked, data, len(data))
        kernel32.GlobalUnlock(h_mem)
        user32.SetClipboardData(CF_UNICODETEXT, h_mem)
    finally:
        user32.CloseClipboard()


def get_battery_status():
    status = SYSTEM_POWER_STATUS()
    if not kernel32.GetSystemPowerStatus(ctypes.byref(status)):
        return None
    return status


def get_local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return socket.gethostbyname(socket.gethostname())
    finally:
        s.close()


def mouse_keyboard(step):
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("↖", callback_data="m:upleft"),
                InlineKeyboardButton("↑", callback_data="m:up"),
                InlineKeyboardButton("↗", callback_data="m:upright"),
            ],
            [
                InlineKeyboardButton("←", callback_data="m:left"),
                InlineKeyboardButton("🖱", callback_data="m:noop"),
                InlineKeyboardButton("→", callback_data="m:right"),
            ],
            [
                InlineKeyboardButton("↙", callback_data="m:downleft"),
                InlineKeyboardButton("↓", callback_data="m:down"),
                InlineKeyboardButton("↘", callback_data="m:downright"),
            ],
            [
                InlineKeyboardButton("Клик", callback_data="m:click"),
                InlineKeyboardButton("2×Клик", callback_data="m:dclick"),
                InlineKeyboardButton("ПКМ", callback_data="m:rclick"),
            ],
            [
                InlineKeyboardButton("Скролл ▲", callback_data="m:scrollup"),
                InlineKeyboardButton("Скролл ▼", callback_data="m:scrolldown"),
            ],
            [InlineKeyboardButton(f"Шаг: {step}px (сменить)", callback_data="m:step")],
        ]
    )


def music_keyboard():
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("⏮", callback_data="s:prev"),
                InlineKeyboardButton("⏯", callback_data="s:playpause"),
                InlineKeyboardButton("⏭", callback_data="s:next"),
            ],
            [
                InlineKeyboardButton("🔉", callback_data="s:voldown"),
                InlineKeyboardButton("🔊", callback_data="s:volup"),
            ],
            [InlineKeyboardButton("🎵 Открыть Spotify", callback_data="s:open")],
        ]
    )


def keyboard_keyboard():
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Esc", callback_data="k:esc"),
                InlineKeyboardButton("Tab", callback_data="k:tab"),
                InlineKeyboardButton("Del", callback_data="k:delete"),
            ],
            [InlineKeyboardButton("↑", callback_data="k:up")],
            [
                InlineKeyboardButton("←", callback_data="k:left"),
                InlineKeyboardButton("Enter ⏎", callback_data="k:enter"),
                InlineKeyboardButton("→", callback_data="k:right"),
            ],
            [InlineKeyboardButton("↓", callback_data="k:down")],
            [
                InlineKeyboardButton("Space", callback_data="k:space"),
                InlineKeyboardButton("⌫ Backspace", callback_data="k:backspace"),
            ],
            [
                InlineKeyboardButton("Win", callback_data="k:win"),
                InlineKeyboardButton("Alt+Tab", callback_data="k:alttab"),
            ],
            [
                InlineKeyboardButton("Ctrl+C", callback_data="k:ctrlc"),
                InlineKeyboardButton("Ctrl+V", callback_data="k:ctrlv"),
                InlineKeyboardButton("Ctrl+Z", callback_data="k:ctrlz"),
            ],
        ]
    )

# ---- WASD-панель для игр ----
VK_KEY_W = 0x57
VK_KEY_A = 0x41
VK_KEY_D = 0x44
VK_KEY_S = 0x53
VK_KEY_E = 0x45
VK_KEY_Q = 0x51
VK_KEY_R = 0x52

GAME_MOVE_KEYS = {"w": VK_KEY_W, "a": VK_KEY_A, "s": VK_KEY_S, "d": VK_KEY_D}
GAME_TAP_KEYS = {
    "space": VK_SPACE, "shift": VK_SHIFT, "ctrl": VK_CONTROL,
    "e": VK_KEY_E, "q": VK_KEY_Q, "r": VK_KEY_R, "tab": VK_TAB,
}

# mode: "tap" — каждое нажатие быстрый клик; "hold" — зажимает клавишу до повторного
# нажатия/переключения режима (для непрерывного движения в играх).
game_key_state = {"mode": "tap", "held_vk": None, "held_name": None}

def game_keyboard():
    mode_label = "🔒 Режим: удержание" if game_key_state["mode"] == "hold" else "👆 Режим: тап"
    release_label = "🛑 Отпустить"
    if game_key_state["held_vk"] is not None:
        release_label += f" ({game_key_state['held_name'].upper()} зажата)"
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("W", callback_data="g:w")],
            [
                InlineKeyboardButton("A", callback_data="g:a"),
                InlineKeyboardButton("␣ Space", callback_data="g:space"),
                InlineKeyboardButton("D", callback_data="g:d"),
            ],
            [InlineKeyboardButton("S", callback_data="g:s")],
            [
                InlineKeyboardButton("Shift", callback_data="g:shift"),
                InlineKeyboardButton("Ctrl", callback_data="g:ctrl"),
                InlineKeyboardButton("Tab", callback_data="g:tab"),
            ],
            [
                InlineKeyboardButton("Q", callback_data="g:q"),
                InlineKeyboardButton("E", callback_data="g:e"),
                InlineKeyboardButton("R", callback_data="g:r"),
            ],
            [InlineKeyboardButton(mode_label, callback_data="g:mode")],
            [InlineKeyboardButton(release_label, callback_data="g:release")],
        ]
    )

def _game_cancel_auto_release(context):
    for j in context.job_queue.get_jobs_by_name("game_auto_release"):
        j.schedule_removal()

def _game_release_held():
    if game_key_state["held_vk"] is not None:
        user32.keybd_event(game_key_state["held_vk"], 0, KEYEVENTF_KEYUP, 0)
        game_key_state["held_vk"] = None
        game_key_state["held_name"] = None

async def _game_auto_release_job(context: ContextTypes.DEFAULT_TYPE):
    # Страховка: если забыли отпустить зажатую клавишу, она отпустится сама
    # максимум через 60 секунд, чтобы не оставлять "залипшую" клавишу в игре.
    _game_release_held()

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ALLOWED_USER_ID = os.getenv("ALLOWED_USER_ID", "").strip()

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN не задан в .env")
if not ALLOWED_USER_ID.isdigit():
    raise RuntimeError("ALLOWED_USER_ID должен быть числовым Telegram ID")
ALLOWED_USER_ID = int(ALLOWED_USER_ID)

APP_PASSWORD = os.getenv("APP_PASSWORD", "fura").strip() or "fura"
MINI_APP_URL = os.getenv("MINI_APP_URL", "").strip()
AUTH_TTL_SECONDS = 24 * 60 * 60  # переспрашивать пароль раз в 24 часа

# Сессия одна на весь бот (доступ разрешён только одному ALLOWED_USER_ID).
# При старте бота expires_at = 0 -> пароль нужно ввести сразу после запуска.
auth_state = {"expires_at": 0.0}

def session_valid():
    return time.time() < auth_state["expires_at"]

def authorized(update):
    return (
        update.effective_user is not None
        and update.effective_user.id == ALLOWED_USER_ID
        and session_valid()
    )

async def deny(update):
    if update.effective_user is not None and update.effective_user.id == ALLOWED_USER_ID:
        await update.effective_message.reply_text(
            "🔐 Сессия истекла или ещё не подтверждена. Пришли пароль текстовым сообщением."
        )
    else:
        await update.effective_message.reply_text("⛔ Доступ запрещён.")

async def check_password(update, context):
    if update.effective_user is None or update.effective_user.id != ALLOWED_USER_ID:
        return  # чужим не отвечаем, чтобы не подтверждать существование бота
    if session_valid():
        return  # уже авторизован, обычные текстовые сообщения игнорируем
    text = (update.message.text or "").strip()
    if text == APP_PASSWORD:
        auth_state["expires_at"] = time.time() + AUTH_TTL_SECONDS
        await update.message.reply_text("✅ Пароль верный. Доступ открыт на 24 часа.")
    else:
        await update.message.reply_text("❌ Неверный пароль. Пришли правильный пароль, чтобы продолжить.")

async def request_password_job(context: ContextTypes.DEFAULT_TYPE):
    auth_state["expires_at"] = 0.0
    await context.bot.send_message(
        ALLOWED_USER_ID,
        "🔐 Прошло 24 часа. Пришли пароль текстовым сообщением, чтобы продолжить пользоваться ботом.",
    )

# ---- Anti-AFK: раз в ~50 секунд чуть шевелит курсор, чтобы ПК не уходил в "нет на месте" ----
antiafk_state = {"enabled": False}

async def antiafk_job(context: ContextTypes.DEFAULT_TYPE):
    if not antiafk_state["enabled"]:
        return
    try:
        move_mouse_relative(1, 0)
        move_mouse_relative(-1, 0)
    except Exception:
        pass

async def antiafk_cmd(update, context):
    if not authorized(update): return await deny(update)
    if not context.args:
        state = "включён ✅" if antiafk_state["enabled"] else "выключен ❌"
        return await update.message.reply_text(
            f"🕹 Anti-AFK сейчас: {state}\nПример: /antiafk on | off"
        )
    arg = context.args[0].lower()
    if arg in ("on", "вкл", "1"):
        antiafk_state["enabled"] = True
        await update.message.reply_text(
            "✅ Anti-AFK включён. Курсор будет слегка шевелиться каждые ~50 сек, "
            "чтобы Windows/мессенджеры не показывали статус «нет на месте»."
        )
    elif arg in ("off", "выкл", "0"):
        antiafk_state["enabled"] = False
        await update.message.reply_text("❌ Anti-AFK выключен.")
    else:
        await update.message.reply_text("Пример: /antiafk on | off")

# ---- Отдельный Anti-AFK для игр: раз в минуту жмёт Пробел + клик мышью
# (обычные "тихие" покачивания курсора игры часто не засчитывают за активность) ----
game_antiafk_state = {"enabled": False}

async def game_antiafk_job(context: ContextTypes.DEFAULT_TYPE):
    if not game_antiafk_state["enabled"]:
        return
    try:
        press_vk(VK_SPACE)
        mouse_click("left")
    except Exception:
        pass

async def antiafk_game_cmd(update, context):
    if not authorized(update): return await deny(update)
    if not context.args:
        state = "включён ✅" if game_antiafk_state["enabled"] else "выключен ❌"
        return await update.message.reply_text(
            f"🎮 Anti-AFK для игр сейчас: {state}\nПример: /antiafkgame on | off"
        )
    arg = context.args[0].lower()
    if arg in ("on", "вкл", "1"):
        game_antiafk_state["enabled"] = True
        await update.message.reply_text(
            "✅ Игровой Anti-AFK включён: раз в минуту будет нажиматься Пробел + клик мышью "
            "(в текущей позиции курсора — учитывай, где он стоит)."
        )
    elif arg in ("off", "выкл", "0"):
        game_antiafk_state["enabled"] = False
        await update.message.reply_text("❌ Игровой Anti-AFK выключен.")
    else:
        await update.message.reply_text("Пример: /antiafkgame on | off")

async def start(update, context):
    if not authorized(update): return await deny(update)
    await update.message.reply_text(
        "🖥 <b>Telegram PC Control</b>\n"
        "Управление этим Windows-компьютером прямо из Telegram.\n\n"

        "<b>🖥 Система</b>\n"
        "/status — информация о ПК\n"
        "/screenshot — скриншот (курсор мыши виден)\n"
        "/live [сек] — 🔴 прямая трансляция экрана\n"
        "/stoplive — остановить трансляцию\n"
        "/open [путь] — открыть программу (можно просто по названию, например /open telegram)\n"
        "/lock — заблокировать Windows\n"
        "/shutdown — выключение\n"
        "/restart — перезагрузка\n\n"

        "<b>🖱 Мышь и ⌨️ клавиатура</b>\n"
        "/mouse — панель управления мышью\n"
        "/keyboard — панель клавиатуры\n"
        "/wasd — 🎮 WASD-панель для игр\n"
        "/type [текст] — напечатать текст на ПК\n"
        "/key [имя] — нажать одну клавишу\n\n"

        "<b>🎵 Медиа</b>\n"
        "/music (/spotify) — управление плеером\n"
        "/volume up|down|mute — громкость\n\n"

        "<b>🕹 Anti-AFK</b>\n"
        "/antiafk on|off — лёгкое покачивание мыши\n"
        "/antiafkgame on|off — раз в минуту Пробел + клик (для игр)\n\n"

        "<b>📋 Прочее</b>\n"
        "/apps [название] — поиск программы по названию\n"
        "/clipboard — показать буфер обмена ПК\n"
        "/setclip [текст] — записать в буфер обмена ПК\n"
        "/battery — заряд батареи\n"
        "/ip — локальный и публичный IP\n"
        "/app — 📱 открыть Mini App\n"
        "/showimage, /clearimage — картинка на весь экран\n"
        "/confirm, /cancel — подтвердить/отменить опасное действие",
        parse_mode="HTML",
    )

async def status(update, context):
    if not authorized(update): return await deny(update)
    await update.message.reply_text(
        f"🖥 ПК: {socket.gethostname()}\n"
        f"💻 ОС: {platform.platform()}\n"
        f"🐍 Python: {platform.python_version()}"
    )

async def screenshot(update, context):
    if not authorized(update): return await deny(update)
    path = Path(tempfile.gettempdir()) / "telegram_pc_screenshot.png"
    try:
        from PIL import ImageGrab
        img = ImageGrab.grab()
        overlay_cursor(img, scale=1.0, size=26)
        img.save(path)
        with path.open("rb") as f:
            await update.message.reply_photo(f, caption="📸 Скриншот")
    except Exception as e:
        await update.message.reply_text(f"Ошибка скриншота: {e}")
    finally:
        path.unlink(missing_ok=True)

# ---- Live-трансляция экрана: периодически обновляем одно сообщение новым кадром.
# Это не настоящее видео (Telegram Bot API его не поддерживает) — а быстро
# обновляющиеся кадры (по умолчанию раз в ~2.5 сек) в том же сообщении,
# плюс кнопки мыши под картинкой — получается "смотрю и управляю" почти как в AnyDesk.
live_state = {"active": False}

def _cursor_arrow_points(cx, cy, size=20):
    return [
        (cx, cy), (cx, cy + size), (cx + size * 0.28, cy + size * 0.72),
        (cx + size * 0.46, cy + size * 0.98), (cx + size * 0.62, cy + size * 0.88),
        (cx + size * 0.42, cy + size * 0.62), (cx + size * 0.7, cy + size * 0.62),
    ]

def overlay_cursor(img, scale=1.0, size=20):
    """ImageGrab не захватывает системный курсор мыши, поэтому рисуем свой —
    жёлтая стрелка с тёмной обводкой, хорошо видна на любом фоне."""
    from PIL import ImageDraw
    try:
        cx, cy = get_cursor_pos()
        cx, cy = cx * scale, cy * scale
        d = ImageDraw.Draw(img)
        d.polygon(_cursor_arrow_points(cx, cy, size), fill=(255, 214, 0), outline=(20, 20, 20), width=2)
    except Exception:
        pass
    return img

def grab_screen_jpeg(path, max_width=1000, quality=55):
    from PIL import ImageGrab
    img = ImageGrab.grab()
    ratio = 1.0
    if img.width > max_width:
        ratio = max_width / img.width
        img = img.resize((max_width, int(img.height * ratio)))
    overlay_cursor(img, scale=ratio, size=18)
    img.convert("RGB").save(path, "JPEG", quality=quality)

async def live_loop(context, chat_id, interval):
    path = Path(tempfile.gettempdir()) / "telegram_pc_live.jpg"
    step = MOUSE_STEPS[1]
    message_id = None
    fail_count = 0
    loop = asyncio.get_event_loop()
    try:
        while live_state["active"]:
            try:
                await loop.run_in_executor(None, grab_screen_jpeg, path, 1000, 55)
                caption = f"🔴 LIVE — обновление каждые {interval:.1f} сек\nОстановить: /stoplive"
                if message_id is None:
                    with path.open("rb") as f:
                        msg = await context.bot.send_photo(
                            chat_id, f, caption=caption, reply_markup=mouse_keyboard(step)
                        )
                        message_id = msg.message_id
                else:
                    with path.open("rb") as f:
                        await context.bot.edit_message_media(
                            chat_id=chat_id, message_id=message_id,
                            media=InputMediaPhoto(f, caption=caption),
                            reply_markup=mouse_keyboard(step),
                        )
                fail_count = 0
            except Exception:
                fail_count += 1
                if fail_count >= 5:
                    live_state["active"] = False
                    try:
                        await context.bot.send_message(chat_id, "⚠️ Трансляция остановлена из-за повторяющихся ошибок.")
                    except Exception:
                        pass
                    break
            await asyncio.sleep(interval)
    finally:
        path.unlink(missing_ok=True)

async def start_live(context, chat_id, interval=2.5):
    if live_state["active"]:
        return False
    live_state["active"] = True
    context.application.create_task(live_loop(context, chat_id, interval))
    return True

async def stop_live():
    live_state["active"] = False

async def live_cmd(update, context):
    if not authorized(update): return await deny(update)
    interval = 2.5
    if context.args:
        try:
            interval = max(1.5, float(context.args[0]))
        except ValueError:
            pass
    started = await start_live(context, update.effective_chat.id, interval)
    if started:
        await update.message.reply_text(
            f"🔴 Запускаю трансляцию экрана (обновление каждые {interval:.1f} сек)...\n"
            "Под кадром будут кнопки управления мышью."
        )
    else:
        await update.message.reply_text("🔴 Трансляция уже идёт. Останови её командой /stoplive.")

async def stoplive_cmd(update, context):
    if not authorized(update): return await deny(update)
    if not live_state["active"]:
        return await update.message.reply_text("Трансляция и так не идёт.")
    await stop_live()
    await update.message.reply_text("⏹ Трансляция остановлена.")

async def open_program(update, context):
    if not authorized(update): return await deny(update)
    if not context.args:
        return await update.message.reply_text(
            'Пример: /open telegram\n'
            '/open steam\n'
            '/open "C:\\Program Files\\App\\app.exe"\n\n'
            "Можно просто ввести название программы — бот поищет её ярлык в меню "
            "«Пуск» и на рабочем столе. Если совпадений несколько — используй /apps, "
            "чтобы выбрать нужное из списка."
        )

    raw = update.message.text.partition(" ")[2].strip()
    key = raw.lower().strip('"')

    aliases = {
        "chrome": [r"C:\Program Files\Google\Chrome\Application\chrome.exe"],
        "notepad": ["notepad.exe"],
        "calculator": ["calc.exe"],
        "calc": ["calc.exe"],
        "paint": ["mspaint.exe"],
        "explorer": ["explorer.exe"],
        "проводник": ["explorer.exe"],
        "cmd": ["cmd.exe"],
        "консоль": ["cmd.exe"],
        "task manager": ["taskmgr.exe"],
        "taskmgr": ["taskmgr.exe"],
        "диспетчер задач": ["taskmgr.exe"],
        "control panel": ["control.exe"],
        "панель управления": ["control.exe"],
    }

    # 1) явный путь к существующему файлу
    maybe_path = Path(raw.strip('"'))
    if maybe_path.is_file():
        try:
            subprocess.Popen([str(maybe_path)])
            return await update.message.reply_text(f"✅ Запущено: {raw}")
        except Exception as e:
            return await update.message.reply_text(f"Ошибка: {e}")

    # 2) известный алиас
    if key in aliases:
        try:
            subprocess.Popen(aliases[key])
            return await update.message.reply_text(f"✅ Запущено: {raw}")
        except Exception as e:
            return await update.message.reply_text(f"Ошибка: {e}")

    # 3) поиск ярлыка по названию в меню "Пуск" / на рабочем столе — можно
    #    открыть практически любую установленную программу просто по имени
    matches = find_app_shortcuts(key)
    if matches:
        chosen = matches[0]
        try:
            os.startfile(str(chosen))
            extra = ""
            if len(matches) > 1:
                extra = f"\n(похожих ярлыков ещё {len(matches) - 1} — если нужен другой, используй /apps {raw})"
            return await update.message.reply_text(f"✅ Запущено: {chosen.stem}{extra}")
        except Exception as e:
            return await update.message.reply_text(f"Ошибка запуска: {e}")

    # 4) пробуем как команду (например exe, доступный через переменную PATH)
    try:
        subprocess.Popen(raw, shell=True)
        return await update.message.reply_text(f"🔎 Не нашёл ярлык, пробую запустить как команду: {raw}")
    except Exception:
        pass

    await update.message.reply_text(
        "❌ Не нашёл такую программу.\n"
        "Попробуй /apps " + raw + " — покажу похожие варианты, "
        "или укажи полный путь к .exe в кавычках."
    )

def _shortcut_search_dirs():
    dirs = []
    appdata = os.environ.get("APPDATA")
    programdata = os.environ.get("ProgramData")
    userprofile = os.environ.get("USERPROFILE")
    public = os.environ.get("PUBLIC")
    if appdata:
        dirs.append(Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs")
    if programdata:
        dirs.append(Path(programdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs")
    if userprofile:
        dirs.append(Path(userprofile) / "Desktop")
    if public:
        dirs.append(Path(public) / "Desktop")
    return [d for d in dirs if d.exists()]

def find_app_shortcuts(query, limit=15):
    """Ищет .lnk-ярлыки (меню "Пуск" + рабочий стол), название которых содержит query.
    Точные совпадения — в начале списка."""
    query = query.strip().lower()
    if not query:
        return []
    exact, partial = [], []
    for base in _shortcut_search_dirs():
        try:
            for p in base.rglob("*.lnk"):
                name = p.stem.lower()
                if query == name:
                    exact.append(p)
                elif query in name:
                    partial.append(p)
        except Exception:
            continue
    seen = set()
    result = []
    for p in exact + partial:
        key = str(p).lower()
        if key not in seen:
            seen.add(key)
            result.append(p)
        if len(result) >= limit:
            break
    return result

async def apps_search_cmd(update, context):
    if not authorized(update): return await deny(update)
    if not context.args:
        return await update.message.reply_text(
            "Пример: /apps discord — покажу найденные ярлыки с этим словом в названии, "
            "нажми на нужный, чтобы запустить."
        )
    query = update.message.text.partition(" ")[2].strip()
    matches = find_app_shortcuts(query)[:8]
    if not matches:
        return await update.message.reply_text(
            "Ничего не нашёл в меню «Пуск»/на рабочем столе. "
            "Попробуй другое слово или укажи путь к .exe напрямую через /open."
        )
    context.user_data["app_search_results"] = [str(m) for m in matches]
    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton(f"🚀 {m.stem}", callback_data=f"o:{i}")] for i, m in enumerate(matches)]
    )
    await update.message.reply_text(f"Нашёл по запросу «{query}»:", reply_markup=keyboard)

def image_path():
    return Path(tempfile.gettempdir()) / "telegram_pc_display.png"

async def receive_photo(update, context):
    if not authorized(update): return await deny(update)
    photo = update.message.photo[-1]
    tg_file = await photo.get_file()
    await tg_file.download_to_drive(str(image_path()))
    await update.message.reply_text("🖼 Картинка получена. Теперь отправь /showimage.")

async def show_image(update, context):
    if not authorized(update): return await deny(update)
    path = image_path()
    if not path.exists():
        return await update.message.reply_text("Сначала отправь боту картинку как фото.")

    script = r"""import os
import tkinter as tk
from PIL import Image, ImageTk

path = os.environ["TELEGRAM_PC_IMAGE"]
root = tk.Tk()
root.title("Telegram PC Display")
root.attributes("-fullscreen", True)
root.attributes("-topmost", True)
root.configure(bg="black")

img = Image.open(path)
sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
img.thumbnail((sw, sh), Image.Resampling.LANCZOS)
photo = ImageTk.PhotoImage(img)

label = tk.Label(root, image=photo, bg="black")
label.pack(expand=True)
root.bind("<Escape>", lambda e: root.destroy())
root.bind("<Button-1>", lambda e: root.destroy())
root.mainloop()
"""
    script_path = Path(tempfile.gettempdir()) / "telegram_pc_display.py"
    script_path.write_text(script, encoding="utf-8")
    env = os.environ.copy()
    env["TELEGRAM_PC_IMAGE"] = str(path)

    try:
        subprocess.Popen([os.sys.executable, str(script_path)], env=env)
        await update.message.reply_text("🖼 Картинка показана на весь экран. Esc или клик — закрыть.")
    except Exception as e:
        await update.message.reply_text(f"Ошибка показа: {e}")

async def clear_image(update, context):
    if not authorized(update): return await deny(update)
    image_path().unlink(missing_ok=True)
    await update.message.reply_text("🗑 Картинка удалена.")

async def lock_pc(update, context):
    if not authorized(update): return await deny(update)
    subprocess.Popen(["rundll32.exe", "user32.dll,LockWorkStation"])
    await update.message.reply_text("🔒 Компьютер заблокирован.")

async def shutdown(update, context):
    if not authorized(update): return await deny(update)
    context.user_data["pending_action"] = "shutdown"
    await update.message.reply_text("⚠️ Отправь /confirm для выключения или /cancel.")

async def restart(update, context):
    if not authorized(update): return await deny(update)
    context.user_data["pending_action"] = "restart"
    await update.message.reply_text("⚠️ Отправь /confirm для перезагрузки или /cancel.")

async def confirm(update, context):
    if not authorized(update): return await deny(update)
    action = context.user_data.pop("pending_action", None)
    if action == "shutdown":
        subprocess.Popen(["shutdown", "/s", "/t", "5"])
    elif action == "restart":
        subprocess.Popen(["shutdown", "/r", "/t", "5"])
    else:
        return await update.message.reply_text("Нет ожидающего действия.")
    await update.message.reply_text("⏳ Выполняю...")

async def cancel(update, context):
    if not authorized(update): return await deny(update)
    context.user_data.pop("pending_action", None)
    await update.message.reply_text("❌ Отменено.")

async def mouse_panel(update, context):
    if not authorized(update): return await deny(update)
    step = context.user_data.get("mouse_step", MOUSE_STEPS[1])
    await update.message.reply_text(
        "🖱 Управление мышью", reply_markup=mouse_keyboard(step)
    )

async def music_panel(update, context):
    if not authorized(update): return await deny(update)
    await update.message.reply_text(
        "🎵 Управление Spotify", reply_markup=music_keyboard()
    )

async def keyboard_panel(update, context):
    if not authorized(update): return await deny(update)
    await update.message.reply_text(
        "⌨️ Управление клавиатурой", reply_markup=keyboard_keyboard()
    )

async def wasd_panel(update, context):
    if not authorized(update): return await deny(update)
    await update.message.reply_text(
        "🎮 WASD-панель для игр\n"
        "Режим «тап» — быстрое нажатие. Режим «удержание» — зажимает клавишу для "
        "непрерывного движения (повторное нажатие той же клавиши отпускает; "
        "также есть автоотпускание через 60 сек на всякий случай).",
        reply_markup=game_keyboard(),
    )

KEY_ALIASES = {
    "enter": VK_RETURN,
    "esc": VK_ESCAPE,
    "tab": VK_TAB,
    "space": VK_SPACE,
    "backspace": VK_BACK,
    "delete": VK_DELETE,
    "up": VK_UP,
    "down": VK_DOWN,
    "left": VK_LEFT,
    "right": VK_RIGHT,
    "win": VK_LWIN,
}

async def key_cmd(update, context):
    if not authorized(update): return await deny(update)
    if not context.args:
        return await update.message.reply_text(
            "Пример: /key enter\nДоступно: " + ", ".join(KEY_ALIASES)
        )
    name = context.args[0].lower()
    vk = KEY_ALIASES.get(name)
    if vk is None:
        return await update.message.reply_text("Неизвестная клавиша. Доступно: " + ", ".join(KEY_ALIASES))
    try:
        press_vk(vk)
        await update.message.reply_text(f"⌨️ Нажато: {name}")
    except Exception as e:
        await update.message.reply_text(f"Ошибка: {e}")

async def type_text_cmd(update, context):
    if not authorized(update): return await deny(update)
    text = update.message.text.partition(" ")[2]
    if not text:
        return await update.message.reply_text("Пример: /type Привет, это тест")
    try:
        await asyncio.get_event_loop().run_in_executor(None, type_text, text)
        await update.message.reply_text("⌨️ Текст напечатан в активное окно на ПК.")
    except Exception as e:
        await update.message.reply_text(f"Ошибка ввода текста: {e}")

async def volume_cmd(update, context):
    if not authorized(update): return await deny(update)
    if not context.args:
        return await update.message.reply_text("Пример: /volume up | down | mute")
    action = context.args[0].lower()
    try:
        if action in ("up", "+"):
            media_key(VK_VOLUME_UP)
            await update.message.reply_text("🔊 Громче")
        elif action in ("down", "-"):
            media_key(VK_VOLUME_DOWN)
            await update.message.reply_text("🔉 Тише")
        elif action == "mute":
            media_key(VK_VOLUME_MUTE)
            await update.message.reply_text("🔇 Звук выключен/включён")
        else:
            await update.message.reply_text("Пример: /volume up | down | mute")
    except Exception as e:
        await update.message.reply_text(f"Ошибка: {e}")

async def clipboard_get(update, context):
    if not authorized(update): return await deny(update)
    try:
        text = get_clipboard_text()
    except Exception as e:
        return await update.message.reply_text(f"Ошибка чтения буфера обмена: {e}")
    if not text:
        return await update.message.reply_text("📋 Буфер обмена пуст или содержит не текст.")
    if len(text) > 3500:
        text = text[:3500] + "…"
    await update.message.reply_text(f"📋 Буфер обмена ПК:\n\n{text}")

async def clipboard_set(update, context):
    if not authorized(update): return await deny(update)
    text = update.message.text.partition(" ")[2]
    if not text:
        return await update.message.reply_text("Пример: /setclip текст, который нужно скопировать")
    try:
        set_clipboard_text(text)
        await update.message.reply_text("✅ Скопировано в буфер обмена ПК. Теперь можно вставить (Ctrl+V) в любое окно.")
    except Exception as e:
        await update.message.reply_text(f"Ошибка: {e}")

async def battery_status(update, context):
    if not authorized(update): return await deny(update)
    status = get_battery_status()
    if status is None:
        return await update.message.reply_text("Не удалось получить данные о батарее.")
    if status.BatteryFlag & 128:  # BATTERY_FLAG_NO_BATTERY
        return await update.message.reply_text("🔌 Батарея не обнаружена (стационарный ПК).")
    charging = "⚡ Заряжается" if status.ACLineStatus == 1 else "🔋 От батареи"
    percent = status.BatteryLifePercent if status.BatteryLifePercent != 255 else "?"
    await update.message.reply_text(f"{charging}\n🔋 Заряд: {percent}%")

async def ip_info(update, context):
    if not authorized(update): return await deny(update)
    local_ip = get_local_ip()
    public_ip = "не удалось определить"
    try:
        with urllib.request.urlopen("https://api.ipify.org", timeout=3) as r:
            public_ip = r.read().decode().strip()
    except Exception:
        pass
    await update.message.reply_text(f"🌐 Локальный IP: {local_ip}\n🌍 Публичный IP: {public_ip}")

async def app_cmd(update, context):
    if not authorized(update): return await deny(update)
    if not MINI_APP_URL:
        return await update.message.reply_text(
            "📱 Mini App ещё не настроен.\n\n"
            "Нужно один раз захостить файл mini_app/index.html где-нибудь по HTTPS "
            "(проще всего — бесплатно на GitHub Pages, см. README, раздел «Mini App»), "
            "и указать ссылку в поле MINI APP URL панели управления (или в .env как MINI_APP_URL)."
        )
    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton("🚀 Открыть Mini App", web_app=WebAppInfo(url=MINI_APP_URL))]]
    )
    await update.message.reply_text(
        "📱 Визуальная панель управления ПК:", reply_markup=keyboard
    )

async def on_web_app_data(update, context):
    if not authorized(update): return await deny(update)
    raw = update.effective_message.web_app_data.data
    try:
        payload = json.loads(raw)
    except Exception:
        return await update.message.reply_text("Некорректные данные от Mini App.")

    action_type = payload.get("type")
    try:
        if action_type == "type_text":
            text = payload.get("text", "")
            if text:
                await asyncio.get_event_loop().run_in_executor(None, type_text, text)
                await update.message.reply_text("⌨️ Текст напечатан на ПК.")
        elif action_type == "key":
            vk = KEY_ALIASES.get(payload.get("name", ""))
            if vk is not None:
                press_vk(vk)
                await update.message.reply_text(f"⌨️ Нажато: {payload.get('name')}")
        elif action_type == "music":
            action = payload.get("action")
            if action == "playpause":
                media_key(VK_MEDIA_PLAY_PAUSE)
                await update.message.reply_text("⏯ Пауза/Воспроизведение")
            elif action == "next":
                media_key(VK_MEDIA_NEXT_TRACK)
                await update.message.reply_text("⏭ Следующий трек")
            elif action == "prev":
                media_key(VK_MEDIA_PREV_TRACK)
                await update.message.reply_text("⏮ Предыдущий трек")
            elif action == "volup":
                media_key(VK_VOLUME_UP)
                await update.message.reply_text("🔊 Громче")
            elif action == "voldown":
                media_key(VK_VOLUME_DOWN)
                await update.message.reply_text("🔉 Тише")
            elif action == "open":
                os.startfile("spotify:")
                await update.message.reply_text("🎵 Открываю Spotify")
        elif action_type == "antiafk":
            antiafk_state["enabled"] = bool(payload.get("enabled"))
            state_txt = "включён ✅" if antiafk_state["enabled"] else "выключен ❌"
            await update.message.reply_text(f"🕹 Anti-AFK {state_txt}")
        elif action_type == "setclip":
            text = payload.get("text", "")
            if text:
                set_clipboard_text(text)
                await update.message.reply_text("✅ Скопировано в буфер обмена ПК.")
        elif action_type == "mouse_click":
            mouse_click(payload.get("button", "left"))
            await update.message.reply_text("🖱 Клик")
        elif action_type == "game":
            name = payload.get("name", "")
            vk = GAME_MOVE_KEYS.get(name) or GAME_TAP_KEYS.get(name)
            if vk is not None:
                press_vk(vk)
                await update.message.reply_text(f"🎮 {name.upper()}")
        elif action_type == "live":
            live_action = payload.get("action")
            if live_action == "start":
                started = await start_live(context, update.effective_chat.id)
                await update.message.reply_text(
                    "🔴 Запускаю трансляцию экрана..." if started else "🔴 Трансляция уже идёт."
                )
            elif live_action == "stop":
                await stop_live()
                await update.message.reply_text("⏹ Трансляция остановлена.")
        else:
            await update.message.reply_text("Неизвестное действие из Mini App.")
    except Exception as e:
        await update.message.reply_text(f"Ошибка выполнения: {e}")

async def on_button(update, context):
    query = update.callback_query
    if not (query.from_user and query.from_user.id == ALLOWED_USER_ID):
        return await query.answer("⛔ Доступ запрещён.", show_alert=True)

    data = query.data
    prefix, _, action = data.partition(":")

    if prefix == "m":
        step = context.user_data.get("mouse_step", MOUSE_STEPS[1])
        try:
            if action == "up":
                move_mouse_relative(0, -step)
            elif action == "down":
                move_mouse_relative(0, step)
            elif action == "left":
                move_mouse_relative(-step, 0)
            elif action == "right":
                move_mouse_relative(step, 0)
            elif action == "upleft":
                move_mouse_relative(-step, -step)
            elif action == "upright":
                move_mouse_relative(step, -step)
            elif action == "downleft":
                move_mouse_relative(-step, step)
            elif action == "downright":
                move_mouse_relative(step, step)
            elif action == "click":
                mouse_click("left")
            elif action == "dclick":
                mouse_click("left")
                mouse_click("left")
            elif action == "rclick":
                mouse_click("right")
            elif action == "scrollup":
                mouse_scroll(120)
            elif action == "scrolldown":
                mouse_scroll(-120)
            elif action == "step":
                idx = MOUSE_STEPS.index(step) if step in MOUSE_STEPS else 0
                step = MOUSE_STEPS[(idx + 1) % len(MOUSE_STEPS)]
                context.user_data["mouse_step"] = step
                await query.edit_message_reply_markup(reply_markup=mouse_keyboard(step))
            elif action == "noop":
                pass
            await query.answer()
        except Exception as e:
            await query.answer(f"Ошибка: {e}", show_alert=True)

    elif prefix == "s":
        try:
            if action == "playpause":
                media_key(VK_MEDIA_PLAY_PAUSE)
                await query.answer("⏯ Пауза/Воспроизведение")
            elif action == "next":
                media_key(VK_MEDIA_NEXT_TRACK)
                await query.answer("⏭ Следующий трек")
            elif action == "prev":
                media_key(VK_MEDIA_PREV_TRACK)
                await query.answer("⏮ Предыдущий трек")
            elif action == "volup":
                media_key(VK_VOLUME_UP)
                await query.answer("🔊 Громче")
            elif action == "voldown":
                media_key(VK_VOLUME_DOWN)
                await query.answer("🔉 Тише")
            elif action == "open":
                os.startfile("spotify:")
                await query.answer("🎵 Открываю Spotify")
        except Exception as e:
            await query.answer(f"Ошибка: {e}", show_alert=True)

    elif prefix == "k":
        try:
            if action == "esc":
                press_vk(VK_ESCAPE)
            elif action == "tab":
                press_vk(VK_TAB)
            elif action == "delete":
                press_vk(VK_DELETE)
            elif action == "up":
                press_vk(VK_UP)
            elif action == "down":
                press_vk(VK_DOWN)
            elif action == "left":
                press_vk(VK_LEFT)
            elif action == "right":
                press_vk(VK_RIGHT)
            elif action == "enter":
                press_vk(VK_RETURN)
            elif action == "space":
                press_vk(VK_SPACE)
            elif action == "backspace":
                press_vk(VK_BACK)
            elif action == "win":
                press_vk(VK_LWIN)
            elif action == "alttab":
                press_combo([VK_MENU, VK_TAB])
            elif action == "ctrlc":
                press_combo([VK_CONTROL, VK_KEY_C])
            elif action == "ctrlv":
                press_combo([VK_CONTROL, VK_KEY_V])
            elif action == "ctrlz":
                press_combo([VK_CONTROL, VK_KEY_Z])
            await query.answer()
        except Exception as e:
            await query.answer(f"Ошибка: {e}", show_alert=True)

    elif prefix == "g":
        try:
            if action == "mode":
                _game_release_held()
                _game_cancel_auto_release(context)
                game_key_state["mode"] = "hold" if game_key_state["mode"] == "tap" else "tap"
                await query.edit_message_reply_markup(reply_markup=game_keyboard())
                await query.answer(
                    "Режим: удержание" if game_key_state["mode"] == "hold" else "Режим: тап"
                )
            elif action == "release":
                had = game_key_state["held_vk"] is not None
                _game_release_held()
                _game_cancel_auto_release(context)
                await query.edit_message_reply_markup(reply_markup=game_keyboard())
                await query.answer("Отпущено" if had else "Ничего не зажато")
            elif action in GAME_MOVE_KEYS:
                vk = GAME_MOVE_KEYS[action]
                if game_key_state["mode"] == "hold":
                    if game_key_state["held_vk"] == vk:
                        _game_release_held()
                        _game_cancel_auto_release(context)
                        await query.answer(f"{action.upper()} отпущена")
                    else:
                        _game_release_held()
                        user32.keybd_event(vk, 0, 0, 0)
                        game_key_state["held_vk"] = vk
                        game_key_state["held_name"] = action
                        _game_cancel_auto_release(context)
                        context.job_queue.run_once(_game_auto_release_job, when=60, name="game_auto_release")
                        await query.answer(f"{action.upper()} зажата (до 60 сек)")
                    await query.edit_message_reply_markup(reply_markup=game_keyboard())
                else:
                    press_vk(vk)
                    await query.answer(action.upper())
            elif action in GAME_TAP_KEYS:
                press_vk(GAME_TAP_KEYS[action])
                await query.answer()
        except Exception as e:
            await query.answer(f"Ошибка: {e}", show_alert=True)

    elif prefix == "o":
        try:
            results = context.user_data.get("app_search_results", [])
            idx = int(action)
            if 0 <= idx < len(results):
                os.startfile(results[idx])
                await query.answer("✅ Запускаю")
            else:
                await query.answer("Список устарел, повтори /apps", show_alert=True)
        except Exception as e:
            await query.answer(f"Ошибка: {e}", show_alert=True)

BOT_COMMANDS_MENU = [
    BotCommand("start", "Список всех команд"),
    BotCommand("status", "Информация о ПК"),
    BotCommand("screenshot", "Скриншот экрана"),
    BotCommand("live", "🔴 Прямая трансляция экрана"),
    BotCommand("stoplive", "Остановить трансляцию"),
    BotCommand("mouse", "Управление мышью"),
    BotCommand("keyboard", "Панель клавиатуры"),
    BotCommand("wasd", "🎮 WASD-панель для игр"),
    BotCommand("type", "Напечатать текст на ПК"),
    BotCommand("key", "Нажать одну клавишу"),
    BotCommand("music", "Управление плеером/Spotify"),
    BotCommand("volume", "Громкость: up|down|mute"),
    BotCommand("antiafk", "Anti-AFK: лёгкое покачивание мыши"),
    BotCommand("antiafkgame", "Anti-AFK для игр: пробел + клик"),
    BotCommand("clipboard", "Показать буфер обмена ПК"),
    BotCommand("setclip", "Записать текст в буфер обмена ПК"),
    BotCommand("battery", "Заряд батареи"),
    BotCommand("ip", "Локальный и публичный IP"),
    BotCommand("app", "📱 Открыть Mini App"),
    BotCommand("open", "Открыть программу/файл по названию"),
    BotCommand("apps", "Поиск программы по названию"),
    BotCommand("lock", "Заблокировать Windows"),
    BotCommand("shutdown", "Выключить ПК"),
    BotCommand("restart", "Перезагрузить ПК"),
]

async def post_init(application: Application):
    try:
        await application.bot.set_my_commands(BOT_COMMANDS_MENU)
    except Exception:
        pass  # не критично, если Telegram временно недоступен при старте

app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("status", status))
app.add_handler(CommandHandler("screenshot", screenshot))
app.add_handler(CommandHandler("live", live_cmd))
app.add_handler(CommandHandler("stoplive", stoplive_cmd))
app.add_handler(CommandHandler("open", open_program))
app.add_handler(CommandHandler("apps", apps_search_cmd))
app.add_handler(CommandHandler("showimage", show_image))
app.add_handler(CommandHandler("clearimage", clear_image))
app.add_handler(CommandHandler("lock", lock_pc))
app.add_handler(CommandHandler("shutdown", shutdown))
app.add_handler(CommandHandler("restart", restart))
app.add_handler(CommandHandler("confirm", confirm))
app.add_handler(CommandHandler("cancel", cancel))
app.add_handler(CommandHandler("mouse", mouse_panel))
app.add_handler(CommandHandler("music", music_panel))
app.add_handler(CommandHandler("spotify", music_panel))
app.add_handler(CommandHandler("keyboard", keyboard_panel))
app.add_handler(CommandHandler("wasd", wasd_panel))
app.add_handler(CommandHandler("key", key_cmd))
app.add_handler(CommandHandler("type", type_text_cmd))
app.add_handler(CommandHandler("volume", volume_cmd))
app.add_handler(CommandHandler("antiafk", antiafk_cmd))
app.add_handler(CommandHandler("antiafkgame", antiafk_game_cmd))
app.add_handler(CommandHandler("clipboard", clipboard_get))
app.add_handler(CommandHandler("setclip", clipboard_set))
app.add_handler(CommandHandler("battery", battery_status))
app.add_handler(CommandHandler("ip", ip_info))
app.add_handler(CommandHandler("app", app_cmd))
app.add_handler(CallbackQueryHandler(on_button))
app.add_handler(MessageHandler(filters.PHOTO, receive_photo))
app.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, on_web_app_data))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, check_password))

app.job_queue.run_repeating(
    request_password_job,
    interval=timedelta(hours=24),
    first=timedelta(hours=24),
)
app.job_queue.run_repeating(
    antiafk_job,
    interval=timedelta(seconds=50),
    first=timedelta(seconds=50),
)
app.job_queue.run_repeating(
    game_antiafk_job,
    interval=timedelta(seconds=60),
    first=timedelta(seconds=60),
)

if __name__ == "__main__":
    print("Telegram PC Control v2 запущен. Требуется ввод пароля (см. .env: APP_PASSWORD).")
    app.run_polling()
