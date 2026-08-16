"""Generate the PWA icons (static/icons/icon-192.png, icon-512.png).

Renders the brand mark — the same status LED as the top bar's dot, an accent
circle on slate — to RGBA and writes valid PNGs using only the standard
library (struct + zlib). Run once to (re)generate:

    uv run python scripts/make_pwa_icons.py
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

SLATE = (15, 18, 24)  # #0f1218 — dark theme background
ACCENT = (77, 141, 255)  # #4d8dff — brand accent
RING_ALPHA = 0.32  # soft ring around the LED, like the .brand-dot glow

# Proportions relative to the icon size (match in .brand-dot and favicon.svg).
DOT_R = 0.18  # LED radius
RING_R = 0.235  # ring centre radius
RING_W = 0.028  # ring band width


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def render(size: int) -> list[bytes]:
    """Render the mark to one RGBA row per y (row = size * 4 bytes)."""
    cx = cy = (size - 1) / 2
    dot_r = DOT_R * size
    ring_r = RING_R * size
    ring_w = RING_W * size
    rows: list[bytes] = []
    for y in range(size):
        dy = y - cy
        row = bytearray()
        for x in range(size):
            dx = x - cx
            d = (dx * dx + dy * dy) ** 0.5
            # Anti-aliased soft ring, then the solid LED on top.
            half = ring_w / 2
            outer = _clamp(0.5 + (ring_r + half) - d, 0, 1)
            inner = _clamp(0.5 + d - (ring_r - half), 0, 1)
            ring_cov = min(outer, inner)
            r, g, b = SLATE
            a = RING_ALPHA * ring_cov
            if a > 0:
                r = SLATE[0] + (ACCENT[0] - SLATE[0]) * a
                g = SLATE[1] + (ACCENT[1] - SLATE[1]) * a
                b = SLATE[2] + (ACCENT[2] - SLATE[2]) * a
            dot_cov = _clamp(0.5 + dot_r - d, 0, 1)
            if dot_cov > 0:
                r += (ACCENT[0] - r) * dot_cov
                g += (ACCENT[1] - g) * dot_cov
                b += (ACCENT[2] - b) * dot_cov
            row.extend((int(r + 0.5), int(g + 0.5), int(b + 0.5), 255))
        rows.append(bytes(row))
    return rows


def _chunk(tag: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFF_FFFF)


def write_png(path: Path, size: int, rows: list[bytes]) -> None:
    raw = b"".join(b"\x00" + row for row in rows)
    png = b"\x89PNG\r\n\x1a\n"
    png += _chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
    png += _chunk(b"IDAT", zlib.compress(raw, 9))
    png += _chunk(b"IEND", b"")
    path.write_bytes(png)


def main() -> None:
    out_dir = Path(__file__).resolve().parent.parent / "src" / "dashboard" / "static" / "icons"
    out_dir.mkdir(parents=True, exist_ok=True)
    for size in (192, 512):
        target = out_dir / f"icon-{size}.png"
        write_png(target, size, render(size))
        print(f"wrote {target} ({target.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
