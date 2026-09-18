"""`cib new-customer` — write customers/<name>/config.json + an empty manifest.

Onboarding a POS customer needs a name, the site to harvest from, a base
folder, and the retailer's real CSV column list (order matters — it's their
existing POS import format). Images and output-CSV location are derived from
the base folder. Cloudinary and image-processing spec are copied from an
existing customer (default: reeds) so they stay consistent; csvColumns is
NOT copied from the template since every retailer's schema differs — pass
`--columns` (comma-separated, matching the retailer's own header row) or
fall back to the built-in unified default.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from .config import CUSTOMERS_DIR, ConfigError, load_config
from .manifest import COLUMNS

# Sensible default for a brand-new retailer with no sample CSV to match yet -
# the union of the Reeds/DSW core fields (see manifest.COLUMNS), no
# retailer-specific extras. Prefer `--columns` with the retailer's real
# header whenever a sample CSV exists.
DEFAULT_CSV_COLUMNS = [
    "ItemId", "ShortDescription", "WebURL", "Description", "SellingPrice",
    "BasePrice", "ColorName", "ColorGroup", "Size", "SizeSortSequence",
    "ImageURI", "ImageURI2", "ImageURI3", "Style", "Brand", "StoreDepartment",
    "ProductClass", "Style1", "Style2", "AdjustQuantity", "Rating",
]


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")


def new_customer(name: str,
                 website: str,
                 base_dir: str | None,
                 csv_columns: list[str] | None = None,
                 template: str = "reeds") -> Path:
    slug = _slug(name)
    if not slug:
        raise ConfigError(f"can't make a folder name from {name!r}")
    cust_dir = CUSTOMERS_DIR / slug
    if (cust_dir / "config.json").is_file():
        raise ConfigError(f"customer {slug!r} already exists ({cust_dir / 'config.json'})")

    try:
        tmpl = load_config(template)
    except ConfigError:
        tmpl = None

    display = name.strip()
    if not base_dir:
        raise ConfigError("need --dir")
    base = Path(base_dir)
    if not base.is_dir():
        raise ConfigError(f"--dir does not exist: {base}")
    images = str(base / "images")
    out_dir = str(base)

    cfg = {
        "customer": display,
        "source": website.replace("https://", "").replace("http://", "").strip("/"),
        "outputCsvDir": out_dir,
        "outputCsvName": f"{display.replace(' ', '')}Items.csv",
        "csvColumns": csv_columns or DEFAULT_CSV_COLUMNS,
        "imagesDir": images,
        "cloudinary": (tmpl.cloudinary if tmpl else {
            "cloudName": "com-manh-cp", "folder": "sidney", "preset": "sc_uploads",
            "urlPrefix": "https://res.cloudinary.com/com-manh-cp/image/upload/"}),
        "imageSpec": (tmpl.image_spec if tmpl else {
            "canvas": 600, "fit": "contain", "format": "png", "transparent": True,
            "trim": True, "removeBackground": "rembg",
            "rembgModel": "birefnet-general", "workingResolution": 1600}),
        "naming": (tmpl.naming if tmpl else
                   {"style": "TitleCase_Underscores", "versionSuffix": True}),
    }

    cust_dir.mkdir(parents=True, exist_ok=True)
    (cust_dir / "config.json").write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
    mp = cust_dir / "manifest.csv"
    if not mp.is_file():
        mp.write_text(",".join(COLUMNS) + "\n", encoding="utf-8")
    return cust_dir / "config.json"
