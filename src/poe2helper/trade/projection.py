"""Пересчёт параметров вещи с учётом выбранных модов.

Задача: пользователь добавил в поиск «+100 to Armour» или потребовал
«не меньше 110% increased Armour» — каким тогда станет итоговое значение
брони, которое ищется в фильтре ``ar``?

Наивно складывать нельзя: в игре плоские прибавки и проценты действуют
по-разному. Локальные защиты считаются так::

    показанное = (база + плоские) * (1 + проценты/100) * (1 + качество/100)

Качество здесь именно отдельный множитель, а не слагаемое к процентам.
Проверено на реальном предмете: щит Tawhoan Tower Shield с базой 264
(значение с белой основы), плоской прибавкой +216, процентами
99 + 40 + 18 (последние — с руны) и качеством 20% показывает в игре 1480::

    (264 + 216) * 2.57 * 1.2 = 1480.32  ->  1480

Вариант со слагаемым дал бы 1479 и нецелую базу 318.3 — мимо. Тот же
расчёт доказывает, что проценты с руны считаются локальными для
предмета: без них база вышла бы 300, а не 264.

Отсюда следствие: знать базу предмета не нужно. Из показанного значения
восстанавливается скобка ``(база + плоские)``, а дальше применяются
изменения::

    S = показанное / ((1 + проценты/100) * (1 + качество/100))
    новое = (S + Δплоских) * (1 + (проценты + Δпроцентов)/100) * (1 + качество/100)

Так плоская прибавка корректно умножается и на проценты, и на качество,
а новый процент корректно применяется к уже накопленным плоским.

Тот же приём применяется к физическому урону оружия (качество влияет)
и к скорости атаки с критом (качество ни при чём).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..parser.item import ParsedItem
from ..parser.stats_db import normalize

# Ключи совпадают с полями equipment_filters торговой площадки
AR, EV, ES, PHYS, ELE, APS, CRIT = "ar", "ev", "es", "phys", "ele", "aps", "crit"

# Качество добавляется к процентам для защит и физического урона,
# но не для скорости атаки и шанса крита.
QUALITY_APPLIES = {AR, EV, ES, PHYS}


@dataclass(frozen=True)
class Contribution:
    """Во что превращается мод: куда и каким образом он вкладывается."""

    targets: tuple[str, ...]
    kind: str  # "flat" | "inc"


# Порядок важен: более длинные формулировки идут первыми, иначе
# «increased Armour» съест «increased Armour and Evasion».
RULES: list[tuple[re.Pattern[str], Contribution]] = [
    # --- проценты, гибридные защиты ---
    (re.compile(r"^#% increased armour, evasion and energy shield$"), Contribution((AR, EV, ES), "inc")),
    (re.compile(r"^#% increased armour and evasion$"), Contribution((AR, EV), "inc")),
    (re.compile(r"^#% increased armour and energy shield$"), Contribution((AR, ES), "inc")),
    (re.compile(r"^#% increased evasion and energy shield$"), Contribution((EV, ES), "inc")),
    (re.compile(r"^#% increased armour$"), Contribution((AR,), "inc")),
    (re.compile(r"^#% increased evasion( rating)?$"), Contribution((EV,), "inc")),
    (re.compile(r"^#% increased (maximum )?energy shield$"), Contribution((ES,), "inc")),
    (re.compile(r"^#% increased defences$"), Contribution((AR, EV, ES), "inc")),
    # --- плоские защиты ---
    (re.compile(r"^# to armour and evasion( rating)?$"), Contribution((AR, EV), "flat")),
    (re.compile(r"^# to armour and (maximum )?energy shield$"), Contribution((AR, ES), "flat")),
    (re.compile(r"^# to evasion( rating)? and (maximum )?energy shield$"), Contribution((EV, ES), "flat")),
    (re.compile(r"^# to armour$"), Contribution((AR,), "flat")),
    (re.compile(r"^# to evasion( rating)?$"), Contribution((EV,), "flat")),
    (re.compile(r"^# to maximum energy shield$"), Contribution((ES,), "flat")),
    # --- оружие ---
    (re.compile(r"^#% increased physical damage$"), Contribution((PHYS,), "inc")),
    (re.compile(r"^adds # to # physical damage.*$"), Contribution((PHYS,), "flat")),
    (re.compile(r"^adds # to # (fire|cold|lightning) damage.*$"), Contribution((ELE,), "flat")),
    (re.compile(r"^#% increased (attack )?speed$"), Contribution((APS,), "inc")),
    (re.compile(r"^#% increased critical (hit|strike) chance$"), Contribution((CRIT,), "inc")),
]


def classify(text: str) -> Contribution | None:
    """Определяет вклад мода по его тексту. ``None`` — мод не влияет."""
    key = normalize(text)
    for pattern, contribution in RULES:
        if pattern.match(key):
            return contribution
    return None


def mod_amount(text: str, values: list[float]) -> float | None:
    """Величина вклада: для «Adds # to #» это среднее диапазона."""
    if not values:
        return None
    key = normalize(text)
    if re.search(r"# to #", key) and len(values) >= 2:
        return (values[0] + values[1]) / 2
    return values[0]


