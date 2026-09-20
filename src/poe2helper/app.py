"""Точка сборки приложения: трей, хоткеи, буфер обмена, оверлей."""

from __future__ import annotations

import logging
import logging.handlers
import sys

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QFont, QGuiApplication, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from . import hotkeys as hk
from .config import Config
from .filters.update import run_filter_update
from .parser.item import parse_item
from .parser.stats_db import StatsDB
from .paths import log_path
from .trade.client import TradeClient
from .trade.ninja import NinjaClient
from .ui.main_window import MainWindow
from .ui.overlay import PriceCheckOverlay
from .ui.style import COLORS
from .ui.workers import run_async

log = logging.getLogger(__name__)

CLIPBOARD_SENTINEL = "​PoE2Helper​"
POLL_INTERVAL_MS = 50
POLL_ATTEMPTS = 24


def setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    root = logging.getLogger()
    root.setLevel(level)
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    try:
        handler = logging.handlers.RotatingFileHandler(
            log_path(), maxBytes=1_000_000, backupCount=2, encoding="utf-8"
        )
        handler.setFormatter(fmt)
        root.addHandler(handler)
    except OSError:
        pass
    stream = logging.StreamHandler(sys.stderr)
    stream.setFormatter(fmt)
    root.addHandler(stream)


class HotkeyBridge(QObject):
    """Переносит событие из потока хоткеев в поток UI."""

    triggered = Signal(str)


