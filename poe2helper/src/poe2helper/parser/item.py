"""Парсер текста предмета Path of Exile 2 из буфера обмена (Ctrl+C в игре).

Формат: секции, разделённые строками из дефисов (``--------``).
Первая секция содержит ``Item Class:``, ``Rarity:`` и имя/базу.
Дальше идут свойства (``Ключ: значение``), требования, сокеты, уровень предмета,
затем секции с модификаторами. Модификаторы помечены суффиксами
``(implicit)``, ``(rune)``, ``(enchant)``, ``(fractured)``, ``(desecrated)``,
``(crafted)``; обычные аффиксы идут без суффикса.

Модуль не зависит от Qt и от сети — его можно гонять в тестах на любой ОС.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

SEPARATOR_RE = re.compile(r"^-{3,}$")
NUMBER_RE = re.compile(r"[+-]?\d+(?:\.\d+)?")
MOD_TAG_RE = re.compile(r"\s*\((implicit|explicit|crafted|enchant|rune|fractured|desecrated|scourge|veiled|sanctum)\)\s*$", re.I)
AUGMENTED_RE = re.compile(r"\s*\((?:augmented|unmet)\)\s*$", re.I)

# Строки-флаги, встречающиеся отдельной секцией
FLAG_LINES = {
    "corrupted": "corrupted",
    "mirrored": "mirrored",
    "unidentified": "unidentified",
    "split": "split",
    "unmodifiable": "unmodifiable",
    "desecrated": "has_desecrated",
    "can have a second enchantment modifier": None,
}

# Ключи свойств, которые нас интересуют
KNOWN_PROPERTY_KEYS = {
    "item class",
    "rarity",
    "quality",
    "armour",
    "evasion rating",
    "energy shield",
    "block chance",
    "block",
    "spirit",
    "physical damage",
    "elemental damage",
    "chaos damage",
    "critical hit chance",
    "attacks per second",
    "reload time",
    "requirements",
    "level",
    "str",
    "dex",
    "int",
    "strength",
    "dexterity",
    "intelligence",
    "sockets",
    "item level",
    "stack size",
    "waystone tier",
    "waystone drop chance",
    "item quantity",
    "item rarity",
    "monster pack size",
    "quality (attack modifiers)",
    "quality (caster modifiers)",
    "quality (defence modifiers)",
    "quality (life and mana modifiers)",
    "quality (resistance modifiers)",
    "limited to",
    "radius",
    "charm slots",
    "grants skill",
    "note",
    "area level",
    "map tier",
    "charges",
    "uses",
    "uses remaining",
    "duration",
    "recovery",
    "mana",
    "life",
}

# Классы предметов -> категория для type_filters.category на trade2
CATEGORY_BY_CLASS: dict[str, str] = {
    "wands": "weapon.wand",
    "staves": "weapon.staff",
    "quarterstaves": "weapon.warstaff",
    "warstaves": "weapon.warstaff",
    "bows": "weapon.bow",
    "crossbows": "weapon.crossbow",
    "sceptres": "weapon.sceptre",
    "spears": "weapon.spear",
    "flails": "weapon.flail",
    "one hand maces": "weapon.onemace",
    "two hand maces": "weapon.twomace",
    "one hand swords": "weapon.onesword",
    "two hand swords": "weapon.twosword",
    "one hand axes": "weapon.oneaxe",
    "two hand axes": "weapon.twoaxe",
    "claws": "weapon.claw",
    "daggers": "weapon.dagger",
    "helmets": "armour.helmet",
    "body armours": "armour.chest",
    "gloves": "armour.gloves",
    "boots": "armour.boots",
    "shields": "armour.shield",
    "foci": "armour.focus",
    "bucklers": "armour.buckler",
    "quivers": "armour.quiver",
    "amulets": "accessory.amulet",
    "rings": "accessory.ring",
    "belts": "accessory.belt",
    "jewels": "jewel",
    "life flasks": "flask.life",
    "mana flasks": "flask.mana",
    "charms": "flask.charm",
    "waystones": "map.waystone",
    "relics": "map.relic",
    "tablet": "map.tablet",
    "trial coins": "map.barya",
    "expedition logbooks": "map.logbook",
    "skill gems": "gem.activegem",
    "support gems": "gem.supportgem",
    "meta gems": "gem.metagem",
    "stackable currency": "currency",
    "currency": "currency",
    "omen": "currency.omen",
    "socketable": "currency.socketable",
    "soul cores": "currency.socketable",
    "runes": "currency.socketable",
}


@dataclass
class ItemMod:
    """Один модификатор предмета."""

    text: str  # текст без суффикса-тега
    kind: str  # explicit / implicit / rune / enchant / fractured / desecrated / crafted
    values: list[float] = field(default_factory=list)
    raw: str = ""

    @property
    def value(self) -> float | None:
        """Значение для фильтра: среднее для диапазонов «от X до Y»."""
        if not self.values:
            return None
        if len(self.values) >= 2 and re.search(r"#\s+to\s+#", self.pattern):
            return (self.values[0] + self.values[1]) / 2
        return self.values[0]

    @property
    def pattern(self) -> str:
        """Текст с числами, заменёнными на ``#``."""
        return NUMBER_RE.sub("#", self.text)


