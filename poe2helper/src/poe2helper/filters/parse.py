"""Парсер итем-фильтра Path of Exile 2.

Фильтр — это последовательность блоков ``Show``/``Hide`` с условиями и
директивами оформления. NeverSink помечает блоки комментарием вида::

    Show # %D6 $type->currency $tier->t1
        Class "Stackable Currency"
        BaseType == "Divine Orb" "Perfect Jeweller's Orb"
        SetFontSize 45

Парсер намеренно «нежадный»: он хранит исходные строки как есть и умеет
менять только список значений конкретного условия. Всё остальное
(оформление, комментарии, отступы, порядок блоков) остаётся нетронутым.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

BLOCK_START_RE = re.compile(r"^(\s*)(Show|Hide|Minimal)\b(.*)$")
TAG_TYPE_RE = re.compile(r"\$type->([^\s#]+)")
TAG_TIER_RE = re.compile(r"\$tier->([^\s#]+)")
CONDITION_RE = re.compile(r"^(\s*)([A-Za-z]+)(\s*(?:==|>=|<=|!=|<|>|=)?\s*)(.*?)(\s*#.*)?$")
QUOTED_RE = re.compile(r'"([^"]*)"|(\S+)')
TIER_NUM_RE = re.compile(r"^t(\d+)$", re.I)


def split_values(text: str) -> list[str]:
    """``"Divine Orb" "Chaos Orb"`` -> ``['Divine Orb', 'Chaos Orb']``."""
    out: list[str] = []
    for m in QUOTED_RE.finditer(text.strip()):
        value = m.group(1) if m.group(1) is not None else m.group(2)
        if value is not None and value != "":
            out.append(value)
    return out


def join_values(values: list[str]) -> str:
    return " ".join(f'"{v}"' for v in values)


@dataclass
class Block:
    """Один блок Show/Hide вместе со всеми своими строками."""

    lines: list[str] = field(default_factory=list)
    line_no: int = 0  # номер первой строки в исходном файле (с 1)

    # ------------------------------------------------------------- свойства
    @property
    def header(self) -> str:
        return self.lines[0] if self.lines else ""

    @property
    def action(self) -> str:
        m = BLOCK_START_RE.match(self.header)
        return m.group(2) if m else ""

    @property
    def tags(self) -> dict[str, str]:
        out: dict[str, str] = {}
        m = TAG_TYPE_RE.search(self.header)
        if m:
            out["type"] = m.group(1)
        m = TAG_TIER_RE.search(self.header)
        if m:
            out["tier"] = m.group(1)
        return out

    @property
    def type_tag(self) -> str:
        return self.tags.get("type", "")

    @property
    def tier_tag(self) -> str:
        return self.tags.get("tier", "")

    @property
    def tier_number(self) -> int | None:
        m = TIER_NUM_RE.match(self.tier_tag)
        return int(m.group(1)) if m else None

    # ------------------------------------------------------------- условия
    def find_condition(self, name: str) -> tuple[int, str, str, str] | None:
        """Возвращает ``(index, indent, operator, values_text)`` первого условия."""
        target = name.lower()
        for idx, line in enumerate(self.lines[1:], start=1):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            m = CONDITION_RE.match(line)
            if not m:
                continue
            if m.group(2).lower() == target:
                return idx, m.group(1), m.group(3), m.group(4)
        return None

    def has_condition(self, name: str) -> bool:
        return self.find_condition(name) is not None

    def condition_values(self, name: str) -> list[str]:
        found = self.find_condition(name)
        if not found:
            return []
        return split_values(found[3])

    def set_condition_values(self, name: str, values: list[str], empty_placeholder: str | None = None) -> bool:
        """Переписывает список значений условия, сохраняя отступ и оператор."""
        found = self.find_condition(name)
        if not found:
            return False
        idx, indent, operator, _ = found
        original = self.lines[idx]
        trailing = ""
        m = CONDITION_RE.match(original)
        if m and m.group(5):
            trailing = m.group(5)
        if not values:
            if empty_placeholder is None:
                return False
            values = [empty_placeholder]
        op = operator if operator.strip() else " == "
        if not op.startswith(" "):
            op = " " + op
        if not op.endswith(" "):
            op = op + " "
        self.lines[idx] = f"{indent}{name}{op}{join_values(values)}{trailing}"
        return True

    @property
    def base_types(self) -> list[str]:
        return self.condition_values("BaseType")

    @property
    def classes(self) -> list[str]:
        return self.condition_values("Class")

    def text(self) -> str:
        return "\n".join(self.lines)


@dataclass
class FilterFile:
    path: Path | None = None
    preamble: list[str] = field(default_factory=list)
    blocks: list[Block] = field(default_factory=list)
    newline: str = "\n"
    had_trailing_newline: bool = True

    @classmethod
    def parse_text(cls, text: str, path: Path | None = None) -> "FilterFile":
        newline = "\r\n" if "\r\n" in text else "\n"
        had_trailing_newline = text.endswith(("\n", "\r"))
        raw_lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        if had_trailing_newline and raw_lines and raw_lines[-1] == "":
            raw_lines.pop()

        ff = cls(path=path, newline=newline, had_trailing_newline=had_trailing_newline)
        current: Block | None = None
        for i, line in enumerate(raw_lines, start=1):
            if BLOCK_START_RE.match(line):
                current = Block(lines=[line], line_no=i)
                ff.blocks.append(current)
            elif current is None:
                ff.preamble.append(line)
            else:
                current.lines.append(line)
        return ff

    @classmethod
    def load(cls, path: Path) -> "FilterFile":
        # newline="" — иначе Python сам схлопнет CRLF в LF и мы потеряем
        # исходный стиль переводов строк при обратной записи.
        with open(path, "r", encoding="utf-8-sig", errors="replace", newline="") as fh:
            text = fh.read()
        return cls.parse_text(text, path=path)

    def render(self) -> str:
        parts: list[str] = list(self.preamble)
        for block in self.blocks:
            parts.extend(block.lines)
        text = self.newline.join(parts)
        if self.had_trailing_newline:
            text += self.newline
        return text

    def save(self, path: Path | None = None) -> Path:
        target = path or self.path
        if target is None:
            raise ValueError("Не задан путь для сохранения фильтра")
        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.write_text(self.render(), encoding="utf-8", newline="")
        tmp.replace(target)
        return target

    # ------------------------------------------------------------ выборки
    def blocks_by_type(self) -> dict[str, list[Block]]:
        out: dict[str, list[Block]] = {}
        for block in self.blocks:
            tag = block.type_tag
            if tag:
                out.setdefault(tag.lower(), []).append(block)
        return out

    def known_types(self) -> list[str]:
        return sorted(self.blocks_by_type().keys())
