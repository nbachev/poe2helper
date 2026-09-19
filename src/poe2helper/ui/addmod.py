"""Диалог «Добавить мод из пула» — поиск по всем модам торговой площадки."""

from __future__ import annotations

import re

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..parser.stats_db import StatEntry, StatsDB
from .style import QSS

KIND_LABELS = {
    "": "Все категории",
    "explicit": "Обычные (explicit)",
    "implicit": "Имплиситы",
    "fractured": "Fractured",
    "desecrated": "Desecrated",
    "rune": "Руны",
    "enchant": "Энчанты",
    "crafted": "Крафт",
    "pseudo": "Псевдо",
    "sanctum": "Sanctum",
    "skill": "Скиллы",
}


class AddModDialog(QDialog):
    """Возвращает выбранную запись пула через ``selected_entry``."""

    def __init__(
        self,
        db: StatsDB,
        parent: QWidget | None = None,
        initial_query: str = "",
        title: str = "Добавить мод из пула",
    ) -> None:
        super().__init__(parent)
        self.db = db
        self.selected_entry: StatEntry | None = None
        self.selected_option: tuple[int | str, str] | None = None

        self.setWindowTitle(title)
        self.setModal(True)
        self.resize(660, 480)
        self.setStyleSheet(QSS)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        top = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Начни печатать: life, resist, attack speed…")
        self.search.setClearButtonEnabled(True)
        top.addWidget(self.search, 1)

        self.kind_box = QComboBox()
        kinds = [""] + db.kinds()
        for kind in kinds:
            self.kind_box.addItem(KIND_LABELS.get(kind, kind), kind)
        self.kind_box.setFixedWidth(180)
        top.addWidget(self.kind_box)
        root.addLayout(top)

        self.list = QListWidget()
        self.list.setAlternatingRowColors(False)
        root.addWidget(self.list, 1)

        self.option_box = QComboBox()
        self.option_box.setVisible(False)
        root.addWidget(self.option_box)

        self.hint = QLabel("Всего модов в пуле: %d" % len(db.entries))
        self.hint.setObjectName("Hint")
        root.addWidget(self.hint)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.btn_cancel = QPushButton("Отмена")
        self.btn_add = QPushButton("Добавить")
        self.btn_add.setObjectName("Primary")
        self.btn_add.setDefault(True)
        buttons.addWidget(self.btn_cancel)
        buttons.addWidget(self.btn_add)
        root.addLayout(buttons)

        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(160)
        self._debounce.timeout.connect(self._refresh)

        self.search.textChanged.connect(lambda _: self._debounce.start())
        self.kind_box.currentIndexChanged.connect(lambda _: self._refresh())
        self.list.currentItemChanged.connect(self._on_current_changed)
        self.list.itemDoubleClicked.connect(lambda _: self._accept())
        self.btn_add.clicked.connect(self._accept)
        self.btn_cancel.clicked.connect(self.reject)

        if initial_query:
            # Числа в поиске только мешают: ищем по словам мода
            self.search.setText(re.sub(r"[+\-\d.%()]+", " ", initial_query).strip())
        self._refresh()
        self.search.setFocus()
        self.search.selectAll()

    # ------------------------------------------------------------------ ui
    def _refresh(self) -> None:
        query = self.search.text().strip()
        kind = self.kind_box.currentData() or ""
        kinds = [kind] if kind else None
        entries = self.db.search(query, kinds=kinds, limit=400)

        self.list.clear()
        for entry in entries:
            item = QListWidgetItem(entry.text)
            item.setData(Qt.ItemDataRole.UserRole, entry)
            item.setToolTip(f"{entry.id}\nГруппа: {entry.group}")
            suffix = f"   · {entry.kind}"
            item.setText(entry.text + suffix)
            self.list.addItem(item)
        self.hint.setText(
            f"Найдено: {len(entries)}" + ("  (показаны первые 400)" if len(entries) >= 400 else "")
        )
        if entries:
            self.list.setCurrentRow(0)

    def _on_current_changed(self, current: QListWidgetItem | None, previous=None) -> None:
        entry = current.data(Qt.ItemDataRole.UserRole) if current else None
        self.option_box.clear()
        if isinstance(entry, StatEntry) and entry.has_options:
            self.option_box.setVisible(True)
            for opt_id, opt_text in entry.options:
                self.option_box.addItem(opt_text, opt_id)
        else:
            self.option_box.setVisible(False)

    def _accept(self) -> None:
        current = self.list.currentItem()
        entry = current.data(Qt.ItemDataRole.UserRole) if current else None
        if not isinstance(entry, StatEntry):
            return
        self.selected_entry = entry
        if entry.has_options and self.option_box.count():
            self.selected_option = (
                self.option_box.currentData(),
                self.option_box.currentText(),
            )
        else:
            self.selected_option = None
        self.accept()
