#!/usr/bin/env python3
"""Generate the DMG background image for the Scouting Stats installer.

Creates a retina (2x) background with rolling hills, a scouting-green color
scheme, and a white arrow pointing from the app icon position to the
Applications folder position.

Usage:
    python3 scripts/generate-dmg-background.py

Output:
    build/dmg-background.png       (660x400 @1x)
    build/dmg-background@2x.png    (1320x800 @2x, used by create-dmg)
"""

import math
import os

from PIL import Image, ImageDraw


# DMG window dimensions (logical points)
WIDTH = 660
HEIGHT = 400

# We generate at 2x for retina
SCALE = 2
W = WIDTH * SCALE
H = HEIGHT * SCALE


def lerp_color(c1, c2, t):
    """Linearly interpolate between two RGB tuples."""
    return tuple(int(a + (b - a) * t) for a, b in zip(c1, c2))


def draw_gradient(draw, w, h, top_color, bottom_color):
    """Draw a vertical gradient."""
    for y in range(h):
        t = y / h
        color = lerp_color(top_color, bottom_color, t)
        draw.line([(0, y), (w, y)], fill=color)


def draw_hills(draw, w, h):
    """Draw layered rolling hills in the lower portion."""
    hill_layers = [
        # (y_base, amplitude, period_px, phase, color)
        (h * 0.62, 45 * SCALE, w * 1.2,  0.0,  (72, 95, 58)),   # distant
        (h * 0.72, 40 * SCALE, w * 0.9,  2.0,  (64, 85, 52)),   # mid
        (h * 0.82, 30 * SCALE, w * 0.7,  4.5,  (56, 75, 46)),   # near
        (h * 0.92, 20 * SCALE, w * 0.55, 1.2,  (48, 66, 40)),   # foreground
    ]

    for y_base, amp, period, phase, color in hill_layers:
        points = []
        for x in range(w + 1):
            # Gentle sine wave with a subtle harmonic for natural feel
            y = y_base - amp * math.sin(2 * math.pi * x / period + phase)
            y -= amp * 0.3 * math.sin(2 * math.pi * x / (period * 0.4) + phase * 2.1)
            points.append((x, y))
        # Close polygon at bottom
        points.append((w, h))
        points.append((0, h))
        draw.polygon(points, fill=color)


def draw_arrow(draw, w, h):
    """Draw a clean white arrow in the center of the image."""
    cx = w // 2
    cy = int(h * 0.46)

    shaft_len = 90 * SCALE
    shaft_thickness = 4 * SCALE
    head_len = 24 * SCALE
    head_half_w = 16 * SCALE

    arrow_color = (255, 255, 255, 220)

    # Shaft
    x_start = cx - shaft_len // 2
    x_end = cx + shaft_len // 2 - head_len
    draw.rectangle(
        [x_start, cy - shaft_thickness, x_end, cy + shaft_thickness],
        fill=arrow_color,
    )

    # Arrowhead (triangle)
    tip_x = cx + shaft_len // 2
    base_x = tip_x - head_len
    draw.polygon(
        [
            (tip_x, cy),
            (base_x, cy - head_half_w),
            (base_x, cy + head_half_w),
        ],
        fill=arrow_color,
    )


def draw_clouds(draw, w, h):
    """Draw subtle cloud shapes."""
    cloud_color = (255, 255, 255, 15)

    clouds = [
        (w * 0.12, h * 0.15, 80 * SCALE),
        (w * 0.55, h * 0.08, 60 * SCALE),
        (w * 0.85, h * 0.18, 70 * SCALE),
    ]

    for cx, cy, size in clouds:
        cx, cy, size = int(cx), int(cy), int(size)
        for i, (dx, dy, r) in enumerate([
            (0, 0, size),
            (-size * 0.6, size * 0.1, size * 0.7),
            (size * 0.5, size * 0.15, size * 0.6),
            (-size * 0.2, -size * 0.3, size * 0.5),
            (size * 0.25, -size * 0.2, size * 0.55),
        ]):
            dx, dy, r = int(dx), int(dy), int(r)
            draw.ellipse(
                [cx + dx - r, cy + dy - r, cx + dx + r, cy + dy + r],
                fill=cloud_color,
            )


def main():
    # Create RGBA image
    img = Image.new("RGBA", (W, H))
    draw = ImageDraw.Draw(img)

    # Background gradient - olive/forest green
    top_color = (55, 78, 48)
    bottom_color = (42, 62, 38)
    draw_gradient(draw, W, H, top_color, bottom_color)

    # Subtle clouds
    cloud_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    cloud_draw = ImageDraw.Draw(cloud_layer)
    draw_clouds(cloud_draw, W, H)
    img = Image.alpha_composite(img, cloud_layer)

    # Rolling hills
    draw = ImageDraw.Draw(img)
    draw_hills(draw, W, H)

    # Arrow
    arrow_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    arrow_draw = ImageDraw.Draw(arrow_layer)
    draw_arrow(arrow_draw, W, H)
    img = Image.alpha_composite(img, arrow_layer)

    # Flatten to RGB
    final = Image.new("RGB", (W, H), (0, 0, 0))
    final.paste(img, mask=img.split()[3])

    # Save
    os.makedirs("build", exist_ok=True)
    final.save("build/dmg-background@2x.png", "PNG")

    # Also save 1x version
    final_1x = final.resize((WIDTH, HEIGHT), Image.LANCZOS)
    final_1x.save("build/dmg-background.png", "PNG")

    print(f"Generated build/dmg-background.png ({WIDTH}x{HEIGHT})")
    print(f"Generated build/dmg-background@2x.png ({W}x{H})")


if __name__ == "__main__":
    main()
