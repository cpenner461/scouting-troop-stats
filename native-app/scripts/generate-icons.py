#!/usr/bin/env python3
"""Generate app icons for all platforms from the fleur-de-lis glyph.

Renders the Unicode fleur-de-lis character (U+269C) from the FreeSerif font
on a Scout-blue rounded-rectangle background.

Output:
  build-resources/icon.png   - 1024x1024 master icon (used by electron-builder)
  build-resources/icon.icns  - macOS icon bundle
  build-resources/icon.ico   - Windows icon bundle
  build-resources/icons/     - individual PNGs for Linux

electron-builder uses these automatically via the `directories.buildResources`
config in package.json.
"""

import io
import os
import struct
from PIL import Image, ImageDraw, ImageFont

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BUILD_RES = os.path.join(os.path.dirname(SCRIPT_DIR), "build-resources")
ICONS_DIR = os.path.join(BUILD_RES, "icons")

# Olive-green background (matches app theme --olive: #4a5e28)
BG_COLOR = (74, 94, 40)
FG_COLOR = (255, 255, 255)  # white fleur-de-lis

# Font that renders a proper heraldic fleur-de-lis for U+269C
FONT_PATH = "/usr/share/fonts/truetype/freefont/FreeSerif.ttf"

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


def create_master_icon(size=1024):
    """Create the master 1024x1024 icon.

    Renders the fleur-de-lis (U+269C) from FreeSerif, centered on a
    Scout-blue rounded-rectangle background.
    """
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

    # Load font and render the fleur-de-lis character
    char = "\u269C"
    font_size = int(size * 0.62)
    font = ImageFont.truetype(FONT_PATH, font_size)

    # Measure the glyph and center it
    bbox = draw.textbbox((0, 0), char, font=font)
    glyph_w = bbox[2] - bbox[0]
    glyph_h = bbox[3] - bbox[1]
    x = (size - glyph_w) / 2 - bbox[0]
    y = (size - glyph_h) / 2 - bbox[1]

    draw.text((x, y), char, font=font, fill=FG_COLOR)

    return img


def create_ico(master, path, sizes=ICO_SIZES):
    """Save a Windows .ico file with multiple sizes."""
    imgs = []
    for s in sizes:
        resized = master.resize((s, s), Image.LANCZOS)
        imgs.append(resized)
    imgs[0].save(
        path, format="ICO", sizes=[(s, s) for s in sizes], append_images=imgs[1:]
    )


def create_icns(master, path):
    """Create a macOS .icns file.

    The ICNS format:
    - 4-byte magic: 'icns'
    - 4-byte total file size (big-endian)
    - Sequence of icon entries, each with 4-byte type, 4-byte size, PNG data
    """
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
