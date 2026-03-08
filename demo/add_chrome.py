#!/usr/bin/env python3
"""Add macOS-style window chrome to an animated GIF."""

from pathlib import Path
import sys

from PIL import Image, ImageDraw

TITLE_BAR_H = 36
BORDER = 1
PADDING = 4    # inner padding between border and content (shell bg color)
CROP = 4       # trim agg rounded corners from raw GIF
RADIUS = 12    # top corner radius
TITLE_BG = (88, 96, 105, 255)
BORDER_BG = (88, 96, 105, 255)
SHELL_BG = (40, 42, 54, 255)   # #282a36
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
    new_w = cw + 2 * (BORDER + PADDING)
    new_h = ch + TITLE_BAR_H + BORDER + 2 * PADDING

    # Build chrome template in RGBA — corners are transparent
    chrome = Image.new("RGBA", (new_w, new_h), TRANSPARENT)
    draw = ImageDraw.Draw(chrome)
    # Full window body (rounded all corners, then squared off at bottom)
    draw.rounded_rectangle([0, 0, new_w - 1, new_h - 1], radius=RADIUS, fill=BORDER_BG)
    draw.rectangle([0, new_h // 2, new_w - 1, new_h - 1], fill=BORDER_BG)
    # Title bar (rounded top, square bottom)
    draw.rounded_rectangle([0, 0, new_w - 1, TITLE_BAR_H - 1], radius=RADIUS, fill=TITLE_BG)
    draw.rectangle([0, RADIUS, new_w - 1, TITLE_BAR_H - 1], fill=TITLE_BG)
    # Shell background padding area
    content_x = BORDER + PADDING
    content_y = TITLE_BAR_H + PADDING
    draw.rectangle(
        [BORDER, TITLE_BAR_H, new_w - 1 - BORDER, new_h - 1 - BORDER],
        fill=SHELL_BG,
    )
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
            canvas.paste(frame, (content_x, content_y))
            # Re-apply alpha mask (paste overwrites alpha in content area, which is fine,
            # but we need corners to stay transparent)
            canvas.putalpha(alpha_mask)
            frames.append(canvas)
            durations.append(img.info.get("duration", 100))
            img.seek(img.tell() + 1)
    except EOFError:
        pass

    # Convert RGBA → P with fixed palette optimized for terminal text AA
    TKEY = (1, 2, 3)

    # Fixed palette: known colors + grey ramps for anti-aliasing
    bg = (40, 42, 54)       # #282a36 shell background
    chrome_rgb = (88, 96, 105)
    # Dracula theme ANSI colors
    fg_colors = {
        "white":   (248, 248, 242),  # default text
        "green":   (80, 250, 123),   # \033[32m
        "yellow":  (241, 250, 140),  # \033[33m
        "cyan":    (139, 233, 253),  # \033[36m
        "magenta": (255, 121, 198),  # \033[35m
    }
    fixed = [
        TKEY,           # idx 0 = transparent
        bg,
        chrome_rgb,
        (255, 95, 87),  # dot red
        (254, 188, 46), # dot yellow
        (40, 200, 64),  # dot green
    ] + list(fg_colors.values())

    # Fill remaining slots with AA ramps from bg to each fg color
    remaining = 256 - len(fixed)
    # 50% for white (most text), rest split among 4 accent colors
    white_steps = remaining // 2
    accent_steps = (remaining - white_steps) // 4

    def lerp_ramp(c0: tuple, c1: tuple, n: int) -> list[tuple]:
        return [
            (
                int(c0[0] + (c1[0] - c0[0]) * (i + 1) / (n + 1)),
                int(c0[1] + (c1[1] - c0[1]) * (i + 1) / (n + 1)),
                int(c0[2] + (c1[2] - c0[2]) * (i + 1) / (n + 1)),
            )
            for i in range(n)
        ]

    palette_colors = list(fixed)
    palette_colors += lerp_ramp(bg, fg_colors["white"], white_steps)
    for name in ["green", "yellow", "cyan", "magenta"]:
        palette_colors += lerp_ramp(bg, fg_colors[name], accent_steps)

    # Pad to 256
    while len(palette_colors) < 256:
        palette_colors.append((0, 0, 0))

    # Build PIL palette image
    flat_palette = []
    for r, g, b in palette_colors[:256]:
        flat_palette.extend((r, g, b))
    palette_img = Image.new("P", (1, 1))
    palette_img.putpalette(flat_palette)

    rgb_frames = []
    for f in frames:
        rgb = Image.new("RGB", f.size, TKEY)
        rgb.paste(f, mask=f.split()[3])
        rgb_frames.append(rgb)

    p_frames = []
    for rgb in rgb_frames:
        p = rgb.quantize(palette=palette_img, dither=0)
        p_frames.append(p)

    trans_idx = 0  # TKEY is first in palette

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
