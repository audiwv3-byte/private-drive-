"""Prepare the approved bright PRIVATE DRIVE Android launch background.

Only modifies the generated, isolated Flutter scaffold under private_drive_build.
It never edits the production app, payments, backend, or source artwork.
"""
from pathlib import Path
from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parents[2]
BRAND = ROOT / "flutter_app/assets/brand"
ANDROID = ROOT / "private_drive_build/android/app/src/main"
assert ANDROID.joinpath("AndroidManifest.xml").exists(), "isolated Android scaffold missing"
logo_path = BRAND / "private_drive_gold_square_transparent.webp"
background_path = BRAND / "private_drive_vilnius_bright.webp"
assert logo_path.is_file() and background_path.is_file()

with Image.open(logo_path) as logo_image, Image.open(background_path) as city_image:
    logo = logo_image.convert("RGBA")
    assert logo.getextrema()[3][0] == 0, "logo must contain transparency"
    city = ImageOps.fit(city_image.convert("RGB"), (720, 1280),
                        method=Image.Resampling.LANCZOS)
    # Darken only enough to keep launch art crisp on bright screens.
    surface = city.convert("RGBA")
    logo.thumbnail((332, 332), Image.Resampling.LANCZOS)
    surface.alpha_composite(logo, ((720 - logo.width) // 2, 115))
    drawable = ANDROID / "res/drawable-nodpi"
    drawable.mkdir(parents=True, exist_ok=True)
    surface.convert("RGB").save(drawable / "private_drive_launch.webp",
                                format="WEBP", quality=86, method=6)
    (drawable / "private_drive_logo.webp").write_bytes(logo_path.read_bytes())

xml = """<?xml version="1.0" encoding="utf-8"?>
<layer-list xmlns:android="http://schemas.android.com/apk/res/android">
    <item>
        <bitmap android:gravity="fill" android:src="@drawable/private_drive_launch" />
    </item>
</layer-list>
"""
for folder in ("drawable", "drawable-v21"):
    target = ANDROID / "res" / folder
    target.mkdir(parents=True, exist_ok=True)
    (target / "launch_background.xml").write_text(xml, encoding="utf-8")
print("PRIVATE DRIVE native launch: bright Vilnius backdrop and transparent PD logo")
