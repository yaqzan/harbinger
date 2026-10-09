"""Render the Harbinger icon (8-bit raven) from its pixel grid.

    py -3.11 ops/icon.py

Writes web/icon.svg (favicon), web/apple-touch-icon.png (180, full bleed: iOS rounds it)
and web/icon-512.png (rounded tile: Pushover app icon, projects page). Edit GRID, rerun.
"""

from pathlib import Path

from PIL import Image, ImageDraw

WEB = Path(__file__).resolve().parent.parent / "web"

TILE = "#b91c1c"
COLORS = {"#": "#131311", "+": "#4a4943", "e": "#fcfcfa"}
GRID = [  # 16x16, one char per pixel: # body, + wing sheen, e eye
    "................",
    "................",
    "..........###...",
    ".........#####..",
    ".........##e####",
    ".........#####..",
    "........#####...",
    "......#######...",
    ".....###++###...",
    "....###+++##....",
    "...###+++###....",
    "..##########....",
    ".###..#..#......",
    "##....#..#......",
    "....########....",
    "................",
]
RADIUS = 3.5  # tile corner radius, in pixels of the 16-grid


def runs():
    """Horizontal runs of one colour: (x, y, length, char)."""
    for y, row in enumerate(GRID):
        x = 0
        while x < len(row):
            ch = row[x]
            end = x
            while end < len(row) and row[end] == ch:
                end += 1
            if ch in COLORS:
                yield x, y, end - x, ch
            x = end


def svg() -> str:
    rects = "".join(f'<rect x="{x}" y="{y}" width="{n}" height="1" fill="{COLORS[c]}"/>'
                    for x, y, n, c in runs())
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" shape-rendering="crispEdges">'
            f'<clipPath id="t"><rect width="16" height="16" rx="{RADIUS}"/></clipPath>'
            f'<rect width="16" height="16" rx="{RADIUS}" fill="{TILE}" shape-rendering="auto"/>'
            f'<g clip-path="url(#t)">{rects}</g></svg>\n')


def png(size: int, rounded: bool) -> Image.Image:
    scale = 8  # supersample for smooth tile corners
    big = size * scale
    img = Image.new("RGBA", (big, big), TILE)
    draw = ImageDraw.Draw(img)
    cell = big / 16
    for x, y, n, c in runs():
        draw.rectangle((round(x * cell), round(y * cell),
                        round((x + n) * cell) - 1, round((y + 1) * cell) - 1), fill=COLORS[c])
    if rounded:  # clip pixels and tile to the rounded corners together
        mask = Image.new("L", (big, big), 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, big - 1, big - 1), radius=RADIUS / 16 * big,
                                               fill=255)
        img.putalpha(mask)
    return img.resize((size, size), Image.LANCZOS)


if __name__ == "__main__":
    (WEB / "icon.svg").write_text(svg(), encoding="utf-8")
    png(180, rounded=False).convert("RGB").save(WEB / "apple-touch-icon.png")
    png(512, rounded=True).save(WEB / "icon-512.png")
    print("wrote icon.svg, apple-touch-icon.png, icon-512.png")
