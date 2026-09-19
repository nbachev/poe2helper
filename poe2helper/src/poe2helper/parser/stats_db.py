"""Пул модификаторов торговой площадки PoE2 и сопоставление текста мода с id.

Данные берутся с ``/api/trade2/data/stats`` и кэшируются на диск.
Сопоставление текста делается по нормализованному шаблону:
числа заменяются на ``#``, скобочные синонимы (``[Evasion|Evasion Rating]``)
раскрываются, регистр и пробелы приводятся к единому виду.
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass

from ..paths import cache_dir

log = logging.getLogger(__name__)

CACHE_FILE = "trade2_stats.json"
CACHE_TTL = 7 * 24 * 3600  # неделя

NUMBER_RE = re.compile(r"[+-]?\d+(?:\.\d+)?")
BRACKET_RE = re.compile(r"\[([^\[\]]+)\]")
WS_RE = re.compile(r"\s+")

# Порядок приоритета при выборе среди одинаковых текстов
KIND_PRIORITY = [
    "explicit",
    "implicit",
    "fractured",
    "desecrated",
    "rune",
    "enchant",
    "crafted",
    "sanctum",
    "skill",
    "pseudo",
]


@dataclass(frozen=True)
class StatEntry:
    """Запись из пула модов."""

    id: str
    text: str  # исходный текст с '#'
    kind: str  # explicit / implicit / ...
    group: str  # label группы для UI
    options: tuple[tuple[int | str, str], ...] = ()

    @property
    def has_options(self) -> bool:
        return bool(self.options)

    @property
    def display(self) -> str:
        return f"{self.text}  [{self.kind}]"


def expand_brackets(text: str) -> str:
    """``[Evasion|Evasion Rating]`` -> ``Evasion Rating``; ``[Attack]`` -> ``Attack``."""

    def repl(m: re.Match[str]) -> str:
        inner = m.group(1)
        if "|" in inner:
            return inner.split("|")[-1]
        return inner

    prev = None
    out = text
    while prev != out:
        prev = out
        out = BRACKET_RE.sub(repl, out)
    return out


def normalize(text: str) -> str:
    """Нормализованный ключ для сопоставления."""
    t = expand_brackets(text)
    t = NUMBER_RE.sub("#", t)
    t = t.replace("+#", "#").replace("-#", "#")
    t = t.replace("−", "-")
    t = WS_RE.sub(" ", t).strip().lower()
    t = t.rstrip(".")
    return t


class StatsDB:
    """Индекс всех модов торговой площадки."""

    def __init__(self, entries: list[StatEntry] | None = None):
        self.fetched_at: float = 0.0
        self.entries: list[StatEntry] = entries or []
        self._by_key: dict[str, list[StatEntry]] = {}
        self._by_id: dict[str, StatEntry] = {}
        self._option_prefixes: list[tuple[str, StatEntry]] = []
        self._rebuild()

    # ------------------------------------------------------------ загрузка
    @classmethod
    def from_api_payload(cls, payload: dict) -> "StatsDB":
        entries: list[StatEntry] = []
        for group in payload.get("result", []):
            group_label = str(group.get("label") or group.get("id") or "")
            for raw in group.get("entries", []):
                sid = raw.get("id")
                text = raw.get("text")
                if not sid or not text:
                    continue
                kind = str(raw.get("type") or sid.split(".")[0])
                options: list[tuple[int | str, str]] = []
                opt = raw.get("option") or {}
                for o in opt.get("options", []) or []:
                    if "id" in o and "text" in o:
                        options.append((o["id"], str(o["text"])))
                entries.append(
                    StatEntry(
                        id=str(sid),
                        text=str(text),
                        kind=kind,
                        group=group_label,
                        options=tuple(options),
                    )
                )
        return cls(entries)

    @classmethod
    def load_cached(cls) -> "StatsDB | None":
        path = cache_dir() / CACHE_FILE
        if not path.exists():
            return None
        try:
            blob = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            log.warning("Кэш модов повреждён: %s", exc)
            return None
        payload = blob.get("payload")
        if not isinstance(payload, dict):
            return None
        db = cls.from_api_payload(payload)
        db.fetched_at = float(blob.get("fetched_at") or 0)
        return db

    def save_cache(self, payload: dict) -> None:
        path = cache_dir() / CACHE_FILE
        try:
            path.write_text(
                json.dumps({"fetched_at": time.time(), "payload": payload}, ensure_ascii=False),
                encoding="utf-8",
            )
        except OSError as exc:
            log.warning("Не удалось сохранить кэш модов: %s", exc)

    @property
    def is_stale(self) -> bool:
        return (time.time() - (self.fetched_at or 0)) > CACHE_TTL

    @property
    def is_empty(self) -> bool:
        return not self.entries

    # -------------------------------------------------------------- индекс
    def _rebuild(self) -> None:
        self._by_key.clear()
        self._by_id.clear()
        self._option_prefixes.clear()
        for entry in self.entries:
            self._by_id[entry.id] = entry
            key = normalize(entry.text)
            self._by_key.setdefault(key, []).append(entry)
            if entry.has_options:
                # "Allocates #" -> префикс "allocates"
                prefix = key.replace("#", "").strip()
                if prefix:
                    self._option_prefixes.append((prefix, entry))
        # длинные префиксы проверяем первыми
        self._option_prefixes.sort(key=lambda p: len(p[0]), reverse=True)

    def by_id(self, stat_id: str) -> StatEntry | None:
        return self._by_id.get(stat_id)

    # --------------------------------------------------------- сопоставление
    def match(self, mod_text: str, kind: str = "explicit") -> tuple[StatEntry | None, float | None, int | str | None]:
        """Ищет запись пула для текста мода.

        Возвращает ``(entry, value_multiplier, option_id)``.
        ``value_multiplier`` равен ``-1``, если пришлось заменить
        ``reduced``/``less`` на ``increased``/``more`` (значение нужно
        инвертировать), иначе ``1``. ``option_id`` заполняется для модов
        с вариантами (например «Allocates X»).
        """
        key = normalize(mod_text)

        found = self._pick(key, kind)
        if found is not None:
            return found, 1.0, None

        # reduced -> increased, less -> more (значение инвертируется)
        for src, dst in (("reduced", "increased"), ("less", "more")):
            if f" {src} " in f" {key} ":
                alt = re.sub(rf"\b{src}\b", dst, key)
                found = self._pick(alt, kind)
                if found is not None:
                    return found, -1.0, None

        # increased -> reduced (обратный случай)
        for src, dst in (("increased", "reduced"), ("more", "less")):
            if f" {src} " in f" {key} ":
                alt = re.sub(rf"\b{src}\b", dst, key)
                found = self._pick(alt, kind)
                if found is not None:
                    return found, -1.0, None

        # моды с вариантами: "Allocates Ancestral Knowledge"
        for prefix, entry in self._option_prefixes:
            if key.startswith(prefix):
                tail = key[len(prefix):].strip()
                if not tail:
                    continue
                for opt_id, opt_text in entry.options:
                    if normalize(opt_text) == tail:
                        return entry, 1.0, opt_id

        return None, None, None

    def _pick(self, key: str, kind: str) -> StatEntry | None:
        candidates = self._by_key.get(key)
        if not candidates:
            return None
        if len(candidates) == 1:
            return candidates[0]
        kind = (kind or "").lower()
        for c in candidates:
            if c.kind == kind:
                return c
        order = {k: i for i, k in enumerate(KIND_PRIORITY)}
        return sorted(candidates, key=lambda c: order.get(c.kind, 99))[0]

    # ------------------------------------------------------------- поиск UI
    def search(self, query: str, kinds: list[str] | None = None, limit: int = 300) -> list[StatEntry]:
        """Поиск по пулу модов для окна «Добавить мод»."""
        q = normalize(query).replace("#", "").strip()
        terms = [t for t in q.split(" ") if t]
        out: list[tuple[int, StatEntry]] = []
        for entry in self.entries:
            if kinds and entry.kind not in kinds:
                continue
            hay = normalize(entry.text)
            if terms and not all(t in hay for t in terms):
                continue
            score = len(hay)
            if terms and hay.startswith(terms[0]):
                score -= 1000
            out.append((score, entry))
            if len(out) > limit * 8:
                break
        out.sort(key=lambda p: p[0])
        return [e for _, e in out[:limit]]

    def kinds(self) -> list[str]:
        return sorted({e.kind for e in self.entries})