@dataclass
class EquipStats:
    """Числовые характеристики вещи: защита и урон.

    Из них считается ДПС — торговая площадка фильтрует именно по нему,
    а не по «уронов столько-то за удар».
    """

    armour: float | None = None
    evasion: float | None = None
    energy_shield: float | None = None
    block: float | None = None
    spirit: float | None = None
    phys_avg: float | None = None
    ele_avg: float | None = None
    chaos_avg: float | None = None
    aps: float | None = None
    crit: float | None = None
    reload_time: float | None = None

    def _dps(self, damage: float | None) -> float | None:
        if not damage or not self.aps:
            return None
        return round(damage * self.aps, 1)

    @property
    def pdps(self) -> float | None:
        return self._dps(self.phys_avg)

    @property
    def edps(self) -> float | None:
        return self._dps(self.ele_avg)

    @property
    def cdps(self) -> float | None:
        return self._dps(self.chaos_avg)

    @property
    def dps(self) -> float | None:
        total = (self.phys_avg or 0) + (self.ele_avg or 0) + (self.chaos_avg or 0)
        return self._dps(total)

    @property
    def has_defence(self) -> bool:
        return any(
            v is not None
            for v in (self.armour, self.evasion, self.energy_shield, self.block, self.spirit)
        )

    @property
    def has_damage(self) -> bool:
        return self.dps is not None


@dataclass
class ParsedItem:
    raw: str = ""
    item_class: str = ""
    rarity: str = ""
    name: str = ""
    base_type: str = ""
    base_type_certain: bool = True
    item_level: int | None = None
    quality: int | None = None
    sockets: int | None = None
    stack_size: int | None = None
    gem_level: int | None = None
    waystone_tier: int | None = None
    area_level: int | None = None
    corrupted: bool = False
    mirrored: bool = False
    identified: bool = True
    unmodifiable: bool = False
    mods: list[ItemMod] = field(default_factory=list)
    properties: dict[str, str] = field(default_factory=dict)
    equip: EquipStats = field(default_factory=EquipStats)
    note: str = ""

    @property
    def is_unique(self) -> bool:
        return self.rarity.lower() == "unique"

    @property
    def is_rare(self) -> bool:
        return self.rarity.lower() == "rare"

    @property
    def is_magic(self) -> bool:
        return self.rarity.lower() == "magic"

    @property
    def is_currency_like(self) -> bool:
        return self.rarity.lower() in {"currency", "divination card"}

    @property
    def is_gem(self) -> bool:
        return "gem" in self.item_class.lower()

    @property
    def category(self) -> str | None:
        return CATEGORY_BY_CLASS.get(self.item_class.strip().lower())

    @property
    def is_weapon(self) -> bool:
        return (self.category or "").startswith("weapon.")

    @property
    def is_armour(self) -> bool:
        return (self.category or "").startswith("armour.")

    @property
    def display_name(self) -> str:
        if self.name and self.base_type and self.name != self.base_type:
            return f"{self.name} — {self.base_type}"
        return self.name or self.base_type or "?"


