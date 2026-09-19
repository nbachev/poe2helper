"""Окно-оверлей оценки предмета."""

from __future__ import annotations

import logging
import statistics
import webbrowser

from PySide6.QtCore import QEvent, QPoint, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QCursor, QGuiApplication, QKeyEvent, QMouseEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..parser.item import ParsedItem
from ..trade.client import SearchResult
from ..trade.query import ModFilter, QueryOptions, build_mod_filters, build_query, default_options_for
from .addmod import AddModDialog
from .style import COLORS, QSS, rarity_color
from .widgets import ModRow
from .workers import run_async

log = logging.getLogger(__name__)


class PriceCheckOverlay(QWidget):
    """Полупрозрачное окно поверх игры с модами предмета и результатами поиска."""

    closed = Signal()

    def __init__(self, ctx) -> None:
        super().__init__(None)
        self.ctx = ctx  # AppController
        self.item: ParsedItem | None = None
        self.mod_filters: list[ModFilter] = []
        self.rows: list[ModRow] = []
        self.options = QueryOptions()
        self.last_result: SearchResult | None = None
        self._drag_origin: QPoint | None = None
        self._busy = False

        self.setWindowTitle("PoE2 Helper")
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setStyleSheet(QSS)
        self._build()

    # ------------------------------------------------------------------ UI
    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(6, 6, 6, 6)

        card = QFrame()
        card.setObjectName("Card")
        outer.addWidget(card)

        root = QVBoxLayout(card)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(8)

        # ---- шапка
        header = QHBoxLayout()
        title_box = QVBoxLayout()
        title_box.setSpacing(1)
        self.lbl_title = QLabel("—")
        self.lbl_title.setObjectName("Title")
        self.lbl_subtitle = QLabel("")
        self.lbl_subtitle.setObjectName("Subtitle")
        title_box.addWidget(self.lbl_title)
        title_box.addWidget(self.lbl_subtitle)
        header.addLayout(title_box, 1)

        self.btn_pin = QPushButton("📌")
        self.btn_pin.setObjectName("Flat")
        self.btn_pin.setCheckable(True)
        self.btn_pin.setFixedWidth(26)
        self.btn_pin.setToolTip("Не закрывать окно при потере фокуса")
        header.addWidget(self.btn_pin)

        btn_close = QPushButton("✕")
        btn_close.setObjectName("Flat")
        btn_close.setFixedWidth(26)
        btn_close.clicked.connect(self.hide)
        header.addWidget(btn_close)
        root.addLayout(header)

        # ---- моды
        self.mods_area = QScrollArea()
        self.mods_area.setWidgetResizable(True)
        self.mods_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.mods_host = QWidget()
        self.mods_layout = QVBoxLayout(self.mods_host)
        self.mods_layout.setContentsMargins(0, 0, 4, 0)
        self.mods_layout.setSpacing(1)
        self.mods_layout.addStretch(1)
        self.mods_area.setWidget(self.mods_host)
        self.mods_area.setMinimumHeight(90)
        root.addWidget(self.mods_area, 3)

        # ---- фильтры предмета
        filt = QGridLayout()
        filt.setHorizontalSpacing(10)
        filt.setVerticalSpacing(4)

        self.chk_rarity = QCheckBox("Редкость")
        self.cmb_rarity = QComboBox()
        for label, value in (
            ("не уникальные", "nonunique"),
            ("редкие", "rare"),
            ("магические", "magic"),
            ("обычные", "normal"),
            ("уникальные", "unique"),
        ):
            self.cmb_rarity.addItem(label, value)
        filt.addWidget(self.chk_rarity, 0, 0)
        filt.addWidget(self.cmb_rarity, 0, 1)

        self.chk_ilvl = QCheckBox("iLvl ≥")
        self.spn_ilvl = QSpinBox()
        self.spn_ilvl.setRange(0, 100)
        filt.addWidget(self.chk_ilvl, 0, 2)
        filt.addWidget(self.spn_ilvl, 0, 3)

        self.chk_quality = QCheckBox("Качество ≥")
        self.spn_quality = QSpinBox()
        self.spn_quality.setRange(0, 40)
        filt.addWidget(self.chk_quality, 0, 4)
        filt.addWidget(self.spn_quality, 0, 5)

        self.chk_corrupted = QCheckBox("Corrupted")
        self.cmb_corrupted = QComboBox()
        self.cmb_corrupted.addItem("нет", False)
        self.cmb_corrupted.addItem("да", True)
        filt.addWidget(self.chk_corrupted, 1, 0)
        filt.addWidget(self.cmb_corrupted, 1, 1)

        self.chk_sockets = QCheckBox("Сокеты ≥")
        self.spn_sockets = QSpinBox()
        self.spn_sockets.setRange(0, 6)
        filt.addWidget(self.chk_sockets, 1, 2)
        filt.addWidget(self.spn_sockets, 1, 3)

        self.chk_type = QCheckBox("База")
        self.chk_type.setToolTip("Искать только такую же базу предмета")
        filt.addWidget(self.chk_type, 1, 4)

        self.cmb_status = QComboBox()
        self.cmb_status.addItem("онлайн", "online")
        self.cmb_status.addItem("все", "any")
        filt.addWidget(self.cmb_status, 1, 5)

        root.addLayout(filt)

        # ---- кнопки
        actions = QHBoxLayout()
        self.btn_add_mod = QPushButton("＋ Мод из пула")
        self.btn_add_mod.setToolTip("Добавить в поиск любой мод, даже если его нет на предмете")
        self.btn_add_mod.clicked.connect(self._add_mod_from_pool)
        actions.addWidget(self.btn_add_mod)

        self.btn_none = QPushButton("Снять все")
        self.btn_none.clicked.connect(lambda: self._set_all(False))
        actions.addWidget(self.btn_none)

        self.btn_reset = QPushButton("Сброс")
        self.btn_reset.setToolTip("Вернуть исходный набор модов и границы")
        self.btn_reset.clicked.connect(self._reset)
        actions.addWidget(self.btn_reset)

        actions.addStretch(1)

        self.btn_browser = QPushButton("В браузере")
        self.btn_browser.setEnabled(False)
        self.btn_browser.clicked.connect(self._open_in_browser)
        actions.addWidget(self.btn_browser)

        self.btn_search = QPushButton("Искать")
        self.btn_search.setObjectName("Primary")
        self.btn_search.clicked.connect(self.search)
        actions.addWidget(self.btn_search)
        root.addLayout(actions)

        # ---- результаты
        self.lbl_status = QLabel("")
        self.lbl_status.setObjectName("Hint")
        self.lbl_status.setWordWrap(True)
        root.addWidget(self.lbl_status)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Цена", "Продавец", "iLvl", "Заметка"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        header_view = self.table.horizontalHeader()
        header_view.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header_view.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header_view.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header_view.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setMinimumHeight(120)
        self.table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.table.itemDoubleClicked.connect(self._copy_whisper)
        root.addWidget(self.table, 2)

        self.lbl_footer = QLabel("")
        self.lbl_footer.setObjectName("Hint")
        root.addWidget(self.lbl_footer)

        for widget in (
            self.chk_rarity, self.chk_ilvl, self.chk_quality,
            self.chk_corrupted, self.chk_sockets, self.chk_type,
        ):
            widget.toggled.connect(self._sync_options)
        self.cmb_rarity.currentIndexChanged.connect(self._sync_options)
        self.cmb_corrupted.currentIndexChanged.connect(self._sync_options)
        self.cmb_status.currentIndexChanged.connect(self._sync_options)
        for spin in (self.spn_ilvl, self.spn_quality, self.spn_sockets):
            spin.valueChanged.connect(self._sync_options)

    # -------------------------------------------------------------- данные
    def show_item(self, item: ParsedItem) -> None:
        self.item = item
        cfg_search = self.ctx.cfg.get("search") or {}
        self.options = default_options_for(item, cfg_search)
        self.mod_filters = build_mod_filters(
            item,
            self.ctx.stats_db,
            default_kinds=cfg_search.get(
                "enabled_mod_types_by_default", ["explicit", "implicit"]
            ),
            roll_tolerance=float(cfg_search.get("roll_tolerance", 0.1)),
            min_only=bool(cfg_search.get("use_min_only", True)),
        )
        self._rebuild_rows()
        self._fill_header()
        self._options_to_ui()
        self.table.setRowCount(0)
        self.last_result = None
        self.btn_browser.setEnabled(False)
        self.lbl_status.setText("")
        self._update_footer()
        self.show_near_cursor()
        if cfg_search.get("auto_search_on_open", True):
            self.search()

    def _fill_header(self) -> None:
        item = self.item
        if item is None:
            return
        self.lbl_title.setText(item.display_name)
        self.lbl_title.setStyleSheet(f"color: {rarity_color(item.rarity)}; font-size: 15px; font-weight: 600;")
        bits = [item.item_class or "?", item.rarity or "?"]
        if item.item_level:
            bits.append(f"iLvl {item.item_level}")
        if item.quality:
            bits.append(f"кач. {item.quality}%")
        if item.sockets:
            bits.append(f"сокетов {item.sockets}")
        if item.corrupted:
            bits.append("corrupted")
        if not item.identified:
            bits.append("неопознан")
        if not item.base_type_certain:
            bits.append("база определена приблизительно")
        self.lbl_subtitle.setText(" · ".join(bits))

    def _rebuild_rows(self) -> None:
        for row in self.rows:
            row.setParent(None)
            row.deleteLater()
        self.rows.clear()
        for mod in self.mod_filters:
            row = ModRow(mod)
            row.removed.connect(self._remove_row)
            self.mods_layout.insertWidget(self.mods_layout.count() - 1, row)
            self.rows.append(row)
        self._adjust_height()

    def _remove_row(self, row: ModRow) -> None:
        if row.mod in self.mod_filters:
            self.mod_filters.remove(row.mod)
        if row in self.rows:
            self.rows.remove(row)
        row.setParent(None)
        row.deleteLater()
        self._adjust_height()

    def _set_all(self, enabled: bool) -> None:
        for row in self.rows:
            row.set_enabled_state(enabled)

    def _reset(self) -> None:
        if self.item is not None:
            self.show_item(self.item)

    def _add_mod_from_pool(self) -> None:
        db = self.ctx.stats_db
        if db.is_empty:
            self.lbl_status.setText("Пул модов ещё не загружен (Настройки → Обновить данные).")
            return
        dialog = AddModDialog(db, self)
        was_pinned = self.btn_pin.isChecked()
        self.btn_pin.setChecked(True)
        try:
            if dialog.exec() != AddModDialog.DialogCode.Accepted or not dialog.selected_entry:
                return
            entry = dialog.selected_entry
            option_id = dialog.selected_option[0] if dialog.selected_option else None
            text = entry.text
            if dialog.selected_option:
                text = entry.text.replace("#", dialog.selected_option[1])
            mf = ModFilter(
                stat_id=entry.id,
                text=text,
                kind=entry.kind,
                enabled=True,
                option_id=option_id,
                from_pool=True,
            )
            self.mod_filters.append(mf)
            row = ModRow(mf)
            row.removed.connect(self._remove_row)
            self.mods_layout.insertWidget(self.mods_layout.count() - 1, row)
            self.rows.append(row)
            self._adjust_height()
        finally:
            self.btn_pin.setChecked(was_pinned)

    # ------------------------------------------------------------ параметры
    def _options_to_ui(self) -> None:
        blockers = [
            self.chk_rarity, self.chk_ilvl, self.chk_quality, self.chk_corrupted,
            self.chk_sockets, self.chk_type, self.cmb_rarity, self.cmb_corrupted,
            self.cmb_status, self.spn_ilvl, self.spn_quality, self.spn_sockets,
        ]
        for w in blockers:
            w.blockSignals(True)

        opts, item = self.options, self.item
        self.chk_rarity.setChecked(opts.rarity is not None)
        if opts.rarity:
            idx = self.cmb_rarity.findData(opts.rarity)
            if idx >= 0:
                self.cmb_rarity.setCurrentIndex(idx)

        self.chk_ilvl.setChecked(opts.item_level_min is not None)
        self.spn_ilvl.setValue(opts.item_level_min or (item.item_level if item else 0) or 0)

        self.chk_quality.setChecked(opts.quality_min is not None)
        self.spn_quality.setValue(opts.quality_min or (item.quality if item else 0) or 0)

        self.chk_corrupted.setChecked(opts.corrupted is not None)
        self.cmb_corrupted.setCurrentIndex(1 if opts.corrupted else 0)

        self.chk_sockets.setChecked(opts.sockets_min is not None)
        self.spn_sockets.setValue(opts.sockets_min or (item.sockets if item else 0) or 0)

        self.chk_type.setChecked(bool(opts.use_type and item and item.base_type_certain))
        self.chk_type.setEnabled(bool(item and item.base_type_certain))

        idx = self.cmb_status.findData(opts.status)
        self.cmb_status.setCurrentIndex(max(0, idx))

        for w in blockers:
            w.blockSignals(False)

    def _sync_options(self) -> None:
        self.options.rarity = self.cmb_rarity.currentData() if self.chk_rarity.isChecked() else None
        self.options.item_level_min = self.spn_ilvl.value() if self.chk_ilvl.isChecked() else None
        self.options.quality_min = self.spn_quality.value() if self.chk_quality.isChecked() else None
        self.options.corrupted = (
            bool(self.cmb_corrupted.currentData()) if self.chk_corrupted.isChecked() else None
        )
        self.options.sockets_min = self.spn_sockets.value() if self.chk_sockets.isChecked() else None
        self.options.use_type = self.chk_type.isChecked()
        self.options.status = self.cmb_status.currentData() or "online"

    # --------------------------------------------------------------- поиск
    def search(self) -> None:
        if self._busy:
            return
        if self.item is None:
            return
        league = self.ctx.league
        if not league:
            self.lbl_status.setText("Лига не определена. Открой настройки и укажи её вручную.")
            return

        self._sync_options()
        query = build_query(self.item, self.mod_filters, self.options)
        enabled = sum(1 for m in self.mod_filters if m.enabled and m.stat_id)
        self._busy = True
        self.btn_search.setEnabled(False)
        self.btn_search.setText("Ищу…")
        self.lbl_status.setText(f"Запрос к торговой площадке ({enabled} модов)…")

        limit = int(self.ctx.cfg.get("search.default_listings", 20))
        run_async(
            self.ctx.trade.search,
            on_done=self._on_search_done,
            on_error=self._on_search_error,
            league=league,
            query=query,
            limit=limit,
        )

    def _on_search_done(self, result: SearchResult) -> None:
        self._busy = False
        self.btn_search.setEnabled(True)
        self.btn_search.setText("Искать")
        self.last_result = result
        self.btn_browser.setEnabled(bool(result.url))
        self._fill_results(result)

    def _on_search_error(self, message: str) -> None:
        self._busy = False
        self.btn_search.setEnabled(True)
        self.btn_search.setText("Искать")
        self.lbl_status.setText(f"⚠ {message}")
        self.lbl_status.setStyleSheet(f"color: {COLORS['bad']};")

    def _fill_results(self, result: SearchResult) -> None:
        self.lbl_status.setStyleSheet(f"color: {COLORS['text_dim']};")
        self.table.setRowCount(0)
        listings = result.listings
        if not listings:
            self.lbl_status.setText(
                f"Ничего не найдено (всего по запросу: {result.total}). "
                "Попробуй снять часть модов."
            )
            return

        for listing in listings:
            row = self.table.rowCount()
            self.table.insertRow(row)
            price_item = QTableWidgetItem(listing.price_text)
            price_item.setForeground(QBrush(QColor(COLORS["accent"])))
            self.table.setItem(row, 0, price_item)
            self.table.setItem(row, 1, QTableWidgetItem(listing.account))
            self.table.setItem(row, 2, QTableWidgetItem(str(listing.item_level or "")))
            note = listing.note or ("corrupted" if listing.corrupted else "")
            self.table.setItem(row, 3, QTableWidgetItem(note))
            self.table.item(row, 0).setData(Qt.ItemDataRole.UserRole, listing.whisper)

        summary = _price_summary(listings)
        self.lbl_status.setText(
            f"Найдено лотов: {result.total}. Показаны {len(listings)}. {summary}"
        )
        self._update_footer()

    def _update_footer(self) -> None:
        bits = [f"Лига: {self.ctx.league or '—'}"]
        if self.ctx.stats_db.is_empty:
            bits.append("пул модов не загружен")
        bits.append("Esc — закрыть, двойной клик по строке — скопировать шёпот")
        self.lbl_footer.setText(" · ".join(bits))

    def _open_in_browser(self) -> None:
        if self.last_result and self.last_result.url:
            webbrowser.open(self.last_result.url)

    def _copy_whisper(self, item: QTableWidgetItem) -> None:
        row = item.row()
        cell = self.table.item(row, 0)
        whisper = cell.data(Qt.ItemDataRole.UserRole) if cell else ""
        if whisper:
            QGuiApplication.clipboard().setText(whisper)
            self.lbl_status.setText("Шёпот скопирован в буфер обмена.")

    # ------------------------------------------------------------ геометрия
    def show_near_cursor(self) -> None:
        cfg = self.ctx.cfg
        width = int(cfg.get("overlay.width", 520))
        self.setFixedWidth(width)
        self._adjust_height()
        self.setWindowOpacity(float(cfg.get("overlay.opacity", 0.96)))

        if cfg.get("overlay.remember_position", False):
            pos = QPoint(int(cfg.get("overlay.pos_x", 0)), int(cfg.get("overlay.pos_y", 0)))
            if not pos.isNull():
                self.move(pos)
                self.show()
                self.raise_()
                self.activateWindow()
                return

        cursor = QCursor.pos()
        screen = QGuiApplication.screenAt(cursor) or QGuiApplication.primaryScreen()
        geo = screen.availableGeometry()
        x = cursor.x() + 18
        y = cursor.y() + 18
        if x + self.width() > geo.right():
            x = cursor.x() - self.width() - 18
        if y + self.height() > geo.bottom():
            y = geo.bottom() - self.height() - 8
        x = max(geo.left() + 4, x)
        y = max(geo.top() + 4, y)
        self.move(x, y)
        self.show()
        self.raise_()
        self.activateWindow()

    def _adjust_height(self) -> None:
        rows = max(1, len(self.rows))
        mods_height = min(300, 26 * rows + 8)
        self.mods_area.setFixedHeight(mods_height)
        max_height = int(self.ctx.cfg.get("overlay.max_height", 760))
        self.setMaximumHeight(max_height)
        self.adjustSize()

    # ------------------------------------------------------------- события
    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 (Qt API)
        if event.key() == Qt.Key.Key_Escape:
            self.hide()
            return
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.search()
            return
        super().keyPressEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and event.position().y() < 46:
            self._drag_origin = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._drag_origin is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_origin)
            event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._drag_origin is not None:
            self._drag_origin = None
            if self.ctx.cfg.get("overlay.remember_position", False):
                self.ctx.cfg.set("overlay.pos_x", self.x())
                self.ctx.cfg.set("overlay.pos_y", self.y())
                self.ctx.cfg.save()

    def changeEvent(self, event: QEvent) -> None:  # noqa: N802
        if event.type() == QEvent.Type.ActivationChange:
            if (
                not self.isActiveWindow()
                and self.isVisible()
                and not self.btn_pin.isChecked()
                and self.ctx.cfg.get("overlay.close_on_focus_loss", True)
            ):
                self.hide()
        super().changeEvent(event)

    def hideEvent(self, event) -> None:  # noqa: N802
        self.closed.emit()
        super().hideEvent(event)


def _price_summary(listings) -> str:
    by_currency: dict[str, list[float]] = {}
    for listing in listings:
        if listing.price_amount is None:
            continue
        by_currency.setdefault(listing.price_currency or "?", []).append(listing.price_amount)
    if not by_currency:
        return ""
    currency, values = max(by_currency.items(), key=lambda kv: len(kv[1]))
    values.sort()
    median = statistics.median(values)
    return f"мин {values[0]:g} {currency} · медиана {median:g} {currency}"
