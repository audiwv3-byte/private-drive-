"""Generate and register the transparent version of the approved PD logo."""

import hashlib
from pathlib import Path

from PIL import Image

source = Path("assets/brand/private_drive_logo.webp")
assert hashlib.sha256(source.read_bytes()).hexdigest() == "550d3b75e1a50fc4feb4d34bec1727c7dd0f6a947f94e16295b834abbfbde35f"
image = Image.open(source).convert("RGB")
rgba = image.convert("RGBA")
rgb, px = image.load(), rgba.load()
for y in range(image.height):
    for x in range(image.width):
        red, green, blue = rgb[x, y]
        t = min(1.0, max(0.0, (max(red, green, blue) - 25.0) / 70.0))
        px[x, y] = (red, green, blue, round(255 * t * t * (3 - 2 * t)))
dest = Path("assets/brand/private_drive_logo_transparent.png")
rgba.save(dest, format="PNG", optimize=True)
assert rgba.getpixel((0, 0))[3] == 0
pubspec = Path("pubspec.yaml")
source_text = pubspec.read_text()
marker = "    - assets/brand/private_drive_logo.webp"
assert source_text.count(marker) == 1
pubspec.write_text(source_text.replace(marker,
    marker + "\n" + "    - assets/brand/private_drive_logo_transparent.png"))
assert dest.stat().st_size > 10000
