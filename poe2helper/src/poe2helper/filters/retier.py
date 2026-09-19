"""Перетиринг итем-фильтра по актуальным ценам.

Идея: не переписывать фильтр, а перекладывать названия предметов между
уже существующими тир-блоками NeverSink (``$tier->t1`` … ``$tier->tN``)
внутри одной группы (``$type->currency``, ``$type->essences``, …).
Всё оформление автора остаётся на месте — меняются только строки
``BaseType``.
"""

from __future__ import annotations

import difflib
import logging
import re
from dataclasses import dataclass, field

from ..trade.ninja import PriceInfo
from .parse import Block, FilterFile

log = logging.getLogger(__name__)

EMPTY_PLACEHOLDER = "PoE2Helper-EmptyTier"

# Условия, наличие которых означает «блок завязан на прогрессию/стаки,
# не трогаем его, чтобы не сломать логику автора».
DEFAULT_SKIP_CONDITIONS = ("StackSize", "AreaLevel", "ItemLevel", "WaystoneTier", "Quality")

APOSTROPHES = str.maketrans({"’": "'", "ʼ": "'", "´": "'"})


def norm_name(name: str) -> str:
    return re.sub(r"\s+", " ", name.translate(APOSTROPHES)).strip().lower()


@dataclass
class Move:
    name: str
    group: str
    from_tier: int
    to_tier: int
    price: float


@dataclass
class RetierReport:
    moves: list[Move] = field(default_factory=list)
    unchanged: int = 0
    unknown: list[str] = field(default_factory=list)
    groups_processed: list[str] = field(default_factory=list)
    groups_autodetected: list[str] = field(default_factory=list)
    groups_skipped: dict[str, str] = field(default_factory=dict)
    changed_blocks: int = 0
    price_unit: str = "exalted"

    @property
    def has_changes(self) -> bool:
        return bool(self.moves) and self.changed_blocks > 0

    def summary(self) -> str:
        if not self.moves:
            return "Изменений нет — тиринг уже соответствует ценам."
        lines = [
            f"Перемещено предметов: {len(self.moves)} "
            f"(блоков изменено: {self.changed_blocks}, без изменений: {self.unchanged})",
        ]
        by_group: dict[str, list[Move]] = {}
        for mv in self.moves:
            by_group.setdefault(mv.group, []).append(mv)
        for group, moves in sorted(by_group.items()):
            lines.append(f"\n[{group}]")
            for mv in sorted(moves, key=lambda m: -m.price):
                arrow = "↑" if mv.to_tier < mv.from_tier else "↓"
                lines.append(
                    f"  {arrow} {mv.name}: t{mv.from_tier} → t{mv.to_tier} "
                    f"({mv.price:.3g} {self.price_unit})"
                )
        if self.groups_autodetected:
            lines.append(
                "\nГруппы, найденные автоматически: " + ", ".join(sorted(self.groups_autodetected))
            )
        if self.unknown:
            preview = ", ".join(sorted(set(self.unknown))[:12])
            more = "" if len(set(self.unknown)) <= 12 else f" и ещё {len(set(self.unknown)) - 12}"
            lines.append(f"\nБез цены (оставлены на месте): {preview}{more}")
        if self.groups_skipped:
            lines.append("\nПропущенные группы:")
            for group, reason in sorted(self.groups_skipped.items()):
                lines.append(f"  {group}: {reason}")
        return "\n".join(lines)


def adapt_thresholds(thresholds: list[float], tier_count: int) -> list[float]:
    """Приводит список порогов к ``tier_count - 1`` границам."""
    needed = max(0, tier_count - 1)
    th = [float(t) for t in thresholds if isinstance(t, (int, float))]
    th.sort(reverse=True)
    if not th:
        th = [10.0]
    while len(th) < needed:
        th.append(th[-1] / 3.0)
    return th[:needed]


def tier_for_price(price: float, thresholds: list[float]) -> int:
    """Индекс тира (0 = самый высокий) по цене."""
    for idx, bound in enumerate(thresholds):
        if price >= bound:
            return idx
    return len(thresholds)


def _eligible_blocks(blocks: list[Block], skip_conditions: tuple[str, ...]) -> list[tuple[int, Block]]:
    out: list[tuple[int, Block]] = []
    for block in blocks:
        tier = block.tier_number
        if tier is None:
            continue
        if not block.has_condition("BaseType"):
            continue
        if any(block.has_condition(cond) for cond in skip_conditions):
            continue
        out.append((tier, block))
    out.sort(key=lambda p: p[0])
    return out


def tier_blocks_for(
    blocks: list[Block], skip_conditions: tuple[str, ...] = DEFAULT_SKIP_CONDITIONS
) -> list[Block]:
    """Блоки группы, пригодные для перетиринга, по одному на номер тира."""
    seen: dict[int, Block] = {}
    for tier, block in _eligible_blocks(blocks, skip_conditions):
        seen.setdefault(tier, block)
    return [seen[t] for t in sorted(seen)]


