"""Build the POS item CSV.

Unlike the WM-demo model this fork started from (cycle a handful of images
across a flat pool of placeholder ItemIds), a POS CSV row IS a real product
variant: Claude assigns a real itemId while curating harvest_input.csv
(continuing that retailer's own numbering - REEDS-NN, DSW-NN...), so this
stage just projects each kept manifest row through the customer's declared
`csvColumns` - no cycling, no reference-ItemId pool.

Retailers disagree on column set and order (Reeds vs. DSW), so the output
header comes from `config.json`'s `csvColumns` list; whichever manifest
field a column maps to (see FIELD_MAP) is looked up per row, and anything
the row doesn't have (e.g. DSW-only columns on a Reeds row) is written blank.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from .config import Config
from .manifest import ManifestRow, read_manifest
from .naming import StemAllocator

# Output column name -> ManifestRow attribute. Columns not listed here (or
# listed in IMAGE_COLUMNS) are handled separately / written blank.
FIELD_MAP: dict[str, str] = {
    "ItemId": "item_id",
    "Style": "style",
    "WebURL": "web_url",
    "ShortDescription": "short_description",
    "Description": "description",
    "SellingPrice": "selling_price",
    "BasePrice": "base_price",
    "ColorName": "color_name",
    "ColorGroup": "color_group",
    "Size": "size",
    "SizeSortSequence": "size_sort_sequence",
    "ColorSortSequence": "color_sort_sequence",
    "Brand": "brand",
    "StoreDepartment": "store_department",
    "ProductClass": "product_class",
    "Style1": "style1",
    "Style2": "style2",
    "AdjustQuantity": "adjust_quantity",
    "Rating": "rating",
    "EarringType": "earring_type",
    "MetalType": "metal_type",
    "DepartmentNumber": "department_number",
    "DepartmentName": "department_name",
    "VasTypeId": "vas_type_id",
    "LocationId": "location_id",
    "CALocationId": "ca_location_id",
    "Weight": "weight",
    "Volume": "volume",
}

# Every one of these gets the same Cloudinary URL - cib only produces one
# processed shot per manifest row, so "extra angle" slots repeat it.
IMAGE_COLUMNS = {"ImageURI", "ImageURI2", "ImageURI3", "ColorImageURI"}


class BuildError(Exception):
    pass


# --------------------------------------------------------------------------- #
# image URL
# --------------------------------------------------------------------------- #

def image_url(cfg: Config, stem: str) -> str:
    prefix = (cfg.cloudinary.get("urlPrefix") or "").rstrip("/")
    folder = (cfg.cloudinary.get("folder") or "").strip("/")
    ext = (cfg.image_spec.get("format") or "png").lstrip(".")
    parts = [p for p in (prefix, folder, f"{stem}.{ext}") if p]
    return "/".join(parts)


# --------------------------------------------------------------------------- #
# row assembly
# --------------------------------------------------------------------------- #

@dataclass
class BuildResult:
    rows: list[list[str]]
    columns: list[str]
    row_count: int
    duplicate_item_ids: list[str]
    out_path: Path
    published_path: Path | None


def build_output_rows(manifest_rows: list[ManifestRow], cfg: Config) -> list[list[str]]:
    alloc = StemAllocator(cfg.naming["style"], cfg.naming["versionSuffix"])
    out: list[list[str]] = []
    for r in manifest_rows:
        stem = alloc.stem_for_row(r)
        url = image_url(cfg, stem)
        row = []
        for col in cfg.csv_columns:
            if col in IMAGE_COLUMNS:
                row.append(url)
            elif col in FIELD_MAP:
                row.append(getattr(r, FIELD_MAP[col], "") or "")
            else:
                row.append("")
        out.append(row)
    return out


def write_csv(path: Path, columns: list[str], rows: list[list[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(columns)
        writer.writerows(rows)


# --------------------------------------------------------------------------- #
# orchestration
# --------------------------------------------------------------------------- #

def run(cfg: Config, publish: bool = False, dry_run: bool = False,
        timestamp: str | None = None) -> BuildResult:
    from datetime import datetime

    manifest_rows = read_manifest(cfg.manifest_path, kept_only=True)
    if not manifest_rows:
        raise BuildError("Manifest has no kept rows - nothing to put in the CSV.")

    ids = [r.item_id for r in manifest_rows]
    dupes = sorted({x for x in ids if ids.count(x) > 1})
    rows = build_output_rows(manifest_rows, cfg)

    ts = timestamp or datetime.now().strftime("%y%m%d-%H%M")
    stem = Path(cfg.output_csv_name).stem
    out_path = cfg.out_dir / f"{stem}_{ts}.csv"
    published_path: Path | None = None

    if not dry_run:
        write_csv(out_path, cfg.csv_columns, rows)
        cfg.prune_out(f"{stem}_*.csv", keep=5)
        if publish:
            published_path = cfg.require_publish_target()
            write_csv(published_path, cfg.csv_columns, rows)

    return BuildResult(
        rows=rows,
        columns=cfg.csv_columns,
        row_count=len(rows),
        duplicate_item_ids=dupes,
        out_path=out_path,
        published_path=published_path,
    )
