#!/usr/bin/env python3
"""Generate app icons for all platforms from the fleur-de-lis design.

Output:
  build-resources/icon.png   - 1024x1024 master icon (used by electron-builder)
  build-resources/icon.icns  - macOS icon bundle
  build-resources/icon.ico   - Windows icon bundle
  build-resources/icons/     - individual PNGs for Linux

electron-builder uses these automatically via the `directories.buildResources`
config in package.json.
"""

import math
import os
import struct
from PIL import Image, ImageDraw

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BUILD_RES = os.path.join(os.path.dirname(SCRIPT_DIR), "build-resources")
ICONS_DIR = os.path.join(BUILD_RES, "icons")

# Olive green background color (matches the scouting theme)
BG_COLOR = (85, 107, 47)  # classic olive / dark olive green
FG_COLOR = (255, 255, 255)  # white fleur-de-lis

# Icon sizes needed
LINUX_SIZES = [16, 24, 32, 48, 64, 128, 256, 512, 1024]
ICO_SIZES = [16, 24, 32, 48, 64, 128, 256]
ICNS_SIZES = {
    16: b"icp4",   # 16x16
    32: b"icp5",   # 32x32
    64: b"icp6",   # 64x64
    128: b"ic07",  # 128x128
    256: b"ic08",  # 256x256
    512: b"ic09",  # 512x512
    1024: b"ic10", # 1024x1024
}


def draw_fleur_de_lis(img, cx, cy, size):
    """Draw a classic heraldic fleur-de-lis using bezier curves.

    The design follows the traditional fleur-de-lis with:
    - Three upward petals (center tall, sides curling outward)
    - Visible negative space between petals
    - Horizontal band across the waist
    - Tapered base with flared foot
    """
    draw = ImageDraw.Draw(img)
    s = size

    def bezier(p0, p1, p2, p3, steps=40):
        """Cubic bezier curve, returns absolute pixel coords."""
        pts = []
        for i in range(steps + 1):
            t = i / steps
            u = 1 - t
            x = u**3*p0[0] + 3*u**2*t*p1[0] + 3*u*t**2*p2[0] + t**3*p3[0]
            y = u**3*p0[1] + 3*u**2*t*p1[1] + 3*u*t**2*p2[1] + t**3*p3[1]
            pts.append((cx + x * s, cy + y * s))
        return pts

    # ── Center petal (tall, narrow, pointed) ──
    # Right half from tip down to band, then mirror.
    cp_right = []
    cp_right.extend(bezier(
        (0, -0.44),        # tip top
        (0.03, -0.43),     # control
        (0.09, -0.34),     # control: widening
        (0.09, -0.22),     # widest
        steps=20
    ))
    cp_right.extend(bezier(
        (0.09, -0.22),     # widest
        (0.09, -0.10),     # control
        (0.05, -0.01),     # control: narrowing toward waist
        (0.03, 0.06),      # meets band
        steps=20
    ))

    # Assemble center petal: right side + bottom center + left side (mirrored)
    cp_left = [(2 * cx - px, py) for (px, py) in reversed(cp_right)]
    center_petal = cp_right + cp_left
    draw.polygon(center_petal, fill=FG_COLOR)

    # Ball at top of center petal
    tr = s * 0.038
    draw.ellipse([cx - tr, cy - 0.47*s - tr*0.3, cx + tr, cy - 0.47*s + tr*1.7], fill=FG_COLOR)

    # ── Right side petal (curls outward) ──
    # Inner edge: from near the center petal base, curving up and out
    rp_inner = bezier(
        (0.04, 0.05),      # start near center petal
        (0.08, -0.05),     # control: rising
        (0.14, -0.18),     # control: further out
        (0.22, -0.28),     # inner edge near tip
        steps=25
    )
    # Tip curve: arcs outward
    rp_tip = bezier(
        (0.22, -0.28),     # inner edge near tip
        (0.26, -0.34),     # control: up
        (0.34, -0.38),     # control: far out
        (0.38, -0.33),     # outermost point of tip
        steps=20
    )
    # Outer edge: curves back down toward band
    rp_outer = bezier(
        (0.38, -0.33),     # outermost tip
        (0.42, -0.28),     # control: curling back
        (0.42, -0.18),     # control: coming down
        (0.38, -0.08),     # midway down outer edge
        steps=20
    )
    rp_outer2 = bezier(
        (0.38, -0.08),
        (0.34, 0.00),      # control
        (0.28, 0.05),      # control
        (0.22, 0.06),      # meets band area
        steps=15
    )

    right_petal = rp_inner + rp_tip + rp_outer + rp_outer2
    draw.polygon(right_petal, fill=FG_COLOR)

    # Ball at tip of right petal
    br = s * 0.032
    draw.ellipse([cx + 0.38*s - br, cy - 0.36*s - br,
                   cx + 0.38*s + br, cy - 0.36*s + br], fill=FG_COLOR)

    # ── Left side petal (mirror of right) ──
    left_petal = [(2 * cx - px, py) for (px, py) in right_petal]
    draw.polygon(left_petal, fill=FG_COLOR)

    # Ball at tip of left petal
    draw.ellipse([cx - 0.38*s - br, cy - 0.36*s - br,
                   cx - 0.38*s + br, cy - 0.36*s + br], fill=FG_COLOR)

    # ── Horizontal band ──
    band_h = s * 0.048
    band_w = s * 0.28
    band_y = cy + 0.06 * s
    draw.rounded_rectangle(
        [cx - band_w, band_y - band_h, cx + band_w, band_y + band_h],
        radius=band_h * 0.35,
        fill=FG_COLOR,
    )

    # ── Base / stem below band ──
    base_right = []
    base_right.extend(bezier(
        (0.22, 0.11),      # right side of band bottom
        (0.17, 0.12),      # control: inward
        (0.11, 0.16),      # control: narrowing
        (0.08, 0.22),      # narrow waist of stem
        steps=15
    ))
    base_right.extend(bezier(
        (0.08, 0.22),
        (0.06, 0.27),      # control: continues narrowing
        (0.06, 0.32),      # control: starts flaring
        (0.09, 0.36),      # flare begins
        steps=12
    ))
    base_right.extend(bezier(
        (0.09, 0.36),
        (0.11, 0.39),      # control: flare
        (0.13, 0.41),      # control
        (0.15, 0.42),      # bottom-right corner
        steps=10
    ))

    # Bottom edge
    base_right.append((cx + 0.15 * s, cy + 0.42 * s))
    base_right.append((cx, cy + 0.42 * s))

    # Mirror for left half
    base_left = [(2 * cx - px, py) for (px, py) in reversed(base_right)]
    base_outline = base_right + base_left
    draw.polygon(base_outline, fill=FG_COLOR)


