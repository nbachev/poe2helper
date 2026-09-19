"""Соблюдение лимитов запросов официального API PoE.

GGG отдаёт заголовки вида::

    X-Rate-Limit-Rules: Ip,Account
    X-Rate-Limit-Ip: 8:10:60,15:60:120
    X-Rate-Limit-Ip-State: 1:10:0,1:60:0

Формат ``hits:period:restrictTime``. Клиент обязан не превышать эти значения,
иначе аккаунт временно блокируется. Здесь — скользящее окно по каждому
правилу плюс уважение ``Retry-After``.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field

log = logging.getLogger(__name__)


@dataclass
class Rule:
    hits: int
    period: int
    restrict: int


@dataclass
class Policy:
    """Лимиты для одной группы эндпоинтов (search / fetch / ...)."""

    name: str
    rules: list[Rule] = field(default_factory=list)
    timestamps: deque[float] = field(default_factory=deque)
    blocked_until: float = 0.0

    def default_rules(self) -> list[Rule]:
        # Консервативные значения до первого ответа сервера.
        return [Rule(hits=4, period=10, restrict=10), Rule(hits=12, period=60, restrict=60)]


class RateLimiter:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._policies: dict[str, Policy] = {}

    def _policy(self, name: str) -> Policy:
        pol = self._policies.get(name)
        if pol is None:
            pol = Policy(name=name)
            pol.rules = pol.default_rules()
            self._policies[name] = pol
        return pol

    # ------------------------------------------------------------------ API
    def estimate_wait(self, name: str) -> float:
        """Сколько секунд придётся ждать перед следующим запросом."""
        with self._lock:
            pol = self._policy(name)
            now = time.time()
            wait = max(0.0, pol.blocked_until - now)
            for rule in pol.rules:
                if rule.hits <= 0:
                    continue
                window_start = now - rule.period
                recent = [t for t in pol.timestamps if t > window_start]
                # оставляем один слот в запасе
                budget = max(1, rule.hits - 1)
                if len(recent) >= budget:
                    oldest = recent[len(recent) - budget]
                    wait = max(wait, oldest + rule.period - now)
            return wait

    def acquire(self, name: str, max_wait: float = 60.0) -> None:
        """Блокирует поток, пока запрос не станет безопасным."""
        deadline = time.time() + max_wait
        while True:
            wait = self.estimate_wait(name)
            if wait <= 0:
                break
            if time.time() + wait > deadline:
                raise RateLimitedError(
                    f"Лимит запросов: нужно подождать {wait:.0f} с. Попробуй позже."
                )
            log.debug("rate limit %s: ждём %.2f c", name, wait)
            time.sleep(min(wait, 1.0))
        with self._lock:
            pol = self._policy(name)
            pol.timestamps.append(time.time())
            self._trim(pol)

    def _trim(self, pol: Policy) -> None:
        if not pol.rules:
            return
        horizon = time.time() - max(r.period for r in pol.rules) - 1
        while pol.timestamps and pol.timestamps[0] < horizon:
            pol.timestamps.popleft()

    def update_from_headers(self, name: str, headers) -> None:
        """Подстраивает лимиты по ответу сервера."""
        try:
            rules_header = headers.get("X-Rate-Limit-Rules") or headers.get("x-rate-limit-rules")
            if not rules_header:
                return
            merged: list[Rule] = []
            restrict_until = 0.0
            for rule_name in [r.strip() for r in rules_header.split(",") if r.strip()]:
                limits = headers.get(f"X-Rate-Limit-{rule_name}") or headers.get(
                    f"x-rate-limit-{rule_name.lower()}"
                )
                state = headers.get(f"X-Rate-Limit-{rule_name}-State") or headers.get(
                    f"x-rate-limit-{rule_name.lower()}-state"
                )
                if not limits:
                    continue
                for part in limits.split(","):
                    hits, period, restrict = (int(x) for x in part.split(":"))
                    merged.append(Rule(hits=hits, period=period, restrict=restrict))
                if state:
                    for part in state.split(","):
                        cur, period, blocked = (int(x) for x in part.split(":"))
                        if blocked > 0:
                            restrict_until = max(restrict_until, time.time() + blocked)
            with self._lock:
                pol = self._policy(name)
                if merged:
                    pol.rules = merged
                if restrict_until:
                    pol.blocked_until = restrict_until
                    log.warning("API временно ограничил %s на %.0f c", name, restrict_until - time.time())
        except (ValueError, AttributeError) as exc:
            log.debug("Не удалось разобрать заголовки лимитов: %s", exc)

    def penalize(self, name: str, seconds: float) -> None:
        with self._lock:
            pol = self._policy(name)
            pol.blocked_until = max(pol.blocked_until, time.time() + seconds)


class RateLimitedError(RuntimeError):
    pass
