"""Глобальные горячие клавиши Windows через RegisterHotKey + отправка Ctrl+C.

Работает без сторонних зависимостей (только ctypes). На не-Windows модуль
импортируется, но регистрация хоткеев просто ничего не делает — это нужно,
чтобы гонять юнит-тесты на Linux.
"""

from __future__ import annotations

import ctypes
import logging
import os
import threading
from typing import Callable

log = logging.getLogger(__name__)

IS_WINDOWS = os.name == "nt"

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000

WM_HOTKEY = 0x0312
WM_QUIT = 0x0012

VK_MAP = {
    "BACKSPACE": 0x08, "TAB": 0x09, "ENTER": 0x0D, "RETURN": 0x0D,
    "ESC": 0x1B, "ESCAPE": 0x1B, "SPACE": 0x20,
    "PGUP": 0x21, "PAGEUP": 0x21, "PGDN": 0x22, "PAGEDOWN": 0x22,
    "END": 0x23, "HOME": 0x24,
    "LEFT": 0x25, "UP": 0x26, "RIGHT": 0x27, "DOWN": 0x28,
    "INSERT": 0x2D, "DELETE": 0x2E, "DEL": 0x2E,
    "NUMPAD0": 0x60, "NUMPAD1": 0x61, "NUMPAD2": 0x62, "NUMPAD3": 0x63,
    "NUMPAD4": 0x64, "NUMPAD5": 0x65, "NUMPAD6": 0x66, "NUMPAD7": 0x67,
    "NUMPAD8": 0x68, "NUMPAD9": 0x69, "MULTIPLY": 0x6A, "ADD": 0x6B,
    "SUBTRACT": 0x6D, "DECIMAL": 0x6E, "DIVIDE": 0x6F,
    "F1": 0x70, "F2": 0x71, "F3": 0x72, "F4": 0x73, "F5": 0x74, "F6": 0x75,
    "F7": 0x76, "F8": 0x77, "F9": 0x78, "F10": 0x79, "F11": 0x7A, "F12": 0x7B,
    "`": 0xC0, "-": 0xBD, "=": 0xBB, "[": 0xDB, "]": 0xDD, "\\": 0xDC,
    ";": 0xBA, "'": 0xDE, ",": 0xBC, ".": 0xBE, "/": 0xBF,
}

MOD_NAMES = {
    "CTRL": MOD_CONTROL, "CONTROL": MOD_CONTROL,
    "ALT": MOD_ALT, "SHIFT": MOD_SHIFT,
    "WIN": MOD_WIN, "META": MOD_WIN, "CMD": MOD_WIN,
}


class HotkeyError(RuntimeError):
    pass


def parse_hotkey(text: str) -> tuple[int, int]:
    """``"Ctrl+Alt+D"`` -> ``(MOD_CONTROL|MOD_ALT, 0x44)``."""
    parts = [p.strip() for p in (text or "").split("+") if p.strip()]
    if not parts:
        raise HotkeyError("Пустое сочетание клавиш")
    mods = 0
    key: str | None = None
    for part in parts:
        upper = part.upper()
        if upper in MOD_NAMES:
            mods |= MOD_NAMES[upper]
        else:
            key = part
    if key is None:
        raise HotkeyError(f"В сочетании «{text}» нет основной клавиши")
    upper = key.upper()
    if upper in VK_MAP:
        vk = VK_MAP[upper]
    elif len(upper) == 1 and (upper.isalpha() or upper.isdigit()):
        vk = ord(upper)
    elif key in VK_MAP:
        vk = VK_MAP[key]
    else:
        raise HotkeyError(f"Неизвестная клавиша: {key}")
    return mods | MOD_NOREPEAT, vk


