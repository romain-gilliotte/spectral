#!/usr/bin/env python3
"""Add macOS-style window chrome to an animated GIF."""

import sys
from pathlib import Path
from PIL import Image, ImageDraw

TITLE_BAR_H = 36
BORDER = 4
BG = (45, 51, 59)  # #2d333b — GitHub dark "overlay", visible on #0d1117 page bg
DOTS = [
    (255, 95, 87),   # red    #FF5F57
    (254, 188, 46),  # yellow #FEBC2E
    (40, 200, 64),   # green  #28C840
]
DOT_RADIUS = 6
DOT_Y = TITLE_BAR_H // 2
DOT_START_X = 20
DOT_SPACING = 20


def add_chrome(src: Path, dst: Path):
    img = Image.open(src)
    frames: list[Image.Image] = []
    durations: list[int] = []

    w, h = img.size
    new_w = w + 2 * BORDER
    new_h = h + TITLE_BAR_H + BORDER

    # Build the chrome template once
    chrome = Image.new("RGB", (new_w, new_h), BG)
    draw = ImageDraw.Draw(chrome)
    for i, color in enumerate(DOTS):
        cx = BORDER + DOT_START_X + i * DOT_SPACING
        cy = BORDER + DOT_Y
        draw.ellipse(
            [cx - DOT_RADIUS, cy - DOT_RADIUS, cx + DOT_RADIUS, cy + DOT_RADIUS],
            fill=color,
        )

    # Process each frame
    try:
        while True:
            frame = img.convert("RGB")
            canvas = chrome.copy()
            canvas.paste(frame, (BORDER, TITLE_BAR_H))
            frames.append(canvas)
            durations.append(img.info.get("duration", 100))
            img.seek(img.tell() + 1)
    except EOFError:
        pass

    frames[0].save(
        dst,
        save_all=True,
        append_images=frames[1:],
        duration=durations,
        loop=0,
        optimize=False,
    )
    print(f"✓ {dst} ({new_w}x{new_h}, {len(frames)} frames)")


if __name__ == "__main__":
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/tmp/raw.gif")
    dst = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("assets/demo.gif")
    add_chrome(src, dst)
