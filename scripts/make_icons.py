"""
Regenerate assets/portlens.ico and assets/portlens_logo.png from assets/mark.png.

The icon follows the same recipe as Network Resetter's: transparent background,
mark centred with 24/256 padding, sizes 256, 128, 64, 48, 32 and 16.

Run from the repository root:  python scripts/make_icons.py
"""

import os

from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(ROOT, "assets")
ICON_SIZES = [256, 128, 64, 48, 32, 16]
ICON_FILL = 208 / 256   # mark fills 208 of 256 px (24 px padding)
LOGO_SIZE = 1024
LOGO_FILL = 0.805


def framed(mark, size, fill):
    """Transparent square canvas with the mark centred, fitting fill * size."""
    box = round(size * fill)
    scale = box / max(mark.size)
    width, height = max(1, round(mark.width * scale)), max(1, round(mark.height * scale))
    art = mark.resize((width, height), Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    canvas.paste(art, ((size - width) // 2, (size - height) // 2), art)
    return canvas


def main():
    mark = Image.open(os.path.join(ASSETS, "mark.png")).convert("RGBA")
    mark = mark.crop(mark.getbbox())  # exact artwork, no padding

    framed(mark, LOGO_SIZE, LOGO_FILL).save(
        os.path.join(ASSETS, "portlens_logo.png"), optimize=True)

    # Render each size from the source so small sizes stay crisp.
    frames = [framed(mark, size, ICON_FILL) for size in ICON_SIZES]
    frames[0].save(os.path.join(ASSETS, "portlens.ico"), format="ICO",
                   sizes=[(size, size) for size in ICON_SIZES],
                   append_images=frames[1:])
    print("Wrote assets/portlens.ico and assets/portlens_logo.png")


if __name__ == "__main__":
    main()
