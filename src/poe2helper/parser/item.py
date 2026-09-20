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

# --- расширенные описания модов (Advanced Mod Descriptions) ---
# Игра дописывает к каждому аффиксу строку-аннотацию и подмешивает в значение
# возможный разброс ролла:
#     { Prefix Modifier "Rotund" (Tier: 3) — Life }
#     +97(85-99) to maximum Life
# Аннотацию забираем как справку о тире, разброс из значения вырезаем —
# иначе текст мода не совпадёт ни с чем в пуле торговой площадки.
ANNOTATION_RE = re.compile(r"^\{(.+)\}$")
ROLL_RANGE_RE = re.compile(r"(?<=\d)\(\s*\d+(?:\.\d+)?(?:\s*-\s*\d+(?:\.\d+)?)?\s*\)")
ROLL_RANGE_CAPTURE_RE = re.compile(
    r"(?<=\d)\(\s*(\d+(?:\.\d+)?)(?:\s*-\s*(\d+(?:\.\d+)?))?\s*\)"
)
ANNOTATION_KIND_RE = re.compile(
    r"\b(prefix|suffix|implicit|explicit|rune|enchant|crafted|desecrated|fractured|scourge|veiled|sanctum)\b",
    re.I,
)
ANNOTATION_NAME_RE = re.compile(r'"([^"]+)"')
ANNOTATION_TIER_RE = re.compile(r"\(\s*Tier:\s*(\d+)\s*\)", re.I)

# Строки, которые игра пишет в шапке вместо имени предмета.
# Имя и база в этом случае уезжают в следующую секцию.
HEADER_NOISE_PREFIXES = (
    "you cannot use this item",
    "this item is not usable",
    "crafted item",  # так помечает предметы Path of Building
)

# «Adds 73 to 110 Cold Damage» — добавленный стихийный урон.
# Нужен, когда свойства «Elemental Damage:» в тексте нет (например,
# предмет скопирован из Path of Building), а урон посчитать надо.
ADDS_ELEMENTAL_RE = re.compile(
    r"^adds\s+[\d.]+\s+to\s+[\d.]+\s+(fire|cold|lightning)\s+damage", re.I
)
ADDS_CHAOS_RE = re.compile(r"^adds\s+[\d.]+\s+to\s+[\d.]+\s+chaos\s+damage", re.I)

ANNOTATION_KIND_MAP = {
    "prefix": "explicit",
    "suffix": "explicit",
    "explicit": "explicit",
    "implicit": "implicit",
    "rune": "rune",
    "enchant": "enchant",
    "crafted": "crafted",
    "desecrated": "desecrated",
    "fractured": "fractured",
    "scourge": "scourge",
    "veiled": "veiled",
    "sanctum": "sanctum",
}


def _fmt_num(value: float) -> str:
    if abs(value - round(value)) < 1e-9:
        return str(int(round(value)))
    return f"{value:g}"


def strip_roll_ranges(text: str) -> str:
    """``+97(85-99) to maximum Life`` -> ``+97 to maximum Life``."""
    return ROLL_RANGE_RE.sub("", text)


