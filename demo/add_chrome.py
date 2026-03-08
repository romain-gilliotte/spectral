#!/usr/bin/env python3
"""Add macOS-style window chrome to an animated GIF."""

import sys
from pathlib import Path
from PIL import Image, ImageDraw

TITLE_BAR_H = 36
BORDER = 1
CROP = 4       # trim agg rounded corners from raw GIF
RADIUS = 12    # top corner radius
TITLE_BG = (88, 96, 105)    # #586069
BORDER_BG = (88, 96, 105)
CORNER_BG = (13, 17, 23)    # #0d1117 — GitHub dark page background
DOTS = [
    (255, 95, 87),   # red
    (254, 188, 46),  # yellow
    (40, 200, 64),   # green
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
    cw = w - 2 * CROP
    ch = h - 2 * CROP
    new_w = cw + 2 * BORDER
    new_h = ch + TITLE_BAR_H + BORDER

    # Build chrome template: rounded top corners, square bottom
    chrome = Image.new("RGB", (new_w, new_h), CORNER_BG)
    draw = ImageDraw.Draw(chrome)
    # Full window body (rounded all corners, then squared off at bottom)
    draw.rounded_rectangle([0, 0, new_w - 1, new_h - 1], radius=RADIUS, fill=BORDER_BG)
    draw.rectangle([0, new_h // 2, new_w - 1, new_h - 1], fill=BORDER_BG)
    # Title bar (rounded top, square bottom)
    draw.rounded_rectangle([0, 0, new_w - 1, TITLE_BAR_H - 1], radius=RADIUS, fill=TITLE_BG)
    draw.rectangle([0, RADIUS, new_w - 1, TITLE_BAR_H - 1], fill=TITLE_BG)
    # Traffic lights
    for i, color in enumerate(DOTS):
        cx = BORDER + DOT_START_X + i * DOT_SPACING
        cy = DOT_Y
        draw.ellipse(
            [cx - DOT_RADIUS, cy - DOT_RADIUS, cx + DOT_RADIUS, cy + DOT_RADIUS],
            fill=color,
        )

    # Process each frame
    try:
        while True:
            frame = img.convert("RGB")
            frame = frame.crop((CROP, CROP, w - CROP, h - CROP))
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
