"""Render the app icon: a 1024px PNG (macOS .icns via iconutil) and/or a Windows .ico.

    python make_icon.py icon.png [icon.ico]

The mark is packaging/app-logo.png (transparent PNG), centred on a light rounded tile.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter

SIZE = 1024
LOGO = Path(__file__).with_name("app-logo.png")
LOGO_WIDTH = 700  # px in the 1024 canvas; the tile itself is 824 wide


def render(path: Path) -> None:
    scale = 4  # supersample for smooth edges
    size = SIZE * scale

    # macOS icon grid: ~824px rounded square centred in a 1024px canvas.
    inset = 100 * scale
    box = (inset, inset, size - inset, size - inset)
    radius = 185 * scale
    tile_mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(tile_mask).rounded_rectangle(box, radius=radius, fill=255)

    # Soft drop shadow under the tile.
    shadow_alpha = tile_mask.filter(ImageFilter.GaussianBlur(14 * scale)).point(lambda a: int(a * 0.28))
    shadow = Image.new("RGBA", (size, size), (15, 23, 60, 0))
    shadow.putalpha(shadow_alpha)
    image = ImageChops.offset(shadow, 0, 10 * scale)

    # Light vertical gradient: white at the top, faint blue at the bottom.
    gradient = Image.new("RGBA", (size, size))
    top, bottom = (255, 255, 255), (232, 239, 255)
    draw = ImageDraw.Draw(gradient)
    for y in range(size):
        t = min(max((y - inset) / (size - 2 * inset), 0.0), 1.0)
        color = tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3))
        draw.line([(0, y), (size, y)], fill=(*color, 255))
    tile = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    tile.paste(gradient, (0, 0), tile_mask)
    image = Image.alpha_composite(image, tile)

    # Hairline edge so the white tile reads against light backgrounds.
    edge = Image.new("L", (size, size), 0)
    ImageDraw.Draw(edge).rounded_rectangle(box, radius=radius, outline=255, width=2 * scale)
    edge_layer = Image.new("RGBA", (size, size), (120, 140, 190, 0))
    edge_layer.putalpha(edge.point(lambda a: int(a * 0.35)))
    image = Image.alpha_composite(image, edge_layer)

    logo = Image.open(LOGO).convert("RGBA")
    width = LOGO_WIDTH * scale
    logo = logo.resize((width, round(logo.height * width / logo.width)), Image.LANCZOS)
    image.alpha_composite(logo, ((size - logo.width) // 2, (size - logo.height) // 2))

    image.resize((SIZE, SIZE), Image.LANCZOS).save(path)


if __name__ == "__main__":
    png = Path(sys.argv[1])
    render(png)
    if len(sys.argv) > 2:
        Image.open(png).save(sys.argv[2], sizes=[(s, s) for s in (16, 24, 32, 48, 64, 128, 256)])
