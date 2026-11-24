#!/usr/bin/env python3
"""Генерирует Windows-иконку из фирменной геометрии (Pillow, только для сборки)."""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "assets"
OUT.mkdir(exist_ok=True)
S = 1024
im = Image.new("RGBA", (S, S), (11, 10, 19, 255))
d = ImageDraw.Draw(im)
for y in range(S):
    t = y / S
    color = (round(36 * (1 - t) + 11 * t), round(32 * (1 - t) + 10 * t), round(59 * (1 - t) + 19 * t), 255)
    d.line((0, y, S, y), fill=color)
mask = Image.new("L", (S, S))
ImageDraw.Draw(mask).rounded_rectangle((16, 16, S - 16, S - 16), radius=232, fill=255)
im.putalpha(mask)
hexagon = [(512, 144), (796, 308), (796, 636), (512, 800), (228, 636), (228, 308)]
d = ImageDraw.Draw(im)
d.polygon(hexagon, fill=(23, 20, 42, 255))
d.line(hexagon + [hexagon[0]], fill=(155, 135, 245, 255), width=12, joint="curve")
points = [(252, 556), (368, 560), (432, 356), (524, 684), (600, 468), (768, 472)]
glow = Image.new("RGBA", (S, S))
gd = ImageDraw.Draw(glow)
gd.line(points, fill=(155, 135, 245, 150), width=58, joint="curve")
glow = glow.filter(ImageFilter.GaussianBlur(28))
im = Image.alpha_composite(im, glow)
d = ImageDraw.Draw(im)
d.line(points[:4], fill=(181, 163, 255, 255), width=36, joint="curve")
d.line(points[3:], fill=(86, 224, 210, 255), width=36, joint="curve")
for x, y in points:
    d.ellipse((x - 18, y - 18, x + 18, y + 18), fill=(181, 163, 255, 255) if x < 524 else (86, 224, 210, 255))
im.resize((512, 512), Image.Resampling.LANCZOS).save(OUT / "icon.png")
im.save(OUT / "icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
print(OUT / "icon.ico")