def _split_sections(text: str) -> list[list[str]]:
    sections: list[list[str]] = [[]]
    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if SEPARATOR_RE.match(line.strip()):
            sections.append([])
        else:
            sections[-1].append(line.rstrip())
    return [[ln for ln in sec if ln.strip()] for sec in sections if any(l.strip() for l in sec)]


def _split_key_value(line: str) -> tuple[str, str] | None:
    if ":" not in line:
        return None
    key, _, value = line.partition(":")
    key = key.strip()
    if not key or len(key) > 40:
        return None
    return key, value.strip()


def _to_int(value: str) -> int | None:
    m = NUMBER_RE.search(value)
    if not m:
        return None
    try:
        return int(float(m.group()))
    except ValueError:
        return None


def _to_float(value: str) -> float | None:
    m = re.search(r"\d+(?:\.\d+)?", value)
    if not m:
        return None
    try:
        return float(m.group())
    except ValueError:
        return None


RANGE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)")


def _avg_damage(value: str) -> float | None:
    """``"12-24 (augmented), 5-9"`` -> 18 + 7 = 25.

    Элементальный урон приходит несколькими диапазонами через запятую —
    суммируем средние по каждому, как это делает сама торговая площадка.
    """
    ranges = RANGE_RE.findall(value)
    if not ranges:
        return None
    total = 0.0
    for low, high in ranges:
        total += (float(low) + float(high)) / 2
    return round(total, 2)


def looks_like_poe_item(text: str) -> bool:
    """Быстрая проверка: похоже ли содержимое буфера на предмет из PoE."""
    if not text or len(text) < 12:
        return False
    head = text.lstrip()[:400].lower()
    return head.startswith("item class:") or "rarity:" in head


def parse_item(text: str) -> ParsedItem | None:
    """Разбирает текст предмета. Возвращает ``None``, если это не предмет."""
    if not looks_like_poe_item(text):
        return None

    item = ParsedItem(raw=text)
    sections = _split_sections(text)
    if not sections:
        return None

    _parse_header(item, sections[0])

    for section in sections[1:]:
        _parse_section(item, section)

    _post_process(item)
    return item


def _parse_header(item: ParsedItem, section: list[str]) -> None:
    rest: list[str] = []
    for line in section:
        kv = _split_key_value(line)
        if kv and kv[0].lower() == "item class":
            item.item_class = kv[1]
        elif kv and kv[0].lower() == "rarity":
            item.rarity = kv[1]
        else:
            rest.append(line.strip())

    if len(rest) >= 2:
        item.name = rest[0]
        item.base_type = rest[1]
    elif len(rest) == 1:
        item.name = rest[0]
        item.base_type = rest[0]

    # Для магических предметов имя содержит префикс/суффикс — база неизвестна.
    if item.is_magic:
        item.base_type_certain = False
        item.base_type = _strip_magic_affixes(item.name)

    # "Waystone (Tier 15)" -> база "Waystone"
    m = re.match(r"^(.*?)\s*\(Tier\s+(\d+)\)\s*$", item.base_type)
    if m:
        item.base_type = m.group(1).strip()
        item.waystone_tier = int(m.group(2))

    # "Superior ..." — префикс качества, в trade он не участвует
    for prefix in ("Superior ", "Advanced ", "Expert "):
        if item.base_type.startswith(prefix) and item.rarity.lower() not in {"unique"}:
            # Advanced/Expert — это реальные базы в PoE2, Superior — нет
            if prefix == "Superior ":
                item.base_type = item.base_type[len(prefix):]


def _strip_magic_affixes(name: str) -> str:
    """Грубо срезает суффикс «of ...» у магического предмета."""
    idx = name.find(" of ")
    if idx > 0:
        return name[:idx].strip()
    return name.strip()


