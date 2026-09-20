"""Экономика PoE2 с poe.ninja.

Эндпоинты (проверены на актуальной версии сайта)::

    GET https://poe.ninja/poe2/api/economy/leagues
    GET https://poe.ninja/poe2/api/economy/exchange/current/overview?league=..&type=..
    GET https://poe.ninja/poe2/api/economy/stash/current/item/overview?league=..&type=..

Ответ exchange-обзора::

    {
      "core": {"items": [...], "rates": {"exalted": 444.7, "chaos": 8.36},
               "primary": "divine", "secondary": "chaos"},
      "lines": [{"id": "alch", "primaryValue": 0.007415, ...}],
      "items": [{"id": "alch", "name": "Orb of Alchemy", "category": "Currency"}]
    }

``primaryValue`` — цена в primary-валюте (дивайны), ``rates`` — сколько
единиц другой валюты в одном primary. Значит ``цена_в_экзах =
primaryValue * rates["exalted"]``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import requests

log = logging.getLogger(__name__)

NINJA_BASE = "https://poe.ninja/poe2/api/economy"

EXCHANGE_TYPES = [
    "Currency",
    "Fragments",
    "Abyss",
    "UncutGems",
    "LineageSupportGems",
    "Essences",
    "SoulCores",
    "Idols",
    "Runes",
    "Ritual",
    "Expedition",
    "Delirium",
    "Breach",
    "Verisium",
]

STASH_TYPES = [
    "UniqueWeapons",
    "UniqueArmours",
    "UniqueAccessories",
    "UniqueFlasks",
    "UniqueCharms",
    "UniqueJewels",
    "UniqueSanctumRelics",
    "UniqueTablets",
    "PrecursorTablets",
]


class NinjaError(RuntimeError):
    pass


@dataclass
class PriceInfo:
    name: str
    divine: float
    exalted: float
    chaos: float
    category: str = ""
    source_type: str = ""
    change: float = 0.0

    def value(self, unit: str) -> float:
        return {"divine": self.divine, "exalted": self.exalted, "chaos": self.chaos}.get(
            unit, self.exalted
        )


class NinjaClient:
    def __init__(self, user_agent: str = "PoE2Helper/0.1", timeout: int = 20) -> None:
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": user_agent, "Accept": "application/json"})

    def _get(self, url: str, params: dict | None = None) -> dict | list:
        try:
            resp = self.session.get(url, params=params, timeout=self.timeout)
        except requests.RequestException as exc:
            raise NinjaError(f"poe.ninja недоступен: {exc}") from exc
        if resp.status_code >= 400:
            raise NinjaError(f"poe.ninja вернул {resp.status_code} для {url}")
        try:
            return resp.json()
        except ValueError as exc:
            raise NinjaError("poe.ninja вернул не-JSON ответ") from exc

    # --------------------------------------------------------------- лиги
    def leagues(self) -> list[str]:
        data = self._get(f"{NINJA_BASE}/leagues")
        out: list[str] = []
        if isinstance(data, list):
            for entry in data:
                if isinstance(entry, dict):
                    name = entry.get("id") or entry.get("name")
                    if name:
                        out.append(str(name))
        return out

    def default_league(self) -> str:
        """Первая лига из списка — как правило, текущая временная лига."""
        leagues = self.leagues()
        for name in leagues:
            low = name.lower()
            if low.startswith("hc ") or low in {"standard", "hardcore"}:
                continue
            return name
        return leagues[0] if leagues else "Standard"

    # --------------------------------------------------------------- цены
    def overview(self, league: str, type_name: str, stash: bool = False) -> dict[str, PriceInfo]:
        path = (
            f"{NINJA_BASE}/stash/current/item/overview"
            if stash
            else f"{NINJA_BASE}/exchange/current/overview"
        )
        payload = self._get(path, {"league": league, "type": type_name})
        if not isinstance(payload, dict):
            return {}
        return _parse_overview(payload, type_name)

    def collect_prices(
        self, league: str, types: list[str] | None = None, include_uniques: bool = False
    ) -> dict[str, PriceInfo]:
        """Сводная таблица «название предмета -> цена»."""
        prices: dict[str, PriceInfo] = {}
        for type_name in types or EXCHANGE_TYPES:
            try:
                chunk = self.overview(league, type_name)
            except NinjaError as exc:
                log.warning("Пропускаю категорию %s: %s", type_name, exc)
                continue
            for name, info in chunk.items():
                # при дубле оставляем более дорогой вариант
                if name not in prices or info.exalted > prices[name].exalted:
                    prices[name] = info
        if include_uniques:
            for type_name in STASH_TYPES:
                try:
                    chunk = self.overview(league, type_name, stash=True)
                except NinjaError as exc:
                    log.warning("Пропускаю категорию %s: %s", type_name, exc)
                    continue
                for name, info in chunk.items():
                    if name not in prices or info.exalted > prices[name].exalted:
                        prices[name] = info
        return prices


def _parse_overview(payload: dict, type_name: str) -> dict[str, PriceInfo]:
    core = payload.get("core") or {}
    rates = core.get("rates") or {}
    ex_rate = _as_float(rates.get("exalted"))
    chaos_rate = _as_float(rates.get("chaos"))

    meta: dict[str, dict] = {}
    for bucket in (payload.get("items"), core.get("items")):
        if isinstance(bucket, list):
            for entry in bucket:
                if isinstance(entry, dict) and entry.get("id"):
                    meta[str(entry["id"])] = entry

    out: dict[str, PriceInfo] = {}
    for line in payload.get("lines") or []:
        if not isinstance(line, dict):
            continue
        line_id = str(line.get("id") or "")
        info_meta = meta.get(line_id) or {}
        name = str(info_meta.get("name") or line.get("name") or "").strip()
        if not name:
            continue
        divine = _as_float(line.get("primaryValue"))
        if divine is None:
            continue
        sparkline = line.get("sparkline") or {}
        out[name] = PriceInfo(
            name=name,
            divine=divine,
            exalted=divine * ex_rate if ex_rate else 0.0,
            chaos=divine * chaos_rate if chaos_rate else 0.0,
            category=str(info_meta.get("category") or ""),
            source_type=type_name,
            change=_as_float(sparkline.get("totalChange")) or 0.0,
        )
    return out


def _as_float(value) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