@dataclass
class Totals:
    """Слагаемые по одному параметру."""

    displayed: float | None = None
    inc_on_item: float = 0.0
    quality: float = 0.0
    quality_multiplies: bool = False

    @property
    def quality_multiplier(self) -> float:
        """Качество — отдельный множитель, и не ко всем параметрам."""
        return 1 + self.quality / 100 if self.quality_multiplies else 1.0

    def inc_multiplier(self, extra_percent: float = 0.0) -> float:
        return 1 + (self.inc_on_item + extra_percent) / 100

    @property
    def multiplier(self) -> float:
        return self.inc_multiplier() * self.quality_multiplier

    @property
    def flat_sum(self) -> float | None:
        """Скобка ``(база + плоские)``, восстановленная из показанного."""
        if self.displayed is None:
            return None
        mult = self.multiplier
        return self.displayed / mult if mult else None


@dataclass
class Projection:
    """Результат пересчёта: значения по ключам фильтров + пояснение."""

    values: dict[str, float] = field(default_factory=dict)
    explain: dict[str, str] = field(default_factory=dict)


def item_totals(item: ParsedItem) -> dict[str, Totals]:
    """Собирает по предмету показанные значения и проценты его модов."""
    quality = float(item.quality or 0)
    eq = item.equip
    displayed = {
        AR: eq.armour,
        EV: eq.evasion,
        ES: eq.energy_shield,
        PHYS: eq.phys_avg,
        ELE: eq.ele_avg,
        APS: eq.aps,
        CRIT: eq.crit,
    }
    totals = {
        key: Totals(
            displayed=value,
            quality=quality,
            quality_multiplies=key in QUALITY_APPLIES,
        )
        for key, value in displayed.items()
    }

    for mod in item.mods:
        contribution = classify(mod.text)
        if contribution is None or contribution.kind != "inc":
            continue
        amount = mod_amount(mod.text, mod.values)
        if amount is None:
            continue
        for key in contribution.targets:
            totals[key].inc_on_item += amount

    return totals


def project(item: ParsedItem, wanted: list[tuple[str, list[float], float | None]]) -> Projection:
    """Считает параметры вещи с учётом желаемых значений модов.

    ``wanted`` — список ``(текст мода, значения на предмете, желаемое
    значение)``. Желаемое ``None`` означает «оставить как на предмете».
    """
    totals = item_totals(item)
    flat_delta: dict[str, float] = {}
    inc_delta: dict[str, float] = {}

    for text, values, target in wanted:
        contribution = classify(text)
        if contribution is None:
            continue
        actual = mod_amount(text, values) or 0.0
        effective = actual if target is None else float(target)
        delta = effective - actual
        if not delta:
            continue
        bucket = flat_delta if contribution.kind == "flat" else inc_delta
        for key in contribution.targets:
            bucket[key] = bucket.get(key, 0.0) + delta

    result = Projection()
    for key, totals_for_key in totals.items():
        base_sum = totals_for_key.flat_sum
        if base_sum is None:
            continue
        d_flat = flat_delta.get(key, 0.0)
        d_inc = inc_delta.get(key, 0.0)
        if not d_flat and not d_inc:
            result.values[key] = totals_for_key.displayed
            continue
        # Проценты меняются внутри своей скобки, качество остаётся снаружи
        value = max(
            0.0,
            (base_sum + d_flat)
            * totals_for_key.inc_multiplier(d_inc)
            * totals_for_key.quality_multiplier,
        )
        result.values[key] = value
        result.explain[key] = (
            f"на предмете {totals_for_key.displayed:g}; "
            f"плоские {d_flat:+g}, проценты {d_inc:+g}% → {value:.0f}"
        )

    _add_derived(result)
    return result


def _add_derived(result: Projection) -> None:
    """ДПС считается из уже пересчитанных урона и скорости атаки."""
    aps = result.values.get(APS)
    if not aps:
        return
    phys = result.values.get(PHYS)
    ele = result.values.get(ELE)
    if phys:
        result.values["pdps"] = round(phys * aps, 1)
    if ele:
        result.values["edps"] = round(ele * aps, 1)
    total = (phys or 0) + (ele or 0)
    if total:
        result.values["dps"] = round(total * aps, 1)


def project_from_filters(item: ParsedItem, mod_filters) -> Projection:
    """Обёртка под ModFilter: берёт нижнюю границу как желаемое значение.

    Мод, у которого граница не задана, считается оставшимся как есть.
    Мод, добавленный из пула, на предмете значения не имеет — там
    желаемое и есть весь вклад.
    """
    wanted: list[tuple[str, list[float], float | None]] = []
    for mod in mod_filters:
        if not getattr(mod, "enabled", False) or not getattr(mod, "matched", False):
            continue
        source = getattr(mod, "source_value", None)
        target = getattr(mod, "min_value", None)
        values = [source] if source is not None else []
        if target is None and source is None:
            continue
        wanted.append((mod.text, values, target))
    return project(item, wanted)