def _parse_section(item: ParsedItem, section: list[str]) -> None:
    # Секция-флаг из одной строки
    if len(section) == 1:
        low = section[0].strip().lower()
        if low in FLAG_LINES:
            _apply_flag(item, low)
            return

    for line in section:
        stripped = line.strip()
        low = stripped.lower()

        if low in FLAG_LINES:
            _apply_flag(item, low)
            continue

        kv = _split_key_value(stripped)
        if kv and kv[0].lower() in KNOWN_PROPERTY_KEYS:
            _apply_property(item, kv[0], kv[1])
            continue

        # Всё остальное считаем модификатором
        mod = _make_mod(stripped)
        if mod is not None:
            item.mods.append(mod)


def _apply_flag(item: ParsedItem, low: str) -> None:
    attr = FLAG_LINES.get(low)
    if attr == "corrupted":
        item.corrupted = True
    elif attr == "mirrored":
        item.mirrored = True
    elif attr == "unidentified":
        item.identified = False
    elif attr == "unmodifiable":
        item.unmodifiable = True


def _apply_property(item: ParsedItem, key: str, value: str) -> None:
    low = key.lower()
    clean = AUGMENTED_RE.sub("", value).strip()
    item.properties[low] = clean

    # Урон разбираем из исходной строки: «(augmented)» может стоять после
    # каждого диапазона, а не только в конце.
    if low == "physical damage":
        item.equip.phys_avg = _avg_damage(value)
        return
    if low == "elemental damage":
        item.equip.ele_avg = _avg_damage(value)
        return
    if low == "chaos damage":
        item.equip.chaos_avg = _avg_damage(value)
        return
    if low == "attacks per second":
        item.equip.aps = _to_float(clean)
        return
    if low == "critical hit chance":
        item.equip.crit = _to_float(clean)
        return
    if low == "reload time":
        item.equip.reload_time = _to_float(clean)
        return
    if low == "armour":
        item.equip.armour = _to_float(clean)
        return
    if low == "evasion rating":
        item.equip.evasion = _to_float(clean)
        return
    if low == "energy shield":
        item.equip.energy_shield = _to_float(clean)
        return
    if low in ("block chance", "block"):
        item.equip.block = _to_float(clean)
        return
    if low == "spirit":
        item.equip.spirit = _to_float(clean)
        return

    if low == "quality":
        item.quality = _to_int(clean)
    elif low == "item level":
        item.item_level = _to_int(clean)
    elif low == "area level":
        item.area_level = _to_int(clean)
    elif low == "waystone tier":
        item.waystone_tier = _to_int(clean)
    elif low == "stack size":
        # "3/10"
        item.stack_size = _to_int(clean.split("/")[0])
    elif low == "sockets":
        item.sockets = len([c for c in clean.split() if c.strip()])
    elif low == "level":
        # Уровень камня, либо требование по уровню — различаем по классу
        if item.is_gem or item.rarity.lower() == "currency":
            item.gem_level = _to_int(clean)
    elif low == "note":
        item.note = clean


def _make_mod(line: str) -> ItemMod | None:
    raw = line
    kind = "explicit"
    m = MOD_TAG_RE.search(line)
    if m:
        kind = m.group(1).lower()
        line = MOD_TAG_RE.sub("", line).strip()
    line = line.strip()
    if not line:
        return None
    # Строки-подсказки по использованию валюты в поиск не идут
    low = line.lower()
    if low.startswith("right click") or low.startswith("shift click") or low.startswith("can be used in"):
        return None
    values = [float(v) for v in NUMBER_RE.findall(line)]
    return ItemMod(text=line, kind=kind, values=values, raw=raw)


def _post_process(item: ParsedItem) -> None:
    # Неопознанный предмет: у него нет аффиксов в буфере
    if not item.identified:
        item.mods = [m for m in item.mods if m.kind != "explicit"]

    # Уникальные: последний блок — художественный текст (flavour).
    # Эвристика: строки без цифр и без ключевых слов модов, идущие подряд в конце.
    if item.is_unique and item.mods:
        while item.mods:
            last = item.mods[-1]
            if last.values:
                break
            words = last.text.lower()
            if any(k in words for k in ("increase", "reduce", "more ", "less ", "to ", "adds", "grants", "gain")):
                break
            item.mods.pop()
        # flavour как правило длиннее и с заглавной буквы без цифр — оставляем как есть
