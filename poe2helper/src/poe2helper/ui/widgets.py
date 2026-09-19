"""Переиспользуемые элементы оверлея."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QWidget,
)

from ..trade.query import ModFilter
from .style import COLORS

NO_VALUE = -99999.0


class BoundSpin(QDoubleSpinBox):
    """Числовое поле, где «пусто» = граница не задана."""

    def __init__(self, placeholder: str = "—", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setRange(NO_VALUE, 99999.0)
        self.setDecimals(2)
        self.setSingleStep(1.0)
        self.setValue(NO_VALUE)
        self.setSpecialValueText(placeholder)
        self.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.NoButtons)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setFixedWidth(58)
        self.setKeyboardTracking(False)

    def textFromValue(self, value: float) -> str:  # noqa: N802 (Qt API)
        if value == NO_VALUE:
            return self.specialValueText()
        if abs(value - round(value)) < 1e-9:
            return str(int(round(value)))
        return f"{value:g}"

    def bound(self) -> float | None:
        value = self.value()
        return None if value == NO_VALUE else value

    def set_bound(self, value: float | None) -> None:
        self.setValue(NO_VALUE if value is None else float(value))

    def clear_bound(self) -> None:
        self.setValue(NO_VALUE)


class ModRow(QWidget):
    """Строка модификатора: вкл/выкл, текст, min/max, удаление."""

    changed = Signal()
    removed = Signal(object)

    def __init__(self, mod: ModFilter, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.mod = mod

        layout = QHBoxLayout(self)
        layout.setContentsMargins(2, 1, 2, 1)
        layout.setSpacing(6)

        self.check = QCheckBox()
        self.check.setChecked(mod.enabled and mod.matched)
        self.check.setEnabled(mod.matched)
        self.check.toggled.connect(self._on_toggle)
        layout.addWidget(self.check)

        self.label = QLabel(self._label_text())
        self.label.setWordWrap(False)
        self.label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        if not mod.matched:
            self.label.setObjectName("Unmatched")
            self.label.setToolTip("Мод не найден в пуле торговой площадки — в поиск не пойдёт")
        else:
            self.label.setToolTip(f"{mod.stat_id}  ({mod.kind})")
        layout.addWidget(self.label, 1)

        self.tag = QLabel(_kind_short(mod.kind))
        self.tag.setStyleSheet(f"color: {COLORS['text_dim']}; font-size: 10px;")
        self.tag.setFixedWidth(30)
        layout.addWidget(self.tag)

        self.min_spin = BoundSpin("мин")
        self.min_spin.set_bound(mod.min_value)
        self.min_spin.valueChanged.connect(self._on_value)
        self.min_spin.setEnabled(mod.matched and mod.option_id is None)
        layout.addWidget(self.min_spin)

        self.max_spin = BoundSpin("макс")
        self.max_spin.set_bound(mod.max_value)
        self.max_spin.valueChanged.connect(self._on_value)
        self.max_spin.setEnabled(mod.matched and mod.option_id is None)
        layout.addWidget(self.max_spin)

        self.btn_remove = QPushButton("✕")
        self.btn_remove.setObjectName("Flat")
        self.btn_remove.setFixedWidth(22)
        self.btn_remove.setToolTip("Убрать мод из списка")
        self.btn_remove.clicked.connect(lambda: self.removed.emit(self))
        layout.addWidget(self.btn_remove)

        self._sync_style()

    # --------------------------------------------------------------- helpers
    def _label_text(self) -> str:
        text = self.mod.text
        if self.mod.source_value is not None and "#" not in text:
            return text
        return text

    def _on_toggle(self, checked: bool) -> None:
        self.mod.enabled = checked
        self._sync_style()
        self.changed.emit()

    def _on_value(self) -> None:
        self.mod.min_value = self.min_spin.bound()
        self.mod.max_value = self.max_spin.bound()
        self.changed.emit()

    def _sync_style(self) -> None:
        if not self.mod.matched:
            color = COLORS["text_dim"]
        elif self.mod.enabled:
            color = COLORS["text"]
        else:
            color = COLORS["text_dim"]
        weight = "600" if self.mod.enabled else "400"
        style = f"color: {color}; font-weight: {weight};"
        if not self.mod.matched:
            style += " font-style: italic;"
        self.label.setStyleSheet(style)

    def set_enabled_state(self, enabled: bool) -> None:
        if not self.mod.matched:
            return
        self.check.setChecked(enabled)


class EquipRow(QWidget):
    """Строка параметра вещи: броня, ДПС, крит и т. п."""

    changed = Signal()

    def __init__(self, equip, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.equip = equip

        layout = QHBoxLayout(self)
        layout.setContentsMargins(2, 1, 2, 1)
        layout.setSpacing(4)

        self.check = QCheckBox(equip.label)
        self.check.setChecked(equip.enabled)
        self.check.setMinimumWidth(92)
        if equip.value is not None:
            self.check.setToolTip(f"На предмете: {_fmt_value(equip.value, equip.decimals)}")
        self.check.toggled.connect(self._on_toggle)
        layout.addWidget(self.check)

        self.min_spin = BoundSpin("мин")
        self.min_spin.setDecimals(equip.decimals)
        self.min_spin.set_bound(equip.min_value)
        self.min_spin.valueChanged.connect(self._on_value)
        layout.addWidget(self.min_spin)

        self.max_spin = BoundSpin("макс")
        self.max_spin.setDecimals(equip.decimals)
        self.max_spin.set_bound(equip.max_value)
        self.max_spin.valueChanged.connect(self._on_value)
        layout.addWidget(self.max_spin)

        self._sync_style()

    def _on_toggle(self, checked: bool) -> None:
        self.equip.enabled = checked
        self._sync_style()
        self.changed.emit()

    def _on_value(self) -> None:
        self.equip.min_value = self.min_spin.bound()
        self.equip.max_value = self.max_spin.bound()
        self.changed.emit()

    def _sync_style(self) -> None:
        color = COLORS["text"] if self.equip.enabled else COLORS["text_dim"]
        weight = "600" if self.equip.enabled else "400"
        self.check.setStyleSheet(f"color: {color}; font-weight: {weight};")


def _fmt_value(value: float, decimals: int) -> str:
    if decimals <= 0:
        return str(int(round(value)))
    return f"{value:.{decimals}f}"


def _kind_short(kind: str) -> str:
    return {
        "explicit": "exp",
        "implicit": "imp",
        "fractured": "frac",
        "desecrated": "des",
        "rune": "rune",
        "enchant": "ench",
        "crafted": "crft",
        "pseudo": "pse",
        "sanctum": "sanc",
        "skill": "skill",
    }.get(kind, kind[:4])
