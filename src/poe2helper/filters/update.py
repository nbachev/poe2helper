"""Полный цикл обновления итем-фильтра: цены -> перетиринг -> бэкап -> запись."""

from __future__ import annotations

import logging
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from ..config import Config
from ..paths import backup_dir
from ..trade.ninja import NinjaClient, NinjaError, PriceInfo
from .parse import FilterFile
from .retier import DEFAULT_SKIP_CONDITIONS, RetierReport, diff_text, retier

log = logging.getLogger(__name__)

Progress = Callable[[str], None]


@dataclass
class FilterUpdateResult:
    ok: bool = False
    message: str = ""
    report: RetierReport | None = None
    diff: str = ""
    written_path: Path | None = None
    backup_path: Path | None = None
    league: str = ""
    prices_count: int = 0


def _noop(_: str) -> None:
    return None


def resolve_league(cfg: Config, ninja: NinjaClient, progress: Progress = _noop) -> str:
    league = (cfg.get("league") or "").strip()
    if league:
        return league
    progress("Определяю текущую лигу…")
    league = ninja.default_league()
    cfg.set("league", league)
    cfg.save()
    return league


def fetch_prices(cfg: Config, ninja: NinjaClient, league: str, progress: Progress = _noop) -> dict[str, PriceInfo]:
    types = cfg.get("filter.ninja_types") or None
    progress("Качаю цены с poe.ninja…")
    prices = ninja.collect_prices(league, types)
    progress(f"Получено цен: {len(prices)}")
    return prices


def run_filter_update(
    cfg: Config,
    ninja: NinjaClient | None = None,
    dry_run: bool = False,
    progress: Progress = _noop,
    prices: dict[str, PriceInfo] | None = None,
) -> FilterUpdateResult:
    result = FilterUpdateResult()

    raw_path = (cfg.get("filter.path") or "").strip()
    if not raw_path:
        result.message = "Не выбран файл фильтра (Настройки → Итем-фильтр)."
        return result
    path = Path(raw_path)
    if not path.is_file():
        result.message = f"Файл фильтра не найден: {path}"
        return result

    ninja = ninja or NinjaClient(user_agent=cfg.get("network.user_agent", "PoE2Helper/0.1"))

    try:
        league = resolve_league(cfg, ninja, progress)
        result.league = league
        if prices is None:
            prices = fetch_prices(cfg, ninja, league, progress)
    except NinjaError as exc:
        result.message = str(exc)
        return result

    result.prices_count = len(prices)
    if not prices:
        result.message = "poe.ninja не вернул цен — обновление отменено."
        return result

    progress("Читаю фильтр…")
    try:
        ff = FilterFile.load(path)
    except OSError as exc:
        result.message = f"Не удалось прочитать фильтр: {exc}"
        return result

    before = ff.render()

    progress("Пересчитываю тиры…")
    report = retier(
        ff,
        prices,
        thresholds_by_group=cfg.get("filter.thresholds") or {},
        groups=cfg.get("filter.groups") or None,
        price_unit=cfg.get("filter.price_unit", "exalted"),
        skip_conditions=DEFAULT_SKIP_CONDITIONS
        if cfg.get("filter.skip_blocks_with_stacksize", True)
        else (),
        keep_unknown_in_place=cfg.get("filter.keep_unknown_in_place", True),
        auto_groups=bool(cfg.get("filter.auto_detect_groups", True)),
        auto_min_priced_ratio=float(cfg.get("filter.auto_min_priced_ratio", 0.5)),
    )
    result.report = report

    after = ff.render()
    result.diff = diff_text(before, after, path.name)

    if not report.has_changes:
        result.ok = True
        result.message = "Фильтр уже актуален — менять нечего."
        return result

    if dry_run:
        result.ok = True
        result.message = "Предпросмотр готов (файл не изменён)."
        return result

    target = path
    if not cfg.get("filter.write_in_place", True):
        target = path.with_name(f"{path.stem}.autopriced{path.suffix}")

    if cfg.get("filter.make_backup", True) and target.exists():
        try:
            result.backup_path = _make_backup(target, cfg.get("filter.max_backups", 20))
        except OSError as exc:
            log.warning("Бэкап не создан: %s", exc)

    progress("Сохраняю фильтр…")
    try:
        ff.save(target)
    except OSError as exc:
        result.message = f"Не удалось записать фильтр: {exc}"
        return result

    result.ok = True
    result.written_path = target
    result.message = (
        f"Фильтр обновлён: {target.name}. "
        f"Перемещено предметов: {len(report.moves)}. Лига: {league}."
    )
    return result


def _make_backup(path: Path, max_backups: int) -> Path:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    dest = backup_dir() / f"{path.stem}.{stamp}{path.suffix}"
    shutil.copy2(path, dest)
    _prune_backups(path.stem, max_backups)
    return dest


def _prune_backups(stem: str, max_backups: int) -> None:
    if max_backups <= 0:
        return
    files = sorted(
        backup_dir().glob(f"{stem}.*.filter"), key=lambda p: p.stat().st_mtime, reverse=True
    )
    for old in files[max_backups:]:
        try:
            old.unlink()
        except OSError:
            pass
