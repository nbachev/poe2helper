"""Точка входа: ``python -m poe2helper`` или собранный exe.

Важно: относительных импортов (``from .app import main``) здесь быть не может.
PyInstaller делает этот файл стартовым скриптом и выполняет его как
самостоятельный модуль ``__main__``, у которого нет родительского пакета —
относительный импорт в таком режиме падает с ImportError. Поэтому импорт
только абсолютный, а путь к пакету при необходимости добавляется вручную.
"""

from __future__ import annotations

import os
import sys

if __package__ in (None, "") and not getattr(sys, "frozen", False):
    # Запуск файлом, а не через -m: кладём каталог src/ в sys.path,
    # чтобы пакет poe2helper стал видимым. В собранном exe пакет уже
    # лежит внутри бандла, там трогать sys.path не нужно.
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from poe2helper.app import main  # noqa: E402  (импорт после правки sys.path)

if __name__ == "__main__":
    sys.exit(main())