def create_master_icon(size=1024):
    """Create the master 1024x1024 icon."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Draw rounded-rectangle background
    margin = size * 0.03
    radius = size * 0.18
    draw.rounded_rectangle(
        [margin, margin, size - margin, size - margin],
        radius=radius,
        fill=BG_COLOR,
    )

    # Draw fleur-de-lis centered
    cx = size / 2
    cy = size / 2 + size * 0.01  # nudge down slightly for visual balance
    symbol_size = size * 0.75

    draw_fleur_de_lis(img, cx, cy, symbol_size)

    return img


def create_ico(master, path, sizes=ICO_SIZES):
    """Save a Windows .ico file with multiple sizes."""
    imgs = []
    for s in sizes:
        resized = master.resize((s, s), Image.LANCZOS)
        imgs.append(resized)
    imgs[0].save(path, format="ICO", sizes=[(s, s) for s in sizes], append_images=imgs[1:])


def create_icns(master, path):
    """Create a macOS .icns file.

    The ICNS format:
    - 4-byte magic: 'icns'
    - 4-byte total file size (big-endian)
    - Sequence of icon entries, each with 4-byte type, 4-byte size, PNG data
    """
    import io

    entries = []
    for size, type_code in sorted(ICNS_SIZES.items()):
        resized = master.resize((size, size), Image.LANCZOS)
        buf = io.BytesIO()
        resized.save(buf, format="PNG")
        png_data = buf.getvalue()
        entry_size = 8 + len(png_data)
        entries.append((type_code, struct.pack(">I", entry_size), png_data))

    total = 8
    for _, size_bytes, png_data in entries:
        total += 8 + len(png_data)

    with open(path, "wb") as f:
        f.write(b"icns")
        f.write(struct.pack(">I", total))
        for type_code, size_bytes, png_data in entries:
            f.write(type_code)
            f.write(size_bytes)
            f.write(png_data)


def main():
    os.makedirs(BUILD_RES, exist_ok=True)
    os.makedirs(ICONS_DIR, exist_ok=True)

    print("Generating master icon (1024x1024)...")
    master = create_master_icon(1024)

    # Save master PNG
    master_path = os.path.join(BUILD_RES, "icon.png")
    master.save(master_path, "PNG")
    print(f"  -> {master_path}")

    # Generate Linux PNGs at standard sizes
    print("Generating Linux PNGs...")
    for size in LINUX_SIZES:
        resized = master.resize((size, size), Image.LANCZOS)
        p = os.path.join(ICONS_DIR, f"{size}x{size}.png")
        resized.save(p, "PNG")
        print(f"  -> {p}")

    # Generate Windows ICO
    print("Generating Windows icon (icon.ico)...")
    ico_path = os.path.join(BUILD_RES, "icon.ico")
    create_ico(master, ico_path)
    print(f"  -> {ico_path}")

    # Generate macOS ICNS
    print("Generating macOS icon (icon.icns)...")
    icns_path = os.path.join(BUILD_RES, "icon.icns")
    create_icns(master, icns_path)
    print(f"  -> {icns_path}")

    print("\nDone! All icons generated in build-resources/")


if __name__ == "__main__":
    main()