def extract_roll_ranges(text: str) -> list[tuple[float, float]]:
    """``+97(85-99) to maximum Life`` -> ``[(85.0, 99.0)]``.

    Это границы ролла для тира, в котором выпал мод, — игра сообщает их
    только при включённых расширенных описаниях. Для мода с одним
    возможным значением обе границы совпадают.
    """
    out: list[tuple[float, float]] = []
    for low, high in ROLL_RANGE_CAPTURE_RE.findall(text):
        lo = float(low)
        hi = float(high) if high else lo
        out.append((lo, hi))
    return out
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
    "critical strike chance",  # так называется в Path of Building
    "attacks per second",
    "reload time",
    "requirements",
    "requires",
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

    text: str  # текст без суффикса-тега и без разброса ролла
    kind: str  # explicit / implicit / rune / enchant / fractured / desecrated / crafted
    values: list[float] = field(default_factory=list)
    raw: str = ""
    affix: str = ""  # «Prefix "Rotund" (Tier: 3)» из расширенного описания
    tier: int | None = None
    # Один аффикс может давать несколько строк (гибридные моды вроде
    # «40% increased Armour» + «+123 to Stun Threshold»). Строки одного
    # аффикса делят group_id, и оверлей показывает их одной строкой.
    group_id: int = 0
    # Границы ролла для выпавшего тира, если игра их сообщила
    ranges: list[tuple[float, float]] = field(default_factory=list)

    @property
    def roll_percent(self) -> float | None:
        """Насколько удачен ролл внутри своего тира, 0..100."""
        if not self.ranges or not self.values:
            return None
        low, high = self.ranges[0]
        if high <= low:
            return 100.0
        value = self.values[0]
        return max(0.0, min(100.0, (value - low) / (high - low) * 100))

    @property
    def range_text(self) -> str:
        if not self.ranges:
            return ""
        low, high = self.ranges[0]
        if high <= low:
            return _fmt_num(low)
        return f"{_fmt_num(low)}–{_fmt_num(high)}"

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

    rest = _parse_header(item, sections)

    state = {"group": 0}
    for section in rest:
        _parse_section(item, section, state)

    _post_process(item)
    return item


def _name_lines(section: list[str]) -> list[str]:
    """Строки секции, которые могут быть именем/базой предмета."""
    out: list[str] = []
    for line in section:
        stripped = line.strip()
        low = stripped.lower()
        if low.startswith(HEADER_NOISE_PREFIXES):
            continue
        if ANNOTATION_RE.match(stripped):
            continue
        kv = _split_key_value(stripped)
        if kv and kv[0].lower() in KNOWN_PROPERTY_KEYS:
            continue
        if low in FLAG_LINES:
            continue
        out.append(stripped)
    return out


def _parse_header(item: ParsedItem, sections: list[list[str]]) -> list[list[str]]:
    """Разбирает шапку и возвращает оставшиеся секции.

    Обычно имя и база лежат в первой секции вместе с Item Class и Rarity.
    Но если игра вставила туда служебную строку («You cannot use this
    item…»), имя с базой уезжают в следующую секцию — тогда забираем её,
    иначе именем предмета станет предупреждение, а настоящее имя попадёт
    в список модов.
    """
    head = sections[0]
    rest_sections = sections[1:]

    rest: list[str] = []
    for line in head:
        kv = _split_key_value(line)
        if kv and kv[0].lower() == "item class":
            item.item_class = kv[1]
        elif kv and kv[0].lower() == "rarity":
            item.rarity = kv[1]
        elif not line.strip().lower().startswith(HEADER_NOISE_PREFIXES):
            rest.append(line.strip())

    if not rest and rest_sections:
        candidate = _name_lines(rest_sections[0])
        if candidate:
            rest = candidate
            rest_sections = rest_sections[1:]

    _apply_name(item, rest)
    return rest_sections


def _apply_name(item: ParsedItem, rest: list[str]) -> None:
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


def _parse_annotation(inner: str) -> dict:
    """``Prefix Modifier "Rotund" (Tier: 3) — Life`` -> сведения об аффиксе."""
    info: dict = {}
    m = ANNOTATION_KIND_RE.search(inner)
    if m:
        word = m.group(1).lower()
        info["kind"] = ANNOTATION_KIND_MAP.get(word, "explicit")
        info["origin"] = word
    m = ANNOTATION_NAME_RE.search(inner)
    if m:
        info["name"] = m.group(1)
    m = ANNOTATION_TIER_RE.search(inner)
    if m:
        info["tier"] = int(m.group(1))
    return info