def detect_groups(
    filter_file: FilterFile,
    skip_conditions: tuple[str, ...] = DEFAULT_SKIP_CONDITIONS,
    min_tiers: int = 2,
) -> dict[str, dict]:
    """Находит в фильтре все группы ``$type->`` с нумерованными тирами.

    NeverSink называет группы по-разному от версии к версии и использует
    вложенные имена вроде ``endgame->normalcraft->any``, поэтому надёжнее
    прочитать их прямо из файла, чем гадать по списку из настроек.
    """
    out: dict[str, dict] = {}
    for group, blocks in filter_file.blocks_by_type().items():
        ordered = tier_blocks_for(blocks, skip_conditions)
        if len(ordered) < min_tiers:
            continue
        names: list[str] = []
        for block in ordered:
            names += [n for n in block.base_types if n != EMPTY_PLACEHOLDER]
        out[group] = {
            "tiers": [b.tier_number for b in ordered],
            "base_types": names,
            "blocks": len(ordered),
        }
    return out


def _process_group(
    group: str,
    blocks: list[Block],
    price_index: dict[str, PriceInfo],
    thresholds: list[float],
    price_unit: str,
    skip_conditions: tuple[str, ...],
    keep_unknown_in_place: bool,
    report: RetierReport,
) -> bool:
    ordered = tier_blocks_for(blocks, skip_conditions)
    if len(ordered) < 2:
        report.groups_skipped[group] = "меньше двух подходящих тир-блоков"
        return False

    bounds = adapt_thresholds(thresholds, len(ordered))

    origin: dict[str, int] = {}
    order: list[str] = []
    for idx, block in enumerate(ordered):
        for name in block.base_types:
            if name == EMPTY_PLACEHOLDER:
                continue
            key = norm_name(name)
            if key in origin:
                continue
            origin[key] = idx
            order.append(name)

    if not order:
        report.groups_skipped[group] = "нет BaseType для распределения"
        return False

    buckets: list[list[str]] = [[] for _ in ordered]
    for name in order:
        key = norm_name(name)
        info = price_index.get(key)
        from_idx = origin[key]
        if info is None:
            buckets[from_idx if keep_unknown_in_place else -1].append(name)
            report.unknown.append(name)
            continue
        price = info.value(price_unit)
        to_idx = tier_for_price(price, bounds)
        buckets[to_idx].append(name)
        if to_idx != from_idx:
            report.moves.append(
                Move(
                    name=name,
                    group=group,
                    from_tier=_tier_no(ordered[from_idx]),
                    to_tier=_tier_no(ordered[to_idx]),
                    price=price,
                )
            )
        else:
            report.unchanged += 1

    for block, names in zip(ordered, buckets):
        if block.base_types == names:
            continue
        if block.set_condition_values("BaseType", names, empty_placeholder=EMPTY_PLACEHOLDER):
            report.changed_blocks += 1

    report.groups_processed.append(group)
    return True


def retier(
    filter_file: FilterFile,
    prices: dict[str, PriceInfo],
    thresholds_by_group: dict[str, list[float]],
    groups: list[str] | None = None,
    price_unit: str = "exalted",
    skip_conditions: tuple[str, ...] = DEFAULT_SKIP_CONDITIONS,
    keep_unknown_in_place: bool = True,
    auto_groups: bool = True,
    auto_min_priced_ratio: float = 0.5,
) -> RetierReport:
    """Раскладывает базы по тирам согласно ценам.

    Сначала обрабатываются группы из настроек. Если ``auto_groups``, то
    дополнительно берутся все найденные в файле группы, где хотя бы
    ``auto_min_priced_ratio`` баз имеют известную цену — это спасает, когда
    NeverSink переименовал теги и настройки промахнулись мимо них.
    """
    report = RetierReport(price_unit=price_unit)
    price_index = {norm_name(name): info for name, info in prices.items()}
    by_type = filter_file.blocks_by_type()
    default_profile = thresholds_by_group.get("currency") or [10]
    wanted = [g.lower() for g in (groups if groups is not None else list(thresholds_by_group))]

    handled: set[str] = set()
    for group in wanted:
        handled.add(group)
        blocks = by_type.get(group)
        if not blocks:
            report.groups_skipped[group] = "в фильтре нет блоков с таким $type"
            continue
        _process_group(
            group,
            blocks,
            price_index,
            thresholds_by_group.get(group, default_profile),
            price_unit,
            skip_conditions,
            keep_unknown_in_place,
            report,
        )

    if auto_groups:
        detected = detect_groups(filter_file, skip_conditions)
        for group, info in sorted(detected.items()):
            if group in handled:
                continue
            names = info["base_types"]
            if not names:
                continue
            priced = sum(1 for n in names if norm_name(n) in price_index)
            ratio = priced / len(names)
            if ratio < auto_min_priced_ratio:
                report.groups_skipped[group] = (
                    f"автоопределение: цены известны только для {priced} из {len(names)} баз"
                )
                continue
            report.groups_autodetected.append(group)
            _process_group(
                group,
                by_type[group],
                price_index,
                thresholds_by_group.get(group, default_profile),
                price_unit,
                skip_conditions,
                keep_unknown_in_place,
                report,
            )

    return report


def _tier_no(block: Block) -> int:
    return block.tier_number or 0


def diff_text(before: str, after: str, filename: str = "filter") -> str:
    diff = difflib.unified_diff(
        before.splitlines(),
        after.splitlines(),
        fromfile=f"{filename} (было)",
        tofile=f"{filename} (стало)",
        lineterm="",
        n=1,
    )
    return "\n".join(diff)
