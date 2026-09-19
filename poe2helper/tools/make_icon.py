"""Генерирует resources/icon.ico без сторонних библиотек.

Иконка — тёмный скруглённый квадрат с золотой рамкой и буквами «P2».
Формат .ico с вложенными PNG (поддерживается начиная с Windows Vista).
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

SIZES = (16, 24, 32, 48, 64, 128, 256)

BG = (21, 23, 28, 255)
BORDER = (200, 165, 91, 255)
FILL = (122, 101, 53, 255)
GLYPH = (23, 24, 28, 255)

# Растровые маски 5x7 для символов «P» и «2»
GLYPHS = {
    "P": [
        "1111 ",
        "1   1",
        "1   1",
        "1111 ",
        "1    ",
        "1    ",
        "1    ",
    ],
    "2": [
        " 111 ",
        "1   1",
        "    1",
        "   1 ",
        "  1  ",
        " 1   ",
        "11111",
    ],
}


def blend(dst: tuple[int, int, int, int], src: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    sa = src[3] / 255.0
    if sa >= 1.0:
        return src
    return (
        int(src[0] * sa + dst[0] * (1 - sa)),
        int(src[1] * sa + dst[1] * (1 - sa)),
        int(src[2] * sa + dst[2] * (1 - sa)),
        max(dst[3], src[3]),
    )


def render(size: int) -> bytes:
    """RGBA-пиксели размером size x size."""
    px = [[(0, 0, 0, 0) for _ in range(size)] for _ in range(size)]

    pad = max(1, round(size * 0.06))
    radius = max(2, round(size * 0.22))
    border_w = max(1, round(size * 0.05))

    lo, hi = pad, size - 1 - pad

    def inside_rounded(x: int, y: int, shrink: int = 0) -> bool:
        x0, y0 = lo + shrink, lo + shrink
        x1, y1 = hi - shrink, hi - shrink
        if x < x0 or x > x1 or y < y0 or y > y1:
            return False
        r = max(0, radius - shrink)
        for cx, cy in ((x0 + r, y0 + r), (x1 - r, y0 + r), (x0 + r, y1 - r), (x1 - r, y1 - r)):
            in_x = (x < x0 + r and cx == x0 + r) or (x > x1 - r and cx == x1 - r)
            in_y = (y < y0 + r and cy == y0 + r) or (y > y1 - r and cy == y1 - r)
            if in_x and in_y:
                return (x - cx) ** 2 + (y - cy) ** 2 <= r * r
        return True

    for y in range(size):
        for x in range(size):
            if not inside_rounded(x, y):
                continue
            if inside_rounded(x, y, border_w):
                px[y][x] = blend(px[y][x], BG)
                px[y][x] = blend(px[y][x], FILL[:3] + (70,))
            else:
                px[y][x] = blend(px[y][x], BORDER)

    _draw_text(px, size)
    return _to_rgba_bytes(px, size)


def _draw_text(px, size: int) -> None:
    if size < 16:
        return
    scale = max(1, round(size / 16))
    glyph_w, glyph_h = 5 * scale, 7 * scale
    gap = scale
    total_w = glyph_w * 2 + gap
    start_x = (size - total_w) // 2
    start_y = (size - glyph_h) // 2

    for idx, char in enumerate("P2"):
        mask = GLYPHS[char]
        ox = start_x + idx * (glyph_w + gap)
        for row, line in enumerate(mask):
            for col, cell in enumerate(line):
                if cell != "1":
                    continue
                for dy in range(scale):
                    for dx in range(scale):
                        x = ox + col * scale + dx
                        y = start_y + row * scale + dy
                        if 0 <= x < size and 0 <= y < size:
                            px[y][x] = GLYPH


def _to_rgba_bytes(px, size: int) -> bytes:
    out = bytearray()
    for y in range(size):
        for x in range(size):
            out.extend(bytes(px[y][x]))
    return bytes(out)


def make_png(rgba: bytes, size: int) -> bytes:
    raw = bytearray()
    stride = size * 4
    for y in range(size):
        raw.append(0)  # filter type None
        raw.extend(rgba[y * stride : (y + 1) * stride])

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    header = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + chunk(b"IEND", b"")
    )


def make_ico(path: Path) -> Path:
    images = [(size, make_png(render(size), size)) for size in SIZES]
    count = len(images)
    offset = 6 + 16 * count
    out = bytearray(struct.pack("<HHH", 0, 1, count))
    body = bytearray()
    for size, data in images:
        dim = 0 if size >= 256 else size
        out.extend(struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(data), offset))
        offset += len(data)
        body.extend(data)
    out.extend(body)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(bytes(out))
    return path


if __name__ == "__main__":
    target = Path(__file__).resolve().parents[1] / "resources" / "icon.ico"
    print("Иконка записана:", make_ico(target))