def _parse_section(item: ParsedItem, section: list[str], state: dict) -> None:
    # Секция-флаг из одной строки
    if len(section) == 1:
        low = section[0].strip().lower()
        if low in FLAG_LINES:
            _apply_flag(item, low)
            return

    pending: dict = {}
    under_annotation = False

    for line in section:
        stripped = line.strip()
        low = stripped.lower()

        annotation = ANNOTATION_RE.match(stripped)
        if annotation:
            # Справочная строка расширенного описания. Всё, что идёт после
            # неё до следующей такой строки, — один аффикс: у гибридных
            # модов это две строки и более.
            pending = _parse_annotation(annotation.group(1))
            under_annotation = True
            state["group"] += 1
            continue

        if low in FLAG_LINES:
            _apply_flag(item, low)
            pending, under_annotation = {}, False
            continue

        kv = _split_key_value(stripped)
        if kv and kv[0].lower() in KNOWN_PROPERTY_KEYS:
            _apply_property(item, kv[0], kv[1])
            pending, under_annotation = {}, False
            continue

        # Всё остальное считаем модификатором
        mod = _make_mod(stripped, pending)
        if mod is None:
            continue
        if not under_annotation:
            # Без аннотации каждая строка сама по себе
            state["group"] += 1
        mod.group_id = state["group"]
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
    # В расширенном описании числа тоже приходят с разбросом:
    # «Armour: 368(300-400)», «Physical Damage: 44(40-48)-82(75-90)».
    value = strip_roll_ranges(value)
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
    if low in ("critical hit chance", "critical strike chance"):
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


def _make_mod(line: str, annotation: dict | None = None) -> ItemMod | None:
    raw = line
    annotation = annotation or {}
    kind = annotation.get("kind", "explicit")

    m = MOD_TAG_RE.search(line)
    if m:
        # Явный суффикс вида «(implicit)» важнее аннотации
        kind = m.group(1).lower()
        line = MOD_TAG_RE.sub("", line).strip()

    # Границы ролла забираем ДО того, как вырезать их из текста,
    # иначе извлекать будет уже нечего.
    ranges = extract_roll_ranges(line)
    line = strip_roll_ranges(line).strip()
    if not line:
        return None

    # Строки-подсказки по использованию валюты в поиск не идут
    low = line.lower()
    if low.startswith("right click") or low.startswith("shift click") or low.startswith("can be used in"):
        return None

    values = [float(v) for v in NUMBER_RE.findall(line)]

    affix = ""
    origin = annotation.get("origin", "")
    if origin:
        affix = origin.capitalize()
        if annotation.get("name"):
            affix += f' "{annotation["name"]}"'
        if annotation.get("tier") is not None:
            affix += f" (Tier: {annotation['tier']})"

    return ItemMod(
        text=line,
        kind=kind,
        values=values,
        raw=raw,
        affix=affix,
        tier=annotation.get("tier"),
        ranges=ranges,
    )


def _derive_added_damage(item: ParsedItem) -> None:
    """Восстанавливает стихийный и хаос-урон из модов, если свойства нет.

    Игра показывает отдельной строкой «Elemental Damage: 73-110», но в
    экспорте Path of Building такой строки может не быть — там добавленный
    урон виден только модом. Считаем его сами, и только когда свойство
    отсутствует: иначе вышло бы двойное начисление.
    """
    for pattern, attribute in ((ADDS_ELEMENTAL_RE, "ele_avg"), (ADDS_CHAOS_RE, "chaos_avg")):
        if getattr(item.equip, attribute) is not None:
            continue
        total = 0.0
        for mod in item.mods:
            if not pattern.match(mod.text):
                continue
            if len(mod.values) >= 2:
                total += (mod.values[0] + mod.values[1]) / 2
        if total:
            setattr(item.equip, attribute, round(total, 2))


def _post_process(item: ParsedItem) -> None:
    # Неопознанный предмет: у него нет аффиксов в буфере
    if not item.identified:
        item.mods = [m for m in item.mods if m.kind != "explicit"]

    _derive_added_damage(item)

    # Раньше здесь отбрасывался «художественный текст» уникальных предметов
    # по эвристике «нет цифр и нет ключевых слов». Она била и по настоящим
    # модам вроде «Cannot be Frozen», поэтому убрана: лучше показать лишнюю
    # строку, которую видно как неопознанную и можно снять крестиком,
    # чем молча потерять мод.
    return
