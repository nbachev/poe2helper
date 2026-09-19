"""Сборка JSON-запроса для ``/api/trade2/search``."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..parser.item import ItemMod, ParsedItem
from ..parser.stats_db import StatEntry, StatsDB

RARITY_OPTION = {
    "normal": "normal",
    "magic": "magic",
    "rare": "rare",
    "unique": "unique",
}


@dataclass
class ModFilter:
    """Строка мода в оверлее: включён ли он в поиск и с какими границами."""

    stat_id: str
    text: str  # что показывать пользователю
    kind: str = "explicit"
    enabled: bool = False
    min_value: float | None = None
    max_value: float | None = None
    option_id: int | str | None = None
    weight: float = 1.0
    source_value: float | None = None  # фактический ролл на предмете
    matched: bool = True
    from_pool: bool = False  # добавлен вручную из пула модов
    affix: str = ""  # «Prefix "Rotund" (Tier: 3)» из расширенного описания
    tier: int | None = None

    def to_filter(self) -> dict[str, Any]:
        out: dict[str, Any] = {"id": self.stat_id}
        value: dict[str, Any] = {}
        if self.option_id is not None:
            value["option"] = self.option_id
        if self.min_value is not None:
            value["min"] = _round(self.min_value)
        if self.max_value is not None:
            value["max"] = _round(self.max_value)
        if value:
            out["value"] = value
        return out


# Параметры экипировки в терминах trade2 API.
# Порядок задаёт порядок строк в оверлее.
EQUIPMENT_FIELDS: list[tuple[str, str, int]] = [
    # ключ API, подпись, знаков после запятой
    ("dps", "ДПС", 1),
    ("pdps", "Физ. ДПС", 1),
    ("edps", "Эл. ДПС", 1),
    ("crit", "Крит, %", 2),
    ("aps", "Атак/сек", 2),
    ("reload_time", "Перезарядка", 2),
    ("ar", "Броня", 0),
    ("ev", "Уклонение", 0),
    ("es", "Энергощит", 0),
    ("block", "Блок, %", 0),
    ("spirit", "Дух", 0),
]

# Для перезарядки арбалета меньше — лучше, поэтому подставляем верхнюю границу.
LOWER_IS_BETTER = {"reload_time"}


@dataclass
class EquipFilter:
    """Строка фильтра по характеристике вещи (броня, ДПС и т. д.)."""

    key: str
    label: str
    value: float | None = None
    decimals: int = 0
    enabled: bool = False
    min_value: float | None = None
    max_value: float | None = None

    def bounds(self) -> dict[str, float | int]:
        out: dict[str, float | int] = {}
        if self.min_value is not None:
            out["min"] = _round(self.min_value)
        if self.max_value is not None:
            out["max"] = _round(self.max_value)
        return out


def item_equipment_values(item: ParsedItem) -> dict[str, float]:
    """Характеристики предмета, разложенные по ключам trade2 API."""
    eq = item.equip
    raw = {
        "dps": eq.dps,
        "pdps": eq.pdps,
        "edps": eq.edps,
        "crit": eq.crit,
        "aps": eq.aps,
        "reload_time": eq.reload_time,
        "ar": eq.armour,
        "ev": eq.evasion,
        "es": eq.energy_shield,
        "block": eq.block,
        "spirit": eq.spirit,
    }
    return {k: v for k, v in raw.items() if v}


def build_equipment_filters(
    item: ParsedItem, default_enabled: list[str] | None = None
) -> list[EquipFilter]:
    """Строки для блока «Параметры вещи» в оверлее.

    Показываем только то, что у предмета реально есть. Нижняя граница
    подставляется равной текущему значению — обычный сценарий «найди
    лук не хуже моего».
    """
    values = item_equipment_values(item)
    enabled_keys = {k.lower() for k in (default_enabled or [])}
    out: list[EquipFilter] = []
    for key, label, decimals in EQUIPMENT_FIELDS:
        value = values.get(key)
        if value is None:
            continue
        mf = EquipFilter(
            key=key,
            label=label,
            value=value,
            decimals=decimals,
            enabled=key in enabled_keys,
        )
        if key in LOWER_IS_BETTER:
            mf.max_value = _round(value)
        else:
            mf.min_value = _round(value)
        out.append(mf)
    return out


@dataclass
class QueryOptions:
    status: str = "online"
    rarity: str | None = None  # "unique" / "nonunique" / None
    use_type: bool = True
    use_name: bool = True
    category: str | None = None
    item_level_min: int | None = None
    quality_min: int | None = None
    sockets_min: int | None = None
    corrupted: bool | None = None
    gem_level_min: int | None = None
    identified: bool | None = None
    price_max_chaos: float | None = None
    equipment: list[EquipFilter] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)


def _round(value: float) -> float | int:
    rounded = round(value, 2)
    if abs(rounded - round(rounded)) < 1e-9:
        return int(round(rounded))
    return rounded


def build_mod_filters(
    item: ParsedItem,
    db: StatsDB,
    default_kinds: list[str],
    roll_tolerance: float = 0.1,
    min_only: bool = True,
) -> list[ModFilter]:
    """Превращает моды предмета в строки для оверлея."""
    out: list[ModFilter] = []
    for mod in item.mods:
        entry, multiplier, option_id = db.match(mod.text, mod.kind)
        value = mod.value
        if entry is None:
            out.append(
                ModFilter(
                    stat_id="",
                    text=mod.text,
                    kind=mod.kind,
                    enabled=False,
                    matched=False,
                    source_value=value,
                    affix=mod.affix,
                    tier=mod.tier,
                )
            )
            continue

        if value is not None and multiplier is not None:
            value = value * multiplier

        mf = ModFilter(
            stat_id=entry.id,
            text=_display_text(entry, mod, option_id),
            kind=entry.kind,
            enabled=mod.kind in default_kinds,
            option_id=option_id,
            source_value=value,
            affix=mod.affix,
            tier=mod.tier,
        )
        if option_id is None and value is not None:
            lo, hi = suggest_bounds(value, roll_tolerance, min_only)
            mf.min_value, mf.max_value = lo, hi
        out.append(mf)
    return out


def _display_text(entry: StatEntry, mod: ItemMod, option_id: int | str | None) -> str:
    if option_id is not None:
        for oid, otext in entry.options:
            if oid == option_id:
                return entry.text.replace("#", otext)
    return mod.text


def suggest_bounds(
    value: float, tolerance: float = 0.1, min_only: bool = True
) -> tuple[float | None, float | None]:
    """Границы «примерно такой же ролл»."""
    if value == 0:
        return (None, None)
    if value < 0:
        hi = _round(value * (1 - tolerance))
        lo = None if min_only else _round(value * (1 + tolerance))
        return (lo, hi)
    lo = _round(value * (1 - tolerance))
    hi = None if min_only else _round(value * (1 + tolerance))
    return (lo, hi)


def build_query(
    item: ParsedItem | None,
    mod_filters: list[ModFilter],
    options: QueryOptions,
) -> dict[str, Any]:
    stats_filters = [mf.to_filter() for mf in mod_filters if mf.enabled and mf.stat_id]

    query: dict[str, Any] = {
        "status": {"option": options.status or "online"},
        "stats": [{"type": "and", "filters": stats_filters}],
    }

    if item is not None:
        if options.use_name and item.is_unique and item.name:
            query["name"] = item.name
        if options.use_type and item.base_type and item.base_type_certain:
            query["type"] = item.base_type

    filters: dict[str, Any] = {}

    type_filters: dict[str, Any] = {}
    if options.category:
        type_filters["category"] = {"option": options.category}
    if options.rarity:
        type_filters["rarity"] = {"option": options.rarity}
    if options.item_level_min is not None:
        type_filters["ilvl"] = {"min": options.item_level_min}
    if options.quality_min is not None:
        type_filters["quality"] = {"min": options.quality_min}
    if type_filters:
        filters["type_filters"] = {"filters": type_filters}

    misc_filters: dict[str, Any] = {}
    if options.corrupted is not None:
        misc_filters["corrupted"] = {"option": "true" if options.corrupted else "false"}
    if options.gem_level_min is not None:
        misc_filters["gem_level"] = {"min": options.gem_level_min}
    if options.identified is not None:
        misc_filters["identified"] = {"option": "true" if options.identified else "false"}
    if misc_filters:
        filters["misc_filters"] = {"filters": misc_filters}

    equipment_filters: dict[str, Any] = {}
    if options.sockets_min is not None:
        equipment_filters["rune_sockets"] = {"min": options.sockets_min}
    for equip in options.equipment:
        if not equip.enabled:
            continue
        bounds = equip.bounds()
        if bounds:
            equipment_filters[equip.key] = bounds
    if equipment_filters:
        filters["equipment_filters"] = {"filters": equipment_filters}

    trade_filters: dict[str, Any] = {}
    if options.price_max_chaos is not None:
        trade_filters["price"] = {"max": options.price_max_chaos, "option": "chaos"}
    if trade_filters:
        filters["trade_filters"] = {"filters": trade_filters}

    for key, value in options.extra.items():
        filters[key] = value

    if filters:
        query["filters"] = filters

    return {"query": query, "sort": {"price": "asc"}}


def default_options_for(item: ParsedItem, cfg_search: dict) -> QueryOptions:
    """Разумные настройки поиска под конкретный предмет."""
    opts = QueryOptions(status=cfg_search.get("status", "online"))
    opts.category = item.category

    if item.is_unique:
        opts.rarity = "unique"
        opts.use_name = True
    elif item.is_rare or item.is_magic:
        opts.rarity = "nonunique" if cfg_search.get("include_rarity", True) else None
    elif item.is_currency_like:
        opts.rarity = None
        opts.category = None  # для валюты хватает точного type

    if cfg_search.get("include_item_level", False) and item.item_level:
        opts.item_level_min = item.item_level
    if cfg_search.get("include_quality", False) and item.quality:
        opts.quality_min = item.quality
    if cfg_search.get("include_corrupted", True) and item.rarity.lower() in {
        "rare",
        "unique",
        "magic",
        "normal",
    }:
        opts.corrupted = item.corrupted
    if cfg_search.get("include_sockets", False) and item.sockets:
        opts.sockets_min = item.sockets
    if item.is_gem and item.gem_level:
        opts.gem_level_min = item.gem_level
    if not item.identified:
        opts.identified = False

    opts.equipment = build_equipment_filters(
        item, cfg_search.get("default_equipment_filters", [])
    )

    return opts
