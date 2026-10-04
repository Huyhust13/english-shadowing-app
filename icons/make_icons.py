#!/usr/bin/env python3
"""Draw the app icon: a speech waveform with its offset "shadow".

Writes icon.svg (browser tab), icon-32.png (fallback favicon) and
apple-touch-icon.png (phone home screen). Pure Python, no image libraries.
Usage: python3 icons/make_icons.py
"""
import os
import struct
import zlib

OUT_DIR = os.path.dirname(os.path.abspath(__file__))

GRID = 64  # all geometry below is on a 64x64 grid
BG = (0xB4, 0x72, 0x2E)        # --accent
BAR = (0xFB, 0xF8, 0xF1)       # warm off-white
SHADOW = (0x17, 0x21, 0x1C)    # --text
SHADOW_ALPHA = 0.32
SHADOW_OFFSET = 3
BG_RADIUS = 14

BAR_W = 6
BAR_R = 3
BARS = [(9, 16), (19, 30), (29, 42), (39, 26), (49, 14)]  # (x, height), centered on y=32


def bar_rects(dx=0, dy=0):
    return [(x + dx, 32 - h / 2 + dy, BAR_W, h) for x, h in BARS]


def hex_rgb(c):
    return "#%02X%02X%02X" % c


def write_svg(path):
    def rects(dx, dy):
        return "".join(
            f'<rect x="{x:g}" y="{y:g}" width="{w}" height="{h:g}" rx="{BAR_R}"/>'
            for x, y, w, h in bar_rects(dx, dy)
        )

    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {GRID} {GRID}">'
        f'<rect width="{GRID}" height="{GRID}" rx="{BG_RADIUS}" fill="{hex_rgb(BG)}"/>'
        f'<g fill="{hex_rgb(SHADOW)}" fill-opacity="{SHADOW_ALPHA}">{rects(SHADOW_OFFSET, SHADOW_OFFSET)}</g>'
        f'<g fill="{hex_rgb(BAR)}">{rects(0, 0)}</g>'
        "</svg>\n"
    )
    with open(path, "w") as f:
        f.write(svg)


def in_round_rect(px, py, x, y, w, h, r):
    if px < x or px > x + w or py < y or py > y + h:
        return False
    cx = min(max(px, x + r), x + w - r)
    cy = min(max(py, y + r), y + h - r)
    return (px - cx) ** 2 + (py - cy) ** 2 <= r * r


def mix(a, b, t):
    return tuple(a[i] + (b[i] - a[i]) * t for i in range(3))


def render(size, rounded_bg, samples=4):
    """Return RGBA rows; rounded_bg=False fills the square (iOS masks it itself)."""
    scale = GRID / size
    shadows = bar_rects(SHADOW_OFFSET, SHADOW_OFFSET)
    bars = bar_rects()
    rows = []
    for py in range(size):
        row = bytearray()
        for px in range(size):
            r = g = b = a = 0.0
            for sy in range(samples):
                for sx in range(samples):
                    gx = (px + (sx + 0.5) / samples) * scale
                    gy = (py + (sy + 0.5) / samples) * scale
                    if rounded_bg and not in_round_rect(gx, gy, 0, 0, GRID, GRID, BG_RADIUS):
                        continue
                    color = BG
                    if any(in_round_rect(gx, gy, *rect, BAR_R) for rect in shadows):
                        color = mix(color, SHADOW, SHADOW_ALPHA)
                    if any(in_round_rect(gx, gy, *rect, BAR_R) for rect in bars):
                        color = BAR
                    r, g, b, a = r + color[0], g + color[1], b + color[2], a + 1
            n = samples * samples
            if a:
                row += bytes((round(r / a), round(g / a), round(b / a), round(255 * a / n)))
            else:
                row += b"\0\0\0\0"
        rows.append(bytes(row))
    return rows


def write_png(path, rows):
    size = len(rows)

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    raw = b"".join(b"\0" + row for row in rows)
    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )
    with open(path, "wb") as f:
        f.write(png)


if __name__ == "__main__":
    write_svg(os.path.join(OUT_DIR, "icon.svg"))
    write_png(os.path.join(OUT_DIR, "icon-32.png"), render(32, rounded_bg=True))
    write_png(os.path.join(OUT_DIR, "apple-touch-icon.png"), render(180, rounded_bg=False))
    print("Wrote icon.svg, icon-32.png, apple-touch-icon.png to", OUT_DIR)
