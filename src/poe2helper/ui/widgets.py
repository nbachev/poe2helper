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
    QVBoxLayout,
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
    pick_requested = Signal(object, object)  # (строка, конкретная часть мода)

    def __init__(self, mods, parent: QWidget | None = None) -> None:
        """``mods`` — один ModFilter либо список частей одного аффикса.

        Гибридный мод («40% increased Armour» + «+123 to Stun Threshold»)
        приходит сюда списком: галочка и крестик у него общие, а границы
        min/max — свои у каждой части, потому что торговая площадка ищет
        по каждой характеристике отдельно.
        """
        super().__init__(parent)
        self.mods: list[ModFilter] = [mods] if isinstance(mods, ModFilter) else list(mods)
        self.mod = self.mods[0]  # для кода, которому нужна одна «главная» часть

        layout = QHBoxLayout(self)
        layout.setContentsMargins(2, 1, 2, 1)
        layout.setSpacing(6)

        top = Qt.AlignmentFlag.AlignTop if len(self.mods) > 1 else Qt.AlignmentFlag.AlignVCenter

        self.check = QCheckBox()
        self.check.setToolTip("Включить аффикс в поиск")
        self.check.toggled.connect(self._on_toggle)
        layout.addWidget(self.check, 0, top)

        stack = QVBoxLayout()
        stack.setContentsMargins(0, 0, 0, 0)
        stack.setSpacing(1)
        layout.addLayout(stack, 1)

        self.parts: list[dict] = []
        for mod in self.mods:
            self.parts.append(self._build_part(mod, stack))

        # ссылки на виджеты первой части — совместимость со старым кодом
        first = self.parts[0]
        self.label = first["label"]
        self.tag = first["tag"]
        self.min_spin = first["min"]
        self.max_spin = first["max"]
        self.btn_pick = first["pick"]

        self.btn_remove = QPushButton("✕")
        self.btn_remove.setObjectName("Flat")
        self.btn_remove.setFixedWidth(22)
        self.btn_remove.setToolTip("Убрать мод из списка")
        self.btn_remove.clicked.connect(lambda: self.removed.emit(self))
        layout.addWidget(self.btn_remove, 0, top)

        self.refresh()

    def _build_part(self, mod: ModFilter, stack: QVBoxLayout) -> dict:
        line = QHBoxLayout()
        line.setContentsMargins(0, 0, 0, 0)
        line.setSpacing(6)

        label = QLabel()
        label.setWordWrap(False)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        line.addWidget(label, 1)

        tag = QLabel()
        tag.setStyleSheet(f"color: {COLORS['text_dim']}; font-size: 10px;")
        tag.setFixedWidth(30)
        line.addWidget(tag)

        # Кнопка ручного выбора: показывается, когда часть не опознана
        pick = QPushButton("🔍")
        pick.setObjectName("Flat")
        pick.setFixedWidth(24)
        pick.setToolTip("Выбрать подходящий мод из пула вручную")
        pick.clicked.connect(lambda _=False, m=mod: self.pick_requested.emit(self, m))
        line.addWidget(pick)

        min_spin = BoundSpin("мин")
        min_spin.valueChanged.connect(lambda _=0.0, m=mod: self._on_value(m))
        line.addWidget(min_spin)

        max_spin = BoundSpin("макс")
        max_spin.valueChanged.connect(lambda _=0.0, m=mod: self._on_value(m))
        line.addWidget(max_spin)

        stack.addLayout(line)
        return {"mod": mod, "label": label, "tag": tag, "pick": pick, "min": min_spin, "max": max_spin}

    # ------------------------------------------------------------- состояние
    @property
    def matched(self) -> bool:
        return any(m.matched for m in self.mods)

    @property
    def enabled(self) -> bool:
        return any(m.enabled and m.matched for m in self.mods)

    def refresh(self) -> None:
        """Приводит виджеты в соответствие с состоянием частей."""
        self.check.blockSignals(True)
        self.check.setChecked(self.enabled)
        self.check.setEnabled(self.matched)
        self.check.blockSignals(False)

        for index, part in enumerate(self.parts):
            self._refresh_part(part, first=index == 0)

    def _refresh_part(self, part: dict, first: bool) -> None:
        mod = part["mod"]
        editable = mod.matched and mod.option_id is None

        part["label"].setText(mod.text)
        # Тир относится ко всему аффиксу, поэтому показываем его один раз
        if first and mod.tier:
            part["tag"].setText(f"T{mod.tier}")
        elif first:
            part["tag"].setText(_kind_short(mod.kind) if mod.matched else "—")
        else:
            part["tag"].setText("" if mod.matched else "—")
        part["pick"].setVisible(not mod.matched)

        for key, value in (("min", mod.min_value), ("max", mod.max_value)):
            spin = part[key]
            spin.blockSignals(True)
            spin.set_bound(value)
            spin.setEnabled(editable)
            spin.blockSignals(False)

        if mod.matched:
            tip = f"{mod.stat_id}  ({mod.kind})"
        else:
            tip = (
                "Мод не опознан — в поиск не пойдёт.\n"
                "Нажми 🔍, чтобы выбрать подходящий из пула вручную."
            )
        if mod.affix:
            tip += f"\n{mod.affix}"
        if len(self.mods) > 1:
            tip += "\nГибридный мод: части ищутся отдельно, галочка общая."
        part["label"].setToolTip(tip)
        self._style_part(part)

    def _style_part(self, part: dict) -> None:
        mod = part["mod"]
        color = COLORS["text"] if (mod.enabled and mod.matched) else COLORS["text_dim"]
        weight = "600" if (mod.enabled and mod.matched) else "400"
        style = f"color: {color}; font-weight: {weight};"
        if not mod.matched:
            style += " font-style: italic;"
        part["label"].setStyleSheet(style)

    # --------------------------------------------------------------- события
    def _on_toggle(self, checked: bool) -> None:
        for mod in self.mods:
            if mod.matched:
                mod.enabled = checked
        for part in self.parts:
            self._style_part(part)
        self.changed.emit()

    def _on_value(self, mod: ModFilter) -> None:
        part = next(p for p in self.parts if p["mod"] is mod)
        mod.min_value = part["min"].bound()
        mod.max_value = part["max"].bound()
        self.changed.emit()

    def set_enabled_state(self, enabled: bool) -> None:
        if not self.matched:
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
