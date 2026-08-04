#!/usr/bin/env python3
"""Generate Fusion tab icons: Setup folder, Side disc cutter, Flat vertical cutter.

Run from the repo root:
  python3 scripts/generate_tab_icons.py

Icons are black silhouettes on transparent backgrounds so Fusion can theme them.
Drawn (not photo-based) so they stay legible at 16x16.
"""

from pathlib import Path
import math

from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'LamelloPSystemCNC' / 'resources' / 'tabs'
SIZES = (16, 32, 64)


def save_icon(img: Image.Image, folder: Path) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    for size in SIZES:
        out = img.resize((size, size), Image.Resampling.LANCZOS)
        if size <= 16:
            alpha = out.split()[-1]
            alpha = alpha.filter(ImageFilter.MaxFilter(3))
            out.putalpha(alpha)
        out.save(folder / f'{size}x{size}.png')
        print('wrote', folder / f'{size}x{size}.png')


def _canvas(size=128):
    return Image.new('RGBA', (size, size), (0, 0, 0, 0)), ImageDraw.Draw(Image.new('RGBA', (size, size), (0, 0, 0, 0)))


def make_folder_icon(canvas: int = 128) -> Image.Image:
    img = Image.new('RGBA', (canvas, canvas), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    s = canvas / 64.0

    def xy(x, y):
        return (x * s, y * s)

    # Tab
    d.polygon(
        [xy(8, 14), xy(26, 14), xy(32, 20), xy(56, 20), xy(56, 26), xy(8, 26)],
        fill=(0, 0, 0, 255),
    )
    # Body
    d.rounded_rectangle(
        [8 * s, 24 * s, 56 * s, 52 * s],
        radius=max(2, int(3 * s)),
        fill=(0, 0, 0, 255),
    )
    return img


def make_side_cutter_icon(canvas: int = 128) -> Image.Image:
    """Top-down disc cutter: ring with three gullets + arbor hole."""
    img = Image.new('RGBA', (canvas, canvas), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    cx = cy = canvas / 2
    outer = canvas * 0.42
    inner = canvas * 0.14
    # Outer disc
    d.ellipse([cx - outer, cy - outer, cx + outer, cy + outer], fill=(0, 0, 0, 255))
    # Cut three gullets
    gullet_r = canvas * 0.16
    for angle_deg in (90, 210, 330):
        ang = math.radians(angle_deg)
        gx = cx + math.cos(ang) * (outer * 0.85)
        gy = cy + math.sin(ang) * (outer * 0.85)
        d.ellipse(
            [gx - gullet_r, gy - gullet_r, gx + gullet_r, gy + gullet_r],
            fill=(0, 0, 0, 0),
        )
        # Punch transparency by clearing — draw on mask instead
    # Rebuild with mask for clean holes
    mask = Image.new('L', (canvas, canvas), 0)
    md = ImageDraw.Draw(mask)
    md.ellipse([cx - outer, cy - outer, cx + outer, cy + outer], fill=255)
    for angle_deg in (90, 210, 330):
        ang = math.radians(angle_deg)
        gx = cx + math.cos(ang) * (outer * 0.92)
        gy = cy + math.sin(ang) * (outer * 0.92)
        md.ellipse(
            [gx - gullet_r, gy - gullet_r, gx + gullet_r, gy + gullet_r],
            fill=0,
        )
    md.ellipse([cx - inner, cy - inner, cx + inner, cy + inner], fill=0)
    # Mounting hole ring suggestion
    mid = canvas * 0.22
    md.ellipse([cx - mid, cy - mid, cx + mid, cy + mid], outline=255, width=max(2, canvas // 32))

    out = Image.new('RGBA', (canvas, canvas), (0, 0, 0, 0))
    black = Image.new('RGBA', (canvas, canvas), (0, 0, 0, 255))
    out.paste(black, (0, 0), mask)
    return out


def make_flat_cutter_icon(canvas: int = 128) -> Image.Image:
    """Vertical T-slot / P-System profile cutter silhouette."""
    img = Image.new('RGBA', (canvas, canvas), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    s = canvas / 64.0

    def r(x0, y0, x1, y1):
        d.rectangle([x0 * s, y0 * s, x1 * s, y1 * s], fill=(0, 0, 0, 255))

    # Shank
    r(28, 6, 36, 22)
    # Neck / flutes body
    r(26, 20, 38, 34)
    # Undercut waist (narrower)
    r(29, 32, 35, 40)
    # Wide cutting head (T)
    r(16, 38, 48, 48)
    # Tip
    r(22, 46, 42, 52)
    return img


def main() -> None:
    save_icon(make_folder_icon(128), OUT / 'setup')
    save_icon(make_side_cutter_icon(128), OUT / 'side')
    save_icon(make_flat_cutter_icon(128), OUT / 'flat')
    print('done')


if __name__ == '__main__':
    main()
