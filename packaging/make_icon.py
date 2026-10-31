"""Render the app icon: a 1024px PNG (macOS .icns via iconutil) and/or a Windows .ico.

    python make_icon.py icon.png [icon.ico]

The mark is a hooded cloak with a fingerprint cut out of it, on a violet-to-cyan tile.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter

SIZE = 1024
SCALE = 4  # supersample for smooth edges

# Gradient stops (top-left -> bottom-right), as (position, rgb).
TILE_STOPS = ((0.0, (123, 63, 242)), (0.55, (59, 107, 255)), (1.0, (18, 200, 232)))
GLYPH_TOP, GLYPH_BOTTOM = (255, 255, 255), (220, 230, 255)


def _bezier(p0, p1, p2, p3, steps=48):
    for i in range(steps + 1):
        t = i / steps
        u = 1 - t
        yield (
            u**3 * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t**3 * p3[0],
            u**3 * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t**3 * p3[1],
        )


def _quad(p0, p1, p2, steps=16):
    for i in range(steps + 1):
        t = i / steps
        u = 1 - t
        yield (
            u * u * p0[0] + 2 * u * t * p1[0] + t * t * p2[0],
            u * u * p0[1] + 2 * u * t * p1[1] + t * t * p2[1],
        )


def _hood_points():
    """Hooded cloak outline in 1024-space: rounded crown, straight sides, flared hem."""
    pts = []
    pts += _bezier((512, 222), (396, 222), (316, 326), (316, 470))
    pts += [(316, 630)]
    pts += _bezier((316, 630), (316, 690), (296, 730), (262, 764))
    pts += _quad((262, 764), (244, 782), (262, 792))
    pts += [(762, 792)]
    pts += _quad((762, 792), (780, 782), (762, 764))
    pts += _bezier((762, 764), (728, 730), (708, 690), (708, 630))
    pts += [(708, 470)]
    pts += _bezier((708, 470), (708, 326), (628, 222), (512, 222))
    return pts


def _lerp_color(stops, t):
    t = min(max(t, 0.0), 1.0)
    for (p0, c0), (p1, c1) in zip(stops, stops[1:]):
        if t <= p1:
            k = (t - p0) / (p1 - p0)
            return tuple(c0[i] + (c1[i] - c0[i]) * k for i in range(3))
    return stops[-1][1]


def _diagonal_gradient(size, stops):
    """Linear gradient from (130,100) to (900,930) in 1024-space."""
    small = 256
    x0, y0, x1, y1 = (v * small / SIZE for v in (130, 100, 900, 930))
    dx, dy = x1 - x0, y1 - y0
    norm = dx * dx + dy * dy
    img = Image.new("RGB", (small, small))
    px = img.load()
    for y in range(small):
        for x in range(small):
            t = ((x - x0) * dx + (y - y0) * dy) / norm
            px[x, y] = tuple(int(c) for c in _lerp_color(stops, t))
    return img.resize((size, size), Image.BICUBIC).convert("RGBA")


def _vertical_gradient(size, top, bottom, y_from, y_to):
    img = Image.new("RGBA", (size, size))
    draw = ImageDraw.Draw(img)
    for y in range(size):
        t = (y / SCALE - y_from) / (y_to - y_from)
        t = min(max(t, 0.0), 1.0)
        color = tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3))
        draw.line([(0, y), (size, y)], fill=(*color, 255))
    return img


def render(path: Path) -> None:
    s = SCALE
    size = SIZE * s

    def sc(v):
        return v * s

    # Tile (macOS icon grid: 824px rounded square centred in 1024px).
    box = (sc(100), sc(100), sc(924), sc(924))
    tile_mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(tile_mask).rounded_rectangle(box, radius=sc(185), fill=255)

    tile = _diagonal_gradient(size, TILE_STOPS)

    # Soft top highlight and a faint corner bloom, clipped to the tile.
    gloss = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    gd = ImageDraw.Draw(gloss)
    for y in range(sc(100), sc(520)):
        t = (y - sc(100)) / (sc(520) - sc(100))
        gd.line([(0, y), (size, y)], fill=(255, 255, 255, int(255 * 0.28 * (1 - t))))
    bloom = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ImageDraw.Draw(bloom).ellipse(
        (sc(560), sc(630), sc(1160), sc(1230)), fill=(255, 255, 255, int(255 * 0.07))
    )
    tile = Image.alpha_composite(tile, gloss)
    tile = Image.alpha_composite(tile, bloom)

    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    image.paste(tile, (0, 0), tile_mask)

    # Cloak silhouette with the fingerprint ridges knocked out.
    glyph_mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(glyph_mask).polygon([(sc(x), sc(y)) for x, y in _hood_points()], fill=255)

    ridges = Image.new("L", (size, size), 0)
    rd = ImageDraw.Draw(ridges)
    width = sc(28)
    cap = width // 2

    def stroke_line(x, y_top, y_bottom):
        rd.line([(sc(x), sc(y_top)), (sc(x), sc(y_bottom))], fill=255, width=width)
        for y in (y_top, y_bottom):
            rd.ellipse((sc(x) - cap, sc(y) - cap, sc(x) + cap, sc(y) + cap), fill=255)

    def stroke_arch(cx, cy, r, y_bottom):
        # Vertical legs from y_bottom up to cy, joined by a half circle of radius r.
        stroke_line(cx - r, cy, y_bottom)
        stroke_line(cx + r, cy, y_bottom)
        for i in range(361):
            a = math.pi * i / 360
            x, y = sc(cx + r * math.cos(a)), sc(cy - r * math.sin(a))
            rd.ellipse((x - cap, y - cap, x + cap, y + cap), fill=255)

    stroke_line(512, 560, 700)
    stroke_arch(512, 560, 60, 700)
    stroke_arch(512, 550, 120, 700)

    glyph_mask = ImageChops.subtract(glyph_mask, ridges)

    glyph = _vertical_gradient(size, GLYPH_TOP, GLYPH_BOTTOM, 228, 792)
    glyph.putalpha(glyph_mask)

    # Drop shadow under the glyph.
    shadow_alpha = glyph_mask.filter(ImageFilter.GaussianBlur(sc(26)))
    shadow_alpha = shadow_alpha.point(lambda a: int(a * 0.45))
    shadow = Image.new("RGBA", (size, size), (11, 16, 80, 0))
    shadow.putalpha(shadow_alpha)
    shadow = ImageChops.offset(shadow, 0, sc(22))
    image = Image.alpha_composite(image, shadow)
    image = Image.alpha_composite(image, glyph)

    image.resize((SIZE, SIZE), Image.LANCZOS).save(path)


if __name__ == "__main__":
    png = Path(sys.argv[1])
    render(png)
    if len(sys.argv) > 2:
        Image.open(png).save(sys.argv[2], sizes=[(s, s) for s in (16, 24, 32, 48, 64, 128, 256)])
