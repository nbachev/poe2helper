"""Определение путей: данные приложения, папка PoE2, папка фильтров."""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "PoE2Helper"


def is_frozen() -> bool:
    return getattr(sys, "frozen", False)


def app_dir() -> Path:
    """Папка, из которой запущено приложение (рядом с exe в собранном виде)."""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def data_dir() -> Path:
    """Папка для настроек и кэша.

    Портативный режим: если рядом с exe есть файл ``portable.txt`` или
    папка ``data``, всё хранится там. Иначе — в %APPDATA%.
    """
    base = app_dir()
    if (base / "portable.txt").exists() or (base / "data").is_dir():
        d = base / "data"
    else:
        appdata = os.environ.get("APPDATA")
        if appdata:
            d = Path(appdata) / APP_NAME
        else:  # не-Windows (разработка/тесты)
            d = Path.home() / ".config" / APP_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def cache_dir() -> Path:
    d = data_dir() / "cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


def backup_dir() -> Path:
    d = data_dir() / "filter-backups"
    d.mkdir(parents=True, exist_ok=True)
    return d


def log_path() -> Path:
    return data_dir() / "poe2helper.log"


def config_path() -> Path:
    return data_dir() / "config.json"


def _documents_dir() -> Path | None:
    """Папка «Документы» пользователя (учитывает перенос папки в OneDrive)."""
    if os.name != "nt":
        return None
    try:
        import ctypes
        import ctypes.wintypes as wt

        # SHGetKnownFolderPath(FOLDERID_Documents)
        class GUID(ctypes.Structure):
            _fields_ = [
                ("Data1", ctypes.c_ulong),
                ("Data2", ctypes.c_ushort),
                ("Data3", ctypes.c_ushort),
                ("Data4", ctypes.c_ubyte * 8),
            ]

        folderid_documents = GUID(
            0xFDD39AD0,
            0x238F,
            0x46AF,
            (ctypes.c_ubyte * 8)(0xAD, 0xB4, 0x6C, 0x85, 0x48, 0x03, 0x69, 0xC7),
        )
        path_ptr = ctypes.c_wchar_p()
        res = ctypes.windll.shell32.SHGetKnownFolderPath(
            ctypes.byref(folderid_documents), 0, None, ctypes.byref(path_ptr)
        )
        if res == 0 and path_ptr.value:
            result = Path(path_ptr.value)
            ctypes.windll.ole32.CoTaskMemFree(path_ptr)
            return result
    except Exception:  # pragma: no cover - только Windows
        pass
    home = Path.home()
    cand = home / "Documents"
    return cand if cand.exists() else None


def guess_filter_dirs() -> list[Path]:
    """Возможные папки с итем-фильтрами PoE2."""
    out: list[Path] = []
    docs = _documents_dir()
    candidates: list[Path] = []
    if docs:
        candidates.append(docs / "My Games" / "Path of Exile 2")
    home = Path.home()
    candidates += [
        home / "Documents" / "My Games" / "Path of Exile 2",
        home / "OneDrive" / "Documents" / "My Games" / "Path of Exile 2",
        home / "OneDrive" / "Документы" / "My Games" / "Path of Exile 2",
        home / "Документы" / "My Games" / "Path of Exile 2",
    ]
    for c in candidates:
        try:
            if c.is_dir() and c not in out:
                out.append(c)
        except OSError:
            continue
    return out


def guess_filter_dir() -> Path | None:
    dirs = guess_filter_dirs()
    return dirs[0] if dirs else None


def list_filter_files(directory: Path | None = None) -> list[Path]:
    dirs = [directory] if directory else guess_filter_dirs()
    files: list[Path] = []
    for d in dirs:
        if not d:
            continue
        try:
            files += sorted(p for p in d.glob("*.filter") if p.is_file())
        except OSError:
            continue
    return files
