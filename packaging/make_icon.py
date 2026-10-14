"""Render the app icon: a 1024px PNG (macOS .icns via iconutil) and/or a Windows .ico.

    python make_icon.py icon.png [icon.ico]
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

SIZE = 1024


def render(path: Path) -> None:
    scale = 4  # supersample for smooth edges
    size = SIZE * scale
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))

    # macOS icon grid: ~824px rounded square centred in a 1024px canvas.
    inset = 100 * scale
    box = (inset, inset, size - inset, size - inset)
    radius = 185 * scale

    gradient = Image.new("RGBA", (size, size))
    top, bottom = (40, 52, 84), (14, 18, 32)
    draw = ImageDraw.Draw(gradient)
    for y in range(size):
        t = y / (size - 1)
        color = tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3))
        draw.line([(0, y), (size, y)], fill=(*color, 255))
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle(box, radius=radius, fill=255)
    image.paste(gradient, (0, 0), mask)

    # A hooded "cloak" silhouette with a browser window inside it.
    glyph = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    g = ImageDraw.Draw(glyph)
    cx = size // 2
    hood = [
        (cx, 245 * scale),
        (cx + 250 * scale, 400 * scale),
        (cx + 275 * scale, 780 * scale),
        (cx - 275 * scale, 780 * scale),
        (cx - 250 * scale, 400 * scale),
    ]
    g.polygon(hood, fill=(120, 170, 255, 255))
    window = (cx - 165 * scale, 455 * scale, cx + 165 * scale, 690 * scale)
    g.rounded_rectangle(window, radius=28 * scale, fill=(16, 22, 40, 255))
    bar = (window[0], window[1], window[2], window[1] + 52 * scale)
    g.rounded_rectangle(bar, radius=28 * scale, fill=(236, 242, 255, 255))
    g.rectangle((bar[0], bar[1] + 28 * scale, bar[2], bar[3]), fill=(236, 242, 255, 255))
    for i, dot in enumerate(((255, 95, 87), (254, 188, 46), (40, 200, 64))):
        x = window[0] + (38 + i * 38) * scale
        y = window[1] + 26 * scale
        r = 11 * scale
        g.ellipse((x - r, y - r, x + r, y + r), fill=(*dot, 255))

    shadow = glyph.split()[3].filter(ImageFilter.GaussianBlur(18 * scale))
    shadow_layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    shadow_layer.putalpha(shadow.point(lambda a: a * 0.45))
    image = Image.alpha_composite(image, shadow_layer)
    image = Image.alpha_composite(image, glyph)

    image.resize((SIZE, SIZE), Image.LANCZOS).save(path)


if __name__ == "__main__":
    png = Path(sys.argv[1])
    render(png)
    if len(sys.argv) > 2:
        Image.open(png).save(sys.argv[2], sizes=[(s, s) for s in (16, 24, 32, 48, 64, 128, 256)])