class HotkeyManager:
    """Отдельный поток с очередью сообщений Windows и RegisterHotKey."""

    def __init__(self, on_trigger: Callable[[str], None]) -> None:
        self.on_trigger = on_trigger
        self._thread: threading.Thread | None = None
        self._thread_id: int | None = None
        self._ready = threading.Event()
        self._bindings: dict[int, str] = {}
        self._pending: list[tuple[str, str]] = []
        self._errors: list[str] = []
        self._lock = threading.Lock()
        self._stop = False

    # ------------------------------------------------------------- публично
    @property
    def available(self) -> bool:
        return IS_WINDOWS

    @property
    def errors(self) -> list[str]:
        with self._lock:
            return list(self._errors)

    def register(self, name: str, hotkey: str) -> None:
        """Ставит хоткей в очередь регистрации (можно до start())."""
        with self._lock:
            self._pending.append((name, hotkey))

    def start(self) -> None:
        if not IS_WINDOWS:
            log.info("Глобальные хоткеи доступны только в Windows — пропускаю")
            return
        if self._thread and self._thread.is_alive():
            return
        self._stop = False
        self._thread = threading.Thread(target=self._run, name="hotkeys", daemon=True)
        self._thread.start()
        self._ready.wait(timeout=3)

    def stop(self) -> None:
        self._stop = True
        if IS_WINDOWS and self._thread_id:
            try:
                ctypes.windll.user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
            except Exception:  # pragma: no cover
                pass
        if self._thread:
            self._thread.join(timeout=2)
        self._thread = None

    def reload(self, bindings: dict[str, str]) -> None:
        """Перерегистрирует все хоткеи (после изменения настроек)."""
        self.stop()
        with self._lock:
            self._pending = [(name, key) for name, key in bindings.items() if key]
            self._errors.clear()
            self._bindings.clear()
        self.start()

    # ------------------------------------------------------------- внутри
    def _run(self) -> None:  # pragma: no cover - только Windows
        user32 = ctypes.windll.user32
        self._thread_id = ctypes.windll.kernel32.GetCurrentThreadId()

        with self._lock:
            pending = list(self._pending)
            self._pending.clear()

        hotkey_id = 1
        for name, combo in pending:
            try:
                mods, vk = parse_hotkey(combo)
            except HotkeyError as exc:
                with self._lock:
                    self._errors.append(f"{name}: {exc}")
                continue
            if not user32.RegisterHotKey(None, hotkey_id, mods, vk):
                with self._lock:
                    self._errors.append(
                        f"{name}: не удалось занять {combo} (возможно, занято другой программой)"
                    )
                continue
            self._bindings[hotkey_id] = name
            hotkey_id += 1

        self._ready.set()

        msg = ctypes.wintypes.MSG()
        while not self._stop:
            result = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if result in (0, -1):
                break
            if msg.message == WM_HOTKEY:
                name = self._bindings.get(int(msg.wParam))
                if name:
                    try:
                        self.on_trigger(name)
                    except Exception:
                        log.exception("Ошибка в обработчике хоткея %s", name)

        for hk_id in list(self._bindings):
            try:
                user32.UnregisterHotKey(None, hk_id)
            except Exception:
                pass
        self._bindings.clear()
        self._thread_id = None


# --------------------------------------------------------------- SendInput
if IS_WINDOWS:  # pragma: no cover - только Windows
    import ctypes.wintypes as wt

    ULONG_PTR = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [
            ("wVk", wt.WORD),
            ("wScan", wt.WORD),
            ("dwFlags", wt.DWORD),
            ("time", wt.DWORD),
            ("dwExtraInfo", ULONG_PTR),
        ]

    class _INPUTunion(ctypes.Union):
        _fields_ = [("ki", KEYBDINPUT), ("padding", ctypes.c_byte * 32)]

    class INPUT(ctypes.Structure):
        _fields_ = [("type", wt.DWORD), ("u", _INPUTunion)]

    INPUT_KEYBOARD = 1
    KEYEVENTF_KEYUP = 0x0002
    VK_CONTROL = 0x11
    VK_C = 0x43
    VK_MENU = 0x12
    VK_SHIFT = 0x10
    VK_LWIN = 0x5B


def _key_event(vk: int, up: bool = False):  # pragma: no cover - только Windows
    inp = INPUT()
    inp.type = INPUT_KEYBOARD
    inp.u.ki = KEYBDINPUT(wVk=vk, wScan=0, dwFlags=KEYEVENTF_KEYUP if up else 0, time=0, dwExtraInfo=0)
    return inp


def send_ctrl_c() -> bool:
    """Отправляет Ctrl+C активному окну (игре), чтобы скопировать предмет."""
    if not IS_WINDOWS:
        return False
    try:  # pragma: no cover - только Windows
        user32 = ctypes.windll.user32
        # Отпускаем модификаторы хоткея, иначе игра увидит, например, Ctrl+Alt+C
        release = [
            _key_event(VK_MENU, up=True),
            _key_event(VK_SHIFT, up=True),
            _key_event(VK_LWIN, up=True),
        ]
        seq = release + [
            _key_event(VK_CONTROL),
            _key_event(VK_C),
            _key_event(VK_C, up=True),
            _key_event(VK_CONTROL, up=True),
        ]
        array = (INPUT * len(seq))(*seq)
        sent = user32.SendInput(len(seq), ctypes.byref(array), ctypes.sizeof(INPUT))
        return bool(sent)
    except Exception:
        log.exception("Не удалось отправить Ctrl+C")
        return False


def cursor_position() -> tuple[int, int]:
    """Текущие координаты курсора в пикселях экрана."""
    if not IS_WINDOWS:
        return (0, 0)
    try:  # pragma: no cover - только Windows
        import ctypes.wintypes as wt

        point = wt.POINT()
        ctypes.windll.user32.GetCursorPos(ctypes.byref(point))
        return (int(point.x), int(point.y))
    except Exception:
        return (0, 0)


def set_dpi_awareness() -> None:
    """Корректные координаты на мониторах с масштабированием."""
    if not IS_WINDOWS:
        return
    try:  # pragma: no cover - только Windows
        # PROCESS_PER_MONITOR_DPI_AWARE = 2
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


if IS_WINDOWS:  # pragma: no cover
    import ctypes.wintypes  # noqa: F401  (нужен для MSG в _run)
