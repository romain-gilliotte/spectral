#!/usr/bin/env python3
"""Add macOS-style window chrome to an animated GIF."""

from pathlib import Path
import sys

from PIL import Image, ImageDraw

TITLE_BAR_H = 36
BORDER = 1
CROP = 4       # trim agg rounded corners from raw GIF
RADIUS = 12    # top corner radius
TITLE_BG = (88, 96, 105, 255)
BORDER_BG = (88, 96, 105, 255)
TRANSPARENT = (0, 0, 0, 0)
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

    # Build chrome template in RGBA — corners are transparent
    chrome = Image.new("RGBA", (new_w, new_h), TRANSPARENT)
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
            fill=(*color, 255),
        )

    # Extract alpha mask from chrome (same for every frame)
    alpha_mask = chrome.split()[3]

    # Process each frame
    try:
        while True:
            frame = img.convert("RGB")
            frame = frame.crop((CROP, CROP, w - CROP, h - CROP))
            canvas = chrome.copy()
            canvas.paste(frame, (BORDER, TITLE_BAR_H))
            # Re-apply alpha mask (paste overwrites alpha in content area, which is fine,
            # but we need corners to stay transparent)
            canvas.putalpha(alpha_mask)
            frames.append(canvas)
            durations.append(img.info.get("duration", 100))
            img.seek(img.tell() + 1)
    except EOFError:
        pass

    # Convert RGBA → P with transparency
    # Use a rare RGB color as transparency key, then quantize as RGB
    TKEY = (1, 2, 3)
    rgb_frames = []
    for f in frames:
        rgb = Image.new("RGB", f.size, TKEY)
        rgb.paste(f, mask=f.split()[3])  # paste only opaque pixels
        rgb_frames.append(rgb)

    # Build shared palette from first frame
    palette_img = rgb_frames[0].quantize(colors=255, method=Image.Quantize.MEDIANCUT)

    p_frames = []
    for rgb in rgb_frames:
        p = rgb.quantize(palette=palette_img, dither=0)
        p_frames.append(p)

    # Find transparent palette index (the one mapping to TKEY)
    trans_idx = p_frames[0].getpixel((0, 0))

    p_frames[0].save(
        dst,
        save_all=True,
        append_images=p_frames[1:],
        duration=durations,
        loop=0,
        optimize=True,
        disposal=2,
        transparency=trans_idx,
    )
    print(f"✓ {dst} ({new_w}x{new_h}, {len(frames)} frames)")


if __name__ == "__main__":
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/tmp/raw.gif")
    dst = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("assets/demo.gif")
    add_chrome(src, dst)
