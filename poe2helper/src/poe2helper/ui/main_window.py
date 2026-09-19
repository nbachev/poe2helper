"""Главное окно: статус, настройки и управление итем-фильтром."""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..config import DEFAULT_TIER_THRESHOLDS
from ..filters.parse import FilterFile
from ..filters.retier import detect_groups
from ..filters.update import FilterUpdateResult, run_filter_update
from ..paths import backup_dir, data_dir, list_filter_files
from .style import COLORS, QSS
from .workers import run_async

log = logging.getLogger(__name__)


class MainWindow(QWidget):
    def __init__(self, ctx) -> None:
        super().__init__()
        self.ctx = ctx
        self._filter_busy = False
        self.setWindowTitle("PoE2 Helper")
        self.resize(820, 640)
        self.setStyleSheet(QSS)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)

        self.tabs = QTabWidget()
        root.addWidget(self.tabs, 1)
        self.tabs.addTab(self._build_status_tab(), "Обзор")
        self.tabs.addTab(self._build_filter_tab(), "Итем-фильтр")
        self.tabs.addTab(self._build_settings_tab(), "Настройки")

        self.lbl_bottom = QLabel("")
        self.lbl_bottom.setObjectName("Hint")
        root.addWidget(self.lbl_bottom)

        self.refresh_status()

    # =============================================================== обзор
    def _build_status_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(10)

        self.lbl_league = QLabel("Лига: —")
        self.lbl_league.setObjectName("Title")
        layout.addWidget(self.lbl_league)

        self.lbl_stats = QLabel("Пул модов: —")
        layout.addWidget(self.lbl_stats)

        self.lbl_hotkeys = QLabel("")
        self.lbl_hotkeys.setWordWrap(True)
        layout.addWidget(self.lbl_hotkeys)

        self.lbl_warnings = QLabel("")
        self.lbl_warnings.setWordWrap(True)
        self.lbl_warnings.setStyleSheet(f"color: {COLORS['bad']};")
        layout.addWidget(self.lbl_warnings)

        buttons = QHBoxLayout()
        btn_reload_stats = QPushButton("Обновить пул модов")
        btn_reload_stats.clicked.connect(self._reload_stats)
        buttons.addWidget(btn_reload_stats)

        btn_reload_league = QPushButton("Определить лигу заново")
        btn_reload_league.clicked.connect(self._reload_league)
        buttons.addWidget(btn_reload_league)

        btn_open_data = QPushButton("Папка с настройками")
        btn_open_data.clicked.connect(lambda: _open_path(data_dir()))
        buttons.addWidget(btn_open_data)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        help_box = QGroupBox("Как пользоваться")
        help_layout = QVBoxLayout(help_box)
        self.lbl_help = QLabel()
        self.lbl_help.setWordWrap(True)
        self.lbl_help.setTextFormat(Qt.TextFormat.RichText)
        help_layout.addWidget(self.lbl_help)
        layout.addWidget(help_box)
        layout.addStretch(1)
        return page

    def _reload_stats(self) -> None:
        self.lbl_bottom.setText("Обновляю пул модов…")
        self.ctx.reload_stats(silent=False)

    def _reload_league(self) -> None:
        self.lbl_bottom.setText("Определяю лигу…")
        self.ctx.refresh_league()

    # ============================================================== фильтр
    def _build_filter_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(8)

        path_row = QHBoxLayout()
        self.edit_filter_path = QLineEdit(self.ctx.cfg.get("filter.path", ""))
        self.edit_filter_path.setPlaceholderText("…\\Documents\\My Games\\Path of Exile 2\\my.filter")
        path_row.addWidget(self.edit_filter_path, 1)
        btn_browse = QPushButton("Выбрать…")
        btn_browse.clicked.connect(self._pick_filter)
        path_row.addWidget(btn_browse)
        layout.addLayout(path_row)

        self.list_found = QListWidget()
        self.list_found.setMaximumHeight(90)
        self.list_found.itemDoubleClicked.connect(
            lambda item: self.edit_filter_path.setText(item.text())
        )
        layout.addWidget(QLabel("Найденные фильтры (двойной клик — выбрать):"))
        layout.addWidget(self.list_found)
        self._refresh_found_filters()

        opts = QHBoxLayout()
        self.chk_filter_autostart = QCheckBox("Обновлять при запуске программы")
        self.chk_filter_autostart.setChecked(bool(self.ctx.cfg.get("filter.update_on_start", False)))
        opts.addWidget(self.chk_filter_autostart)

        self.chk_filter_inplace = QCheckBox("Писать в тот же файл")
        self.chk_filter_inplace.setChecked(bool(self.ctx.cfg.get("filter.write_in_place", True)))
        self.chk_filter_inplace.setToolTip(
            "Если снять — результат уйдёт в отдельный файл *.autopriced.filter"
        )
        opts.addWidget(self.chk_filter_inplace)

        self.chk_filter_backup = QCheckBox("Делать бэкап")
        self.chk_filter_backup.setChecked(bool(self.ctx.cfg.get("filter.make_backup", True)))
        opts.addWidget(self.chk_filter_backup)

        self.chk_auto_groups = QCheckBox("Автоопределение групп")
        self.chk_auto_groups.setChecked(bool(self.ctx.cfg.get("filter.auto_detect_groups", True)))
        self.chk_auto_groups.setToolTip(
            "Брать из файла все группы $type-> с нумерованными тирами, где известны цены.\n"
            "Спасает, когда NeverSink переименовал теги."
        )
        opts.addWidget(self.chk_auto_groups)

        opts.addWidget(QLabel("Валюта порогов:"))
        self.cmb_unit = QComboBox()
        for label, value in (("экзальты", "exalted"), ("дивайны", "divine"), ("хаос", "chaos")):
            self.cmb_unit.addItem(label, value)
        idx = self.cmb_unit.findData(self.ctx.cfg.get("filter.price_unit", "exalted"))
        self.cmb_unit.setCurrentIndex(max(0, idx))
        opts.addWidget(self.cmb_unit)
        opts.addStretch(1)
        layout.addLayout(opts)

        layout.addWidget(QLabel("Пороги тиров (через запятую, от дорогих к дешёвым):"))
        self.table_thresholds = QTableWidget(0, 3)
        self.table_thresholds.setHorizontalHeaderLabels(["Вкл", "Группа ($type->)", "Пороги"])
        self.table_thresholds.verticalHeader().setVisible(False)
        self.table_thresholds.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked | QAbstractItemView.EditTrigger.SelectedClicked
        )
        header = self.table_thresholds.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table_thresholds, 1)
        self._fill_thresholds()

        actions = QHBoxLayout()
        btn_scan = QPushButton("Считать группы из файла")
        btn_scan.setToolTip(
            "Прочитать выбранный фильтр и показать реальные группы $type-> с тирами"
        )
        btn_scan.clicked.connect(self._scan_groups)
        actions.addWidget(btn_scan)

        btn_defaults = QPushButton("Пороги по умолчанию")
        btn_defaults.clicked.connect(self._reset_thresholds)
        actions.addWidget(btn_defaults)

        btn_backups = QPushButton("Папка бэкапов")
        btn_backups.clicked.connect(lambda: _open_path(backup_dir()))
        actions.addWidget(btn_backups)
        actions.addStretch(1)

        self.btn_preview = QPushButton("Предпросмотр")
        self.btn_preview.clicked.connect(lambda: self._run_filter(dry_run=True))
        actions.addWidget(self.btn_preview)

        self.btn_apply = QPushButton("Обновить фильтр")
        self.btn_apply.setObjectName("Primary")
        self.btn_apply.clicked.connect(lambda: self._run_filter(dry_run=False))
        actions.addWidget(self.btn_apply)
        layout.addLayout(actions)

        self.filter_output = QPlainTextEdit()
        self.filter_output.setReadOnly(True)
        self.filter_output.setPlaceholderText(
            "Здесь появится отчёт: что и куда переехало, какие группы пропущены."
        )
        self.filter_output.setMinimumHeight(180)
        layout.addWidget(self.filter_output, 1)
        return page

    def _refresh_found_filters(self) -> None:
        self.list_found.clear()
        for path in list_filter_files():
            self.list_found.addItem(str(path))
        if self.list_found.count() == 0:
            self.list_found.addItem("Фильтры не найдены — укажи путь вручную")

    def _fill_thresholds(
        self,
        source: dict[str, list[float]] | None = None,
        active_groups: set[str] | None = None,
    ) -> None:
        thresholds = source or (self.ctx.cfg.get("filter.thresholds") or DEFAULT_TIER_THRESHOLDS)
        active = (
            {g.lower() for g in active_groups}
            if active_groups is not None
            else {g.lower() for g in (self.ctx.cfg.get("filter.groups") or [])}
        )
        self.table_thresholds.setRowCount(0)
        for group in sorted(thresholds):
            row = self.table_thresholds.rowCount()
            self.table_thresholds.insertRow(row)

            check = QTableWidgetItem()
            check.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
            check.setCheckState(
                Qt.CheckState.Checked if group.lower() in active else Qt.CheckState.Unchecked
            )
            self.table_thresholds.setItem(row, 0, check)

            name_item = QTableWidgetItem(group)
            name_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.table_thresholds.setItem(row, 1, name_item)

            values = ", ".join(_fmt(v) for v in thresholds[group])
            self.table_thresholds.setItem(row, 2, QTableWidgetItem(values))

    def _reset_thresholds(self) -> None:
        self._fill_thresholds(DEFAULT_TIER_THRESHOLDS)

    def _scan_groups(self) -> None:
        """Читает выбранный фильтр и заполняет таблицу реальными группами."""
        raw = self.edit_filter_path.text().strip()
        if not raw or not Path(raw).is_file():
            QMessageBox.warning(self, "PoE2 Helper", "Сначала укажи существующий файл фильтра.")
            return
        try:
            ff = FilterFile.load(Path(raw))
        except OSError as exc:
            QMessageBox.warning(self, "PoE2 Helper", f"Не удалось прочитать фильтр: {exc}")
            return

        detected = detect_groups(ff)
        if not detected:
            self.filter_output.setPlainText(
                "В файле не нашлось групп с тегами вида «$type->… $tier->tN».\n"
                "Такие теги есть у фильтров NeverSink и FilterBlade; "
                "самописный фильтр без тегов пересчитать нельзя."
            )
            return

        current, _ = self._collect_thresholds()
        thresholds: dict[str, list[float]] = {}
        for group in detected:
            thresholds[group] = current.get(
                group, list(DEFAULT_TIER_THRESHOLDS.get(group, DEFAULT_TIER_THRESHOLDS["currency"]))
            )

        self._fill_thresholds(thresholds, active_groups=set(detected))

        lines = [f"Найдено групп с нумерованными тирами: {len(detected)}", ""]
        for group, info in sorted(detected.items(), key=lambda kv: -len(kv[1]["base_types"])):
            tiers = ", ".join(f"t{t}" for t in info["tiers"])
            lines.append(f"  {group}: тиры {tiers} · баз {len(info['base_types'])}")
        lines.append(
            "\nГруппы отмечены галочками. Сними лишние, поправь пороги и жми «Предпросмотр»."
        )
        self.filter_output.setPlainText("\n".join(lines))

    def _collect_thresholds(self) -> tuple[dict[str, list[float]], list[str]]:
        thresholds: dict[str, list[float]] = {}
        groups: list[str] = []
        for row in range(self.table_thresholds.rowCount()):
            name = self.table_thresholds.item(row, 1).text().strip()
            if not name:
                continue
            raw = self.table_thresholds.item(row, 2).text()
            values: list[float] = []
            for part in raw.replace(";", ",").split(","):
                part = part.strip().replace(",", ".")
                if not part:
                    continue
                try:
                    values.append(float(part))
                except ValueError:
                    continue
            thresholds[name] = values or list(DEFAULT_TIER_THRESHOLDS.get(name, [10]))
            if self.table_thresholds.item(row, 0).checkState() == Qt.CheckState.Checked:
                groups.append(name)
        return thresholds, groups

    def _pick_filter(self) -> None:
        start = self.edit_filter_path.text().strip()
        if not start:
            found = list_filter_files()
            start = str(found[0].parent) if found else str(Path.home())
        path, _ = QFileDialog.getOpenFileName(
            self, "Выбери итем-фильтр", start, "Item filter (*.filter);;Все файлы (*)"
        )
        if path:
            self.edit_filter_path.setText(path)

    def _run_filter(self, dry_run: bool) -> None:
        if self._filter_busy:
            return
        self.save_settings(silent=True)
        if not self.ctx.cfg.get("filter.path"):
            QMessageBox.warning(self, "PoE2 Helper", "Сначала укажи файл фильтра.")
            return
        self._filter_busy = True
        self.btn_preview.setEnabled(False)
        self.btn_apply.setEnabled(False)
        self.filter_output.setPlainText("Работаю…\n")

        run_async(
            run_filter_update,
            on_done=self._on_filter_done,
            on_error=self._on_filter_error,
            on_progress=self._on_filter_progress,
            with_progress=True,
            cfg=self.ctx.cfg,
            ninja=self.ctx.ninja,
            dry_run=dry_run,
        )

    def _on_filter_progress(self, message: str) -> None:
        self.filter_output.appendPlainText(message)

    def _on_filter_done(self, result: FilterUpdateResult) -> None:
        self._filter_busy = False
        self.btn_preview.setEnabled(True)
        self.btn_apply.setEnabled(True)
        lines = [result.message]
        if result.report:
            lines.append("")
            lines.append(result.report.summary())
        if result.backup_path:
            lines.append(f"\nБэкап: {result.backup_path}")
        if result.diff:
            lines.append("\n--- Изменения в файле ---")
            lines.append(result.diff[:20000])
        self.filter_output.setPlainText("\n".join(lines))
        self.ctx.notify(
            "Итем-фильтр",
            result.message if result.ok else f"Ошибка: {result.message}",
        )

    def _on_filter_error(self, message: str) -> None:
        self._filter_busy = False
        self.btn_preview.setEnabled(True)
        self.btn_apply.setEnabled(True)
        self.filter_output.setPlainText(f"Ошибка: {message}")

    # ============================================================ настройки
    def _build_settings_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        general = QGroupBox("Общее")
        form = QFormLayout(general)
        self.edit_league = QLineEdit(self.ctx.cfg.get("league", ""))
        self.edit_league.setPlaceholderText("пусто = определять автоматически")
        form.addRow("Лига:", self.edit_league)

        self.edit_sessid = QLineEdit(self.ctx.cfg.get("poesessid", ""))
        self.edit_sessid.setEchoMode(QLineEdit.EchoMode.Password)
        self.edit_sessid.setPlaceholderText("нужен, если торговая площадка отвечает 403")
        form.addRow("POESESSID:", self.edit_sessid)

        self.edit_hotkey = QLineEdit(self.ctx.cfg.get("hotkey_price_check", "Ctrl+D"))
        form.addRow("Хоткей оценки:", self.edit_hotkey)
        layout.addWidget(general)

        overlay_box = QGroupBox("Оверлей")
        oform = QFormLayout(overlay_box)
        self.spn_opacity = QDoubleSpinBox()
        self.spn_opacity.setRange(0.3, 1.0)
        self.spn_opacity.setSingleStep(0.02)
        self.spn_opacity.setValue(float(self.ctx.cfg.get("overlay.opacity", 0.96)))
        oform.addRow("Непрозрачность:", self.spn_opacity)

        self.spn_width = QSpinBox()
        self.spn_width.setRange(380, 1200)
        self.spn_width.setValue(int(self.ctx.cfg.get("overlay.width", 520)))
        oform.addRow("Ширина, px:", self.spn_width)

        self.chk_close_focus = QCheckBox("Прятать при потере фокуса")
        self.chk_close_focus.setChecked(bool(self.ctx.cfg.get("overlay.close_on_focus_loss", True)))
        oform.addRow(self.chk_close_focus)

        self.chk_remember_pos = QCheckBox("Запоминать позицию окна")
        self.chk_remember_pos.setChecked(bool(self.ctx.cfg.get("overlay.remember_position", False)))
        oform.addRow(self.chk_remember_pos)
        layout.addWidget(overlay_box)

        search_box = QGroupBox("Поиск")
        sform = QFormLayout(search_box)
        self.chk_autosearch = QCheckBox("Искать сразу при открытии оверлея")
        self.chk_autosearch.setChecked(bool(self.ctx.cfg.get("search.auto_search_on_open", True)))
        sform.addRow(self.chk_autosearch)

        self.spn_tolerance = QDoubleSpinBox()
        self.spn_tolerance.setRange(0.0, 0.9)
        self.spn_tolerance.setSingleStep(0.05)
        self.spn_tolerance.setValue(float(self.ctx.cfg.get("search.roll_tolerance", 0.1)))
        self.spn_tolerance.setToolTip("0.10 = нижняя граница на 10% ниже ролла предмета")
        sform.addRow("Допуск ролла:", self.spn_tolerance)

        self.spn_listings = QSpinBox()
        self.spn_listings.setRange(5, 50)
        self.spn_listings.setValue(int(self.ctx.cfg.get("search.default_listings", 20)))
        sform.addRow("Лотов в выдаче:", self.spn_listings)

        self.chk_min_only = QCheckBox("Ставить только нижнюю границу")
        self.chk_min_only.setChecked(bool(self.ctx.cfg.get("search.use_min_only", True)))
        sform.addRow(self.chk_min_only)
        layout.addWidget(search_box)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        btn_save = QPushButton("Сохранить")
        btn_save.setObjectName("Primary")
        btn_save.clicked.connect(lambda: self.save_settings(silent=False))
        buttons.addWidget(btn_save)
        layout.addLayout(buttons)
        layout.addStretch(1)
        return page

    # ================================================================ общее
    def save_settings(self, silent: bool = True) -> None:
        cfg = self.ctx.cfg
        cfg.set("league", self.edit_league.text().strip())
        cfg.set("poesessid", self.edit_sessid.text().strip())
        cfg.set("hotkey_price_check", self.edit_hotkey.text().strip() or "Ctrl+D")

        cfg.set("overlay.opacity", float(self.spn_opacity.value()))
        cfg.set("overlay.width", int(self.spn_width.value()))
        cfg.set("overlay.close_on_focus_loss", self.chk_close_focus.isChecked())
        cfg.set("overlay.remember_position", self.chk_remember_pos.isChecked())

        cfg.set("search.auto_search_on_open", self.chk_autosearch.isChecked())
        cfg.set("search.roll_tolerance", float(self.spn_tolerance.value()))
        cfg.set("search.default_listings", int(self.spn_listings.value()))
        cfg.set("search.use_min_only", self.chk_min_only.isChecked())

        cfg.set("filter.path", self.edit_filter_path.text().strip())
        cfg.set("filter.update_on_start", self.chk_filter_autostart.isChecked())
        cfg.set("filter.write_in_place", self.chk_filter_inplace.isChecked())
        cfg.set("filter.make_backup", self.chk_filter_backup.isChecked())
        cfg.set("filter.auto_detect_groups", self.chk_auto_groups.isChecked())
        cfg.set("filter.price_unit", self.cmb_unit.currentData())
        thresholds, groups = self._collect_thresholds()
        cfg.set("filter.thresholds", thresholds)
        cfg.set("filter.groups", groups)

        cfg.save()
        self.ctx.apply_settings()
        self.refresh_status()
        if not silent:
            self.lbl_bottom.setText("Настройки сохранены.")

    def refresh_status(self) -> None:
        cfg = self.ctx.cfg
        self.lbl_league.setText(f"Лига: {self.ctx.league or 'не определена'}")
        db = self.ctx.stats_db
        if db.is_empty:
            self.lbl_stats.setText("Пул модов: не загружен")
        else:
            self.lbl_stats.setText(f"Пул модов: {len(db.entries)} записей")
        hotkey = cfg.get("hotkey_price_check", "Ctrl+D")
        self.lbl_hotkeys.setText(
            f"Хоткей оценки: <b>{hotkey}</b> — наведи курсор на предмет в игре и нажми."
        )
        self.lbl_hotkeys.setTextFormat(Qt.TextFormat.RichText)
        warnings = list(self.ctx.warnings)
        self.lbl_warnings.setText("\n".join(warnings))
        self.lbl_help.setText(
            "1. Запусти PoE2 в режиме «Окно без рамки».<br>"
            f"2. Наведи курсор на предмет и нажми <b>{hotkey}</b>.<br>"
            "3. В оверлее сними лишние моды, поправь границы, нажми «Искать».<br>"
            "4. «＋ Мод из пула» добавит в запрос любой мод торговой площадки, "
            "даже если его нет на предмете.<br>"
            "5. Вкладка «Итем-фильтр» пересчитывает тиры NeverSink по актуальным ценам."
        )


def _fmt(value: float) -> str:
    if abs(value - round(value)) < 1e-9:
        return str(int(round(value)))
    return f"{value:g}"


def _open_path(path: Path) -> None:
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QDesktopServices

    QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
