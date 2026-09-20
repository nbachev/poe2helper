"""Переиспользуемые элементы оверлея."""

from __future__ import annotations

from PySide6.QtCore import QRegularExpression, Qt, Signal
from PySide6.QtGui import QRegularExpressionValidator
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..trade.query import LOWER_IS_BETTER, ModFilter
from .style import COLORS

# Допускаем пустую строку, минус, цифры и один разделитель дробной части:
# на русской раскладке Windows это запятая, в наших расчётах — точка.
NUMBER_INPUT_RE = QRegularExpression(r"^-?\d{0,7}([.,]\d{0,4})?$")


class BoundSpin(QLineEdit):
    """Числовое поле, где «пусто» = граница не задана.

    Раньше это был QDoubleSpinBox, и подпись «мин»/«макс» показывалась
    через specialValueText — то есть была настоящим значением поля при
    минимуме, и её приходилось стирать перед вводом. Здесь это обычный
    placeholder: он виден, только пока поле пустое, и значением не является.

    Значение применяется сразу при вводе, а также по потере фокуса и по
    Enter — ждать Enter не нужно.
    """

    valueChanged = Signal(float)  # имя сохранено ради совместимости

    def __init__(self, placeholder: str = "—", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._decimals = 2
        self.setPlaceholderText(placeholder)
        self.setValidator(QRegularExpressionValidator(NUMBER_INPUT_RE, self))
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setFixedWidth(58)
        self.setClearButtonEnabled(False)

        self.textEdited.connect(self._on_text_edited)
        self.editingFinished.connect(self._on_editing_finished)

    # ------------------------------------------------------------- значение
    def setDecimals(self, decimals: int) -> None:  # noqa: N802 (как было у спинбокса)
        self._decimals = max(0, int(decimals))

    def bound(self) -> float | None:
        text = self.text().strip().replace(",", ".")
        if not text or text in ("-", ".", "-."):
            return None
        try:
            value = float(text)
        except ValueError:
            return None
        return round(value, self._decimals) if self._decimals else float(round(value))

    def set_bound(self, value: float | None) -> None:
        """Программная установка значения: сигналы при этом не идут."""
        self.setText("" if value is None else self._format(value))

    def clear_bound(self) -> None:
        self.set_bound(None)

    def _format(self, value: float) -> str:
        value = round(float(value), self._decimals)
        if abs(value - round(value)) < 1e-9:
            return str(int(round(value)))
        return f"{value:g}"

    # -------------------------------------------------------------- события
    def _emit(self) -> None:
        value = self.bound()
        self.valueChanged.emit(0.0 if value is None else value)

    def _on_text_edited(self, _text: str) -> None:
        # Живой отклик: пересчёт идёт по мере ввода, без Enter
        self._emit()

    def _on_editing_finished(self) -> None:
        # Клик вне поля или Enter: приводим текст к единому виду
        value = self.bound()
        current = self.text().strip()
        formatted = "" if value is None else self._format(value)
        if current != formatted:
            self.setText(formatted)
        self._emit()


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
        min_spin.setToolTip("Нижняя граница. Пусто — не ограничивать.")
        min_spin.valueChanged.connect(lambda _=0.0, m=mod: self._on_value(m))
        line.addWidget(min_spin)

        max_spin = BoundSpin("макс")
        max_spin.setToolTip("Верхняя граница. Пусто — не ограничивать.")
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

        text = mod.text
        if mod.range_text:
            # Разброс тира видно сразу, без наведения мыши
            text += f"   ({mod.range_text})"
        part["label"].setText(text)
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
        if mod.range_text:
            tip += f"\nРазброс тира: {mod.range_text}"
            if mod.roll_percent is not None:
                tip += f" · ролл {mod.roll_percent:.0f}%"
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
    value_edited = Signal()  # границу правил руками, а не пересчёт по модам

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
        self.min_spin.setToolTip("Нижняя граница. Пусто — не ограничивать.")
        self.min_spin.setDecimals(equip.decimals)
        self.min_spin.set_bound(equip.min_value)
        self.min_spin.valueChanged.connect(self._on_value)
        layout.addWidget(self.min_spin)

        self.max_spin = BoundSpin("макс")
        self.max_spin.setToolTip("Верхняя граница. Пусто — не ограничивать.")
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
        self.value_edited.emit()

    def _sync_style(self) -> None:
        color = COLORS["text"] if self.equip.enabled else COLORS["text_dim"]
        weight = "600" if self.equip.enabled else "400"
        self.check.setStyleSheet(f"color: {color}; font-weight: {weight};")

    def refresh(self) -> None:
        """Синхронизирует виджеты с моделью, не поднимая сигналов."""
        self.check.blockSignals(True)
        self.check.setChecked(self.equip.enabled)
        self.check.blockSignals(False)
        for spin, value in ((self.min_spin, self.equip.min_value), (self.max_spin, self.equip.max_value)):
            spin.blockSignals(True)
            spin.set_bound(value)
            spin.blockSignals(False)
        self._sync_style()

    def apply_projection(self, value: float | None, explain: str = "") -> None:
        """Подставляет пересчитанное по модам значение.

        Для перезарядки арбалета меньше — лучше, поэтому там меняется
        верхняя граница, а не нижняя.
        """
        if value is None:
            return
        rounded = round(value, self.equip.decimals) if self.equip.decimals else round(value)
        if self.equip.key in LOWER_IS_BETTER:
            self.equip.max_value = rounded
        else:
            self.equip.min_value = rounded
        base = f"На предмете: {_fmt_value(self.equip.value, self.equip.decimals)}"
        self.check.setToolTip(f"{base}\n{explain}" if explain else base)
        self.refresh()


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
