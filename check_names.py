"""Проверка необъявленных глобальных имён без запуска кода.

Компилируем модуль, обходим все code-объекты и смотрим LOAD_GLOBAL.
Если имени нет ни среди импортов/определений модуля, ни среди builtins —
это опечатка или забытый импорт. Заодно ловим импорты, которые нигде
не используются.

Запуск: ``python tools/check_names.py src``
"""

from __future__ import annotations

import ast
import builtins
import dis
import sys
from pathlib import Path

BUILTINS = set(dir(builtins)) | {"__file__", "__name__", "__doc__", "__spec__", "__package__"}


def module_level_names(tree: ast.Module) -> tuple[set[str], dict[str, int]]:
    names: set[str] = set()
    imports: dict[str, int] = {}

    for node in tree.body:
        _collect(node, names, imports, top=True)

    # имена из вложенных присваиваний на уровне модуля (if/try)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Global):
            names.update(node.names)
    return names, imports


def _collect(node: ast.AST, names: set[str], imports: dict[str, int], top: bool) -> None:
    if isinstance(node, ast.Import):
        for alias in node.names:
            bound = alias.asname or alias.name.split(".")[0]
            names.add(bound)
            imports[bound] = node.lineno
    elif isinstance(node, ast.ImportFrom):
        for alias in node.names:
            if alias.name == "*":
                continue
            bound = alias.asname or alias.name
            names.add(bound)
            imports[bound] = node.lineno
    elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        names.add(node.name)
        return
    elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        for target in targets:
            for sub in ast.walk(target):
                if isinstance(sub, ast.Name):
                    names.add(sub.id)
    elif isinstance(node, (ast.If, ast.Try, ast.For, ast.While, ast.With)):
        for child in ast.iter_child_nodes(node):
            _collect(child, names, imports, top=False)
        for handler in getattr(node, "handlers", []) or []:
            for child in ast.iter_child_nodes(handler):
                _collect(child, names, imports, top=False)
        for child in getattr(node, "orelse", []) or []:
            _collect(child, names, imports, top=False)
        for child in getattr(node, "finalbody", []) or []:
            _collect(child, names, imports, top=False)


def walk_code(code, seen=None):
    seen = seen if seen is not None else []
    seen.append(code)
    for const in code.co_consts:
        if hasattr(const, "co_code"):
            walk_code(const, seen)
    return seen


def used_globals(code) -> set[str]:
    out: set[str] = set()
    for sub in walk_code(code):
        for instr in dis.get_instructions(sub):
            if instr.opname in ("LOAD_GLOBAL", "LOAD_NAME", "DELETE_GLOBAL", "STORE_GLOBAL"):
                if isinstance(instr.argval, str):
                    out.add(instr.argval)
    return out


def used_attributes(tree: ast.Module) -> set[str]:
    """Имена, встречающиеся в аннотациях и строках-типах — их не видно в байткоде."""
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            out.add(node.id)
        elif isinstance(node, ast.Attribute):
            base = node
            while isinstance(base, ast.Attribute):
                base = base.value
            if isinstance(base, ast.Name):
                out.add(base.id)
    return out


def check_file(path: Path) -> list[str]:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    code = compile(source, str(path), "exec")

    defined, imports = module_level_names(tree)
    runtime_used = used_globals(code)  # только настоящие глобальные обращения
    any_used = runtime_used | used_attributes(tree)  # плюс аннотации-строки

    problems: list[str] = []
    for name in sorted(runtime_used - defined - BUILTINS):
        if name.startswith("__"):
            continue
        problems.append(f"{path}: неизвестное имя «{name}»")

    for name, lineno in sorted(imports.items(), key=lambda kv: kv[1]):
        if name == "annotations":
            continue
        if name not in any_used:
            problems.append(f"{path}:{lineno}: импорт «{name}» не используется")
    return problems


def main(argv: list[str]) -> int:
    roots = [Path(p) for p in (argv[1:] or ["src"])]
    problems: list[str] = []
    for root in roots:
        files = [root] if root.is_file() else sorted(root.rglob("*.py"))
        for path in files:
            try:
                problems += check_file(path)
            except SyntaxError as exc:
                problems.append(f"{path}: синтаксическая ошибка — {exc}")
    for line in problems:
        print(line)
    print(f"\nПроверено файлов, проблем: {len(problems)}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
