"""Клиент официального API торговой площадки Path of Exile 2 (realm ``poe2``).

Эндпоинты::

    GET  {host}/api/trade2/data/stats
    GET  {host}/api/trade2/data/items
    GET  {host}/api/trade2/data/static
    POST {host}/api/trade2/search/{realm}/{league}
    GET  {host}/api/trade2/fetch/{id1,id2,...}?query={searchId}&realm={realm}

Ссылка для браузера: ``{host}/trade2/search/{realm}/{league}/{searchId}``.
"""

from __future__ import annotations

import logging
import urllib.parse
from dataclasses import dataclass, field
from typing import Any

import requests

from .ratelimit import RateLimitedError, RateLimiter

log = logging.getLogger(__name__)

DEFAULT_HOST = "https://www.pathofexile.com"


class TradeError(RuntimeError):
    """Ошибка обращения к торговой площадке, пригодная для показа пользователю."""


@dataclass
class Listing:
    """Один лот из выдачи."""

    item_name: str = ""
    base_type: str = ""
    price_amount: float | None = None
    price_currency: str = ""
    account: str = ""
    whisper: str = ""
    indexed: str = ""
    item_level: int | None = None
    corrupted: bool = False
    note: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def price_text(self) -> str:
        if self.price_amount is None:
            return "—"
        amount = self.price_amount
        text = f"{amount:g}"
        return f"{text} {self.price_currency}".strip()


@dataclass
class SearchResult:
    search_id: str = ""
    total: int = 0
    complexity: int | None = None
    result_ids: list[str] = field(default_factory=list)
    listings: list[Listing] = field(default_factory=list)
    url: str = ""


class TradeClient:
    def __init__(
        self,
        host: str = DEFAULT_HOST,
        realm: str = "poe2",
        user_agent: str = "PoE2Helper/0.1",
        poesessid: str = "",
        timeout: int = 20,
    ) -> None:
        self.host = host.rstrip("/")
        self.realm = realm
        self.timeout = timeout
        self.limiter = RateLimiter()
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": user_agent,
                "Accept": "application/json",
                "Accept-Language": "en-US,en;q=0.9",
            }
        )
        self.set_poesessid(poesessid)

    # ---------------------------------------------------------------- utils
    def set_poesessid(self, value: str) -> None:
        value = (value or "").strip()
        self.session.cookies.clear()
        if value:
            self.session.cookies.set("POESESSID", value, domain=".pathofexile.com")

    def _request(self, method: str, url: str, policy: str, **kwargs) -> requests.Response:
        self.limiter.acquire(policy)
        try:
            resp = self.session.request(method, url, timeout=self.timeout, **kwargs)
        except requests.RequestException as exc:
            raise TradeError(f"Сеть недоступна: {exc}") from exc

        self.limiter.update_from_headers(policy, resp.headers)

        if resp.status_code == 429:
            retry = resp.headers.get("Retry-After")
            wait = float(retry) if retry and retry.isdigit() else 60.0
            self.limiter.penalize(policy, wait)
            raise TradeError(
                f"Слишком много запросов к торговой площадке. Подожди {wait:.0f} с."
            )
        if resp.status_code == 403:
            raise TradeError(
                "Торговая площадка ответила 403. Обычно помогает указать POESESSID "
                "в настройках (Cloudflare требует авторизованную сессию)."
            )
        if resp.status_code in (401, 404) and "/search/" in url:
            raise TradeError(
                f"Ответ {resp.status_code}: проверь название лиги в настройках."
            )
        if resp.status_code >= 400:
            detail = ""
            try:
                body = resp.json()
                detail = str(body.get("error", {}).get("message") or "")
            except ValueError:
                detail = resp.text[:200]
            raise TradeError(f"Ошибка {resp.status_code}: {detail}")
        return resp

    # ----------------------------------------------------------------- data
    def fetch_stats(self) -> dict:
        """Пул модификаторов. Пробуем с realm и без него."""
        last_error: Exception | None = None
        for params in ({"realm": self.realm}, None):
            url = f"{self.host}/api/trade2/data/stats"
            try:
                resp = self._request("GET", url, policy="data", params=params)
                payload = resp.json()
                if payload.get("result"):
                    return payload
            except (TradeError, ValueError, RateLimitedError) as exc:
                last_error = exc
        if last_error:
            raise TradeError(f"Не удалось скачать список модов: {last_error}")
        raise TradeError("Торговая площадка вернула пустой список модов.")

    def fetch_static(self) -> dict:
        url = f"{self.host}/api/trade2/data/static"
        resp = self._request("GET", url, policy="data", params={"realm": self.realm})
        return resp.json()

    def fetch_items(self) -> dict:
        url = f"{self.host}/api/trade2/data/items"
        resp = self._request("GET", url, policy="data", params={"realm": self.realm})
        return resp.json()

    # --------------------------------------------------------------- search
    def search_url(self, league: str, search_id: str) -> str:
        league_q = urllib.parse.quote(league)
        return f"{self.host}/trade2/search/{self.realm}/{league_q}/{search_id}"

    def search(self, league: str, query: dict, limit: int = 20) -> SearchResult:
        if not league:
            raise TradeError("Не выбрана лига.")
        league_q = urllib.parse.quote(league)
        url = f"{self.host}/api/trade2/search/{self.realm}/{league_q}"
        resp = self._request(
            "POST",
            url,
            policy="search",
            json=query,
            headers={"Content-Type": "application/json"},
        )
        try:
            payload = resp.json()
        except ValueError as exc:
            raise TradeError("Торговая площадка вернула не-JSON ответ.") from exc

        result = SearchResult(
            search_id=str(payload.get("id") or ""),
            total=int(payload.get("total") or 0),
            complexity=payload.get("complexity"),
            result_ids=[str(x) for x in (payload.get("result") or [])],
        )
        result.url = self.search_url(league, result.search_id) if result.search_id else ""
        if result.result_ids:
            result.listings = self.fetch_listings(result.result_ids[:limit], result.search_id)
        return result

    def fetch_listings(self, ids: list[str], search_id: str) -> list[Listing]:
        out: list[Listing] = []
        for chunk_start in range(0, len(ids), 10):
            chunk = ids[chunk_start : chunk_start + 10]
            url = f"{self.host}/api/trade2/fetch/{','.join(chunk)}"
            resp = self._request(
                "GET",
                url,
                policy="fetch",
                params={"query": search_id, "realm": self.realm},
            )
            try:
                payload = resp.json()
            except ValueError:
                continue
            for raw in payload.get("result") or []:
                if raw:
                    out.append(_parse_listing(raw))
        return out


def _parse_listing(raw: dict) -> Listing:
    item = raw.get("item") or {}
    listing = raw.get("listing") or {}
    price = listing.get("price") or {}
    account = (listing.get("account") or {}).get("name") or ""
    whisper = listing.get("whisper") or ""
    amount = price.get("amount")
    return Listing(
        item_name=str(item.get("name") or ""),
        base_type=str(item.get("baseType") or item.get("typeLine") or ""),
        price_amount=float(amount) if isinstance(amount, (int, float)) else None,
        price_currency=str(price.get("currency") or ""),
        account=str(account),
        whisper=str(whisper),
        indexed=str(listing.get("indexed") or ""),
        item_level=item.get("ilvl"),
        corrupted=bool(item.get("corrupted")),
        note=str(item.get("note") or ""),
        raw=raw,
    )
