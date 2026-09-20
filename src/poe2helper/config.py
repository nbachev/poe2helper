"""Настройки приложения: загрузка/сохранение JSON + значения по умолчанию."""

from __future__ import annotations

import copy
import json
import logging
from typing import Any

from .paths import config_path

log = logging.getLogger(__name__)

# Пороги цен (в экзальтах) для перетиринга групп фильтра.
# Список читается как: t1 >= первое значение, t2 >= второе, ...
# Лишние пороги отбрасываются, недостающие достраиваются делением на 3.
DEFAULT_TIER_THRESHOLDS: dict[str, list[float]] = {
    "currency": [40, 10, 3, 1, 0.3, 0.1, 0.03],
    "fragments": [40, 10, 3, 1, 0.3],
    "essences": [15, 4, 1, 0.3, 0.1],
    "runes": [10, 3, 1, 0.3, 0.1],
    "soulcores": [10, 3, 1, 0.3, 0.1],
    "omen": [40, 10, 3, 1, 0.3],
    "expedition": [20, 5, 1, 0.3, 0.1],
    "ritual": [20, 5, 1, 0.3, 0.1],
    "breach": [20, 5, 1, 0.3, 0.1],
    "delirium": [20, 5, 1, 0.3, 0.1],
    "abyss": [20, 5, 1, 0.3, 0.1],
    "uncutgems": [20, 5, 1, 0.3, 0.1],
    "idols": [20, 5, 1, 0.3, 0.1],
}

DEFAULTS: dict[str, Any] = {
    "league": "",  # пусто = определить автоматически (первая temp-лига poe.ninja)
    "realm": "poe2",
    "trade_host": "https://www.pathofexile.com",
    "poesessid": "",
    "hotkey_price_check": "Ctrl+D",
    "hotkey_toggle_overlay": "Ctrl+Alt+D",
    "language": "ru",
    # --- поиск ---
    "search": {
        "status": "online",  # online | any
        "default_listings": 20,
        "auto_search_on_open": True,
        # какие категории модов включать в поиск по умолчанию
        "enabled_mod_types_by_default": ["explicit", "implicit", "fractured", "desecrated"],
        # ширина диапазона по умолчанию: min = значение * (1 - roll_tolerance)
        "roll_tolerance": 0.10,
        "use_min_only": True,
        # Какие параметры вещи включать в поиск сразу (ключи trade2 API:
        # dps, pdps, edps, crit, aps, reload_time, ar, ev, es, block, spirit).
        # Показываются только те, что у предмета есть.
        "default_equipment_filters": ["pdps"],
        # Пересчитывать броню/ДПС по выбранным модам. Плоские прибавки
        # умножаются на проценты предмета, проценты складываются.
        "equipment_from_mods": True,
        "include_item_level": False,
        "include_quality": False,
        "include_corrupted": True,
        "include_sockets": False,
        "include_rarity": True,
    },
    # --- оверлей ---
    "overlay": {
        "opacity": 0.96,
        "font_size": 12,
        "width": 520,
        "max_height": 760,
        "close_on_focus_loss": True,
        "remember_position": False,
        "pos_x": 0,
        "pos_y": 0,
    },
    # --- фильтр ---
    "filter": {
        "enabled": True,
        "path": "",  # полный путь к .filter, пусто = не выбран
        "update_on_start": False,
        "write_in_place": True,  # False -> писать в <name>.autopriced.filter
        "make_backup": True,
        "max_backups": 20,
        "price_unit": "exalted",  # exalted | divine | chaos
        "groups": list(DEFAULT_TIER_THRESHOLDS.keys()),
        "thresholds": copy.deepcopy(DEFAULT_TIER_THRESHOLDS),
        "skip_blocks_with_stacksize": True,
        "keep_unknown_in_place": True,
        # NeverSink переименовывает теги $type-> от версии к версии, поэтому
        # помимо групп из списка выше берём все найденные в файле группы,
        # где цены известны хотя бы для половины баз.
        "auto_detect_groups": True,
        "auto_min_priced_ratio": 0.5,
        "ninja_types": [
            "Currency",
            "Fragments",
            "Essences",
            "Runes",
            "SoulCores",
            "Ritual",
            "Expedition",
            "Delirium",
            "Breach",
            "Abyss",
            "UncutGems",
            "LineageSupportGems",
            "Idols",
            "Verisium",
        ],
    },
    "network": {
        "user_agent": "PoE2Helper/0.1 (+https://github.com/; contact via app settings)",
        "timeout": 20,
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in override.items():
        if key in out and isinstance(out[key], dict) and isinstance(value, dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


class Config:
    """Плоско-вложенный конфиг с доступом через точку: cfg.get("filter.path")."""

    def __init__(self, data: dict[str, Any] | None = None):
        self._data = _deep_merge(DEFAULTS, data or {})

    # ------------------------------------------------------------------ IO
    @classmethod
    def load(cls) -> "Config":
        path = config_path()
        if path.exists():
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    return cls(raw)
                log.warning("config.json не является объектом, беру значения по умолчанию")
            except (OSError, json.JSONDecodeError) as exc:
                log.warning("Не удалось прочитать config.json: %s", exc)
        return cls()

    def save(self) -> None:
        path = config_path()
        tmp = path.with_suffix(".json.tmp")
        try:
            tmp.write_text(
                json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            tmp.replace(path)
        except OSError as exc:
            log.error("Не удалось сохранить config.json: %s", exc)

    # --------------------------------------------------------------- access
    def get(self, dotted: str, default: Any = None) -> Any:
        node: Any = self._data
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def set(self, dotted: str, value: Any) -> None:
        parts = dotted.split(".")
        node = self._data
        for part in parts[:-1]:
            nxt = node.get(part)
            if not isinstance(nxt, dict):
                nxt = {}
                node[part] = nxt
            node = nxt
        node[parts[-1]] = value

    @property
    def data(self) -> dict[str, Any]:
        return self._data

    def as_json(self) -> str:
        return json.dumps(self._data, ensure_ascii=False, indent=2)