class AppController(QObject):
    def __init__(self, app: QApplication) -> None:
        super().__init__()
        self.app = app
        self.cfg = Config.load()
        self.warnings: list[str] = []
        self.league: str = (self.cfg.get("league") or "").strip()

        ua = self.cfg.get("network.user_agent", "PoE2Helper/0.1")
        timeout = int(self.cfg.get("network.timeout", 20))
        self.trade = TradeClient(
            host=self.cfg.get("trade_host", "https://www.pathofexile.com"),
            realm=self.cfg.get("realm", "poe2"),
            user_agent=ua,
            poesessid=self.cfg.get("poesessid", ""),
            timeout=timeout,
        )
        self.ninja = NinjaClient(user_agent=ua, timeout=timeout)
        self.stats_db = StatsDB.load_cached() or StatsDB()

        self.overlay = PriceCheckOverlay(self)
        self.window = MainWindow(self)

        self.tray = self._build_tray()
        self.bridge = HotkeyBridge()
        self.bridge.triggered.connect(self._on_hotkey)
        self.hotkeys = hk.HotkeyManager(self.bridge.triggered.emit)

        self._clip_backup = ""
        self._poll_attempts = 0
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(POLL_INTERVAL_MS)
        self._poll_timer.timeout.connect(self._poll_clipboard)

    # ------------------------------------------------------------- запуск
    def start(self) -> None:
        hk.set_dpi_awareness()
        self._register_hotkeys()

        if not self.league:
            run_async(self.ninja.default_league, on_done=self._on_league, on_error=self._on_bg_error)
        if self.stats_db.is_empty or self.stats_db.is_stale:
            self.reload_stats(silent=True)

        if self.cfg.get("filter.update_on_start", False) and self.cfg.get("filter.path"):
            QTimer.singleShot(2500, lambda: self.update_filter(dry_run=False, silent=True))

        if not hk.IS_WINDOWS:
            self.warnings.append(
                "Глобальные хоткеи работают только в Windows. "
                "Здесь окно можно открыть только вручную."
            )
        self.window.refresh_status()

    def _register_hotkeys(self) -> None:
        bindings = {"price_check": self.cfg.get("hotkey_price_check", "Ctrl+D")}
        self.hotkeys.reload(bindings)
        errors = self.hotkeys.errors
        self.warnings = [w for w in self.warnings if "хоткей" not in w.lower()]
        for err in errors:
            self.warnings.append(f"Хоткей не зарегистрирован — {err}")

    def apply_settings(self) -> None:
        """Вызывается после сохранения настроек."""
        self.trade.set_poesessid(self.cfg.get("poesessid", ""))
        league = (self.cfg.get("league") or "").strip()
        if league:
            self.league = league
        self._register_hotkeys()

    # --------------------------------------------------------------- трей
    def _build_tray(self) -> QSystemTrayIcon:
        tray = QSystemTrayIcon(make_icon(), self.app)
        tray.setToolTip("PoE2 Helper")
        menu = QMenu()

        act_window = QAction("Открыть окно", menu)
        act_window.triggered.connect(self.show_window)
        menu.addAction(act_window)

        act_filter = QAction("Обновить итем-фильтр", menu)
        act_filter.triggered.connect(lambda: self.update_filter(dry_run=False, silent=False))
        menu.addAction(act_filter)

        act_stats = QAction("Обновить пул модов", menu)
        act_stats.triggered.connect(lambda: self.reload_stats(silent=False))
        menu.addAction(act_stats)

        menu.addSeparator()
        act_quit = QAction("Выход", menu)
        act_quit.triggered.connect(self.quit)
        menu.addAction(act_quit)

        tray.setContextMenu(menu)
        tray.activated.connect(self._on_tray_activated)
        tray.show()
        return tray

    def _on_tray_activated(self, reason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.show_window()

    def show_window(self) -> None:
        self.window.show()
        self.window.raise_()
        self.window.activateWindow()

    def notify(self, title: str, message: str) -> None:
        try:
            self.tray.showMessage(title, message, make_icon(), 5000)
        except Exception:
            log.info("%s: %s", title, message)

    def quit(self) -> None:
        self.hotkeys.stop()
        self.cfg.save()
        self.app.quit()

    # ------------------------------------------------------------- хоткеи
    def _on_hotkey(self, name: str) -> None:
        if name == "price_check":
            self.price_check()

    def price_check(self) -> None:
        clipboard = QGuiApplication.clipboard()
        self._clip_backup = clipboard.text()
        clipboard.setText(CLIPBOARD_SENTINEL)
        if not hk.send_ctrl_c():
            # Не Windows либо SendInput не сработал — пробуем то, что уже в буфере
            clipboard.setText(self._clip_backup)
            self._handle_clipboard(self._clip_backup)
            return
        self._poll_attempts = 0
        self._poll_timer.start()

    def _poll_clipboard(self) -> None:
        self._poll_attempts += 1
        text = QGuiApplication.clipboard().text()
        if text and text != CLIPBOARD_SENTINEL:
            self._poll_timer.stop()
            self._handle_clipboard(text)
            QTimer.singleShot(400, self._restore_clipboard)
            return
        if self._poll_attempts >= POLL_ATTEMPTS:
            self._poll_timer.stop()
            self._restore_clipboard()
            self.notify(
                "PoE2 Helper",
                "Игра ничего не скопировала. Наведи курсор на предмет и убедись, "
                "что PoE2 запущен в окне без рамки.",
            )

    def _restore_clipboard(self) -> None:
        clipboard = QGuiApplication.clipboard()
        if clipboard.text() == CLIPBOARD_SENTINEL:
            clipboard.setText(self._clip_backup)

    def _handle_clipboard(self, text: str) -> None:
        item = parse_item(text)
        if item is None:
            self.notify("PoE2 Helper", "В буфере не предмет Path of Exile 2.")
            return
        if self.stats_db.is_empty:
            self.notify("PoE2 Helper", "Пул модов ещё загружается — поиск по модам будет неполным.")
        self.overlay.show_item(item)

    # ------------------------------------------------------------- данные
    def reload_stats(self, silent: bool = True) -> None:
        def task():
            payload = self.trade.fetch_stats()
            db = StatsDB.from_api_payload(payload)
            db.save_cache(payload)
            import time as _time

            db.fetched_at = _time.time()
            return db

        def done(db: StatsDB) -> None:
            self.stats_db = db
            self.window.refresh_status()
            if not silent:
                self.notify("PoE2 Helper", f"Пул модов обновлён: {len(db.entries)} записей.")

        def failed(message: str) -> None:
            self.warnings.append(f"Пул модов не загружен: {message}")
            self.window.refresh_status()
            if not silent:
                self.notify("PoE2 Helper", f"Не удалось обновить пул модов: {message}")

        run_async(task, on_done=done, on_error=failed)

    def _on_league(self, league: str) -> None:
        if league:
            self.league = league
            self.cfg.set("league", league)
            self.cfg.save()
            self.window.refresh_status()

    def _on_bg_error(self, message: str) -> None:
        log.warning("Фоновая задача: %s", message)
        self.warnings.append(message)
        self.window.refresh_status()

    def refresh_league(self) -> None:
        run_async(self.ninja.default_league, on_done=self._on_league, on_error=self._on_bg_error)

    def update_filter(self, dry_run: bool = False, silent: bool = False) -> None:
        def done(result) -> None:
            if not silent or not result.ok:
                self.notify("Итем-фильтр", result.message)
            self.window.filter_output.setPlainText(
                result.message + ("\n\n" + result.report.summary() if result.report else "")
            )

        def failed(message: str) -> None:
            self.notify("Итем-фильтр", f"Ошибка: {message}")

        run_async(
            run_filter_update,
            on_done=done,
            on_error=failed,
            cfg=self.cfg,
            ninja=self.ninja,
            dry_run=dry_run,
        )


def make_icon() -> QIcon:
    """Простая иконка, нарисованная в рантайме — не тянем внешние файлы."""
    pixmap = QPixmap(64, 64)
    pixmap.fill(QColor(COLORS["bg"]))
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QColor(COLORS["accent"]))
    painter.setBrush(QColor(COLORS["accent_dim"]))
    painter.drawRoundedRect(4, 4, 56, 56, 12, 12)
    painter.setPen(QColor("#17181c"))
    font = QFont("Segoe UI", 26, QFont.Weight.Bold)
    painter.setFont(font)
    painter.drawText(pixmap.rect(), 0x0084, "P2")  # Qt.AlignCenter
    painter.end()
    return QIcon(pixmap)


def main(argv: list[str] | None = None) -> int:
    argv = list(argv if argv is not None else sys.argv)
    verbose = "--verbose" in argv or "-v" in argv
    setup_logging(verbose)

    app = QApplication(argv)
    app.setApplicationName("PoE2 Helper")
    app.setQuitOnLastWindowClosed(False)
    app.setWindowIcon(make_icon())

    controller = AppController(app)
    controller.start()

    if "--minimized" not in argv:
        controller.show_window()

    return app.exec()
