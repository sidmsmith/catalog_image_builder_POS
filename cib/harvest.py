"""`cib harvest` — turn a scraped product list into manifest.csv + downloads.

The *judgement* half of a harvest (which products, which shot, price/color/
size capture) stays with Claude driving the browser. This module is the
mechanical half: given an input file of per-product rows, it cleans the
names, derives unique local filenames, downloads the images, and writes the
manifest.

Input file (``customers/<c>/harvest_input.csv`` by default, or ``--input``):
CSV or JSON. Only name + url are required; every other POS field below is
optional per row and passed straight through to the manifest (blank if
omitted). See `manifest.COLUMNS` for the full field list — `itemId` is the
one every POS customer needs (it's the real SKU Claude assigns while
curating the row, continuing that retailer's existing numbering), the
jewelry/footwear-only fields just stay blank for the other retailer.

    name | sourceName      product name  (run through clean_source_name)
    sourceUrl | url         direct image URL
    brand, category         optional, as before
    status, notes           optional, as before
    itemId, style, webUrl, shortDescription, description,
    sellingPrice, basePrice, colorName, colorGroup, size, sizeSortSequence,
    colorSortSequence, storeDepartment, productClass, style1, style2,
    adjustQuantity, rating, earringType, metalType, departmentNumber,
    departmentName, vasTypeId, locationId, caLocationId, weight, volume
"""

from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from .config import Config
from .manifest import COLUMNS
from .naming import clean_source_name, slugify

_CAMEL_RE = re.compile(r"(?<!^)(?=[A-Z])")


def _camel_to_snake(s: str) -> str:
    return _CAMEL_RE.sub("_", s).lower()

BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
_IMG_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif"}
_MIME_EXT = {"image/jpeg": ".jpg", "image/jpg": ".jpg", "image/png": ".png",
             "image/webp": ".webp", "image/gif": ".gif", "image/avif": ".avif"}
_NAME_KEYS = ("name", "sourceName", "sourcename", "product", "title")
_URL_KEYS = ("sourceUrl", "sourceurl", "url", "image", "imageUrl", "imageurl", "src")

# Optional POS fields, read straight from the input row by this exact key
# (Claude authors harvest_input.csv with these headers - no fuzzy matching
# needed the way name/url get it, since those two are the only ones likely
# to arrive under a different header from an ad-hoc scrape).
_POS_KEYS = (
    "itemId", "style", "webUrl", "shortDescription", "description",
    "sellingPrice", "basePrice", "colorName", "colorGroup", "size",
    "sizeSortSequence", "colorSortSequence", "storeDepartment", "productClass",
    "style1", "style2", "adjustQuantity", "rating", "earringType", "metalType",
    "departmentNumber", "departmentName", "vasTypeId", "locationId",
    "caLocationId", "weight", "volume",
)


class HarvestError(Exception):
    pass


@dataclass
class Item:
    name: str
    url: str
    brand: str = ""
    category: str = ""
    status: str = ""
    notes: str = ""
    item_id: str = ""
    style: str = ""
    web_url: str = ""
    short_description: str = ""
    description: str = ""
    selling_price: str = ""
    base_price: str = ""
    color_name: str = ""
    color_group: str = ""
    size: str = ""
    size_sort_sequence: str = ""
    color_sort_sequence: str = ""
    store_department: str = ""
    product_class: str = ""
    style1: str = ""
    style2: str = ""
    adjust_quantity: str = ""
    rating: str = ""
    earring_type: str = ""
    metal_type: str = ""
    department_number: str = ""
    department_name: str = ""
    vas_type_id: str = ""
    location_id: str = ""
    ca_location_id: str = ""
    weight: str = ""
    volume: str = ""
    # filled in during run
    local_file: str = ""
    outcome: str = ""   # downloaded | exists | failed | skipped
    detail: str = ""


@dataclass
class HarvestResult:
    items: list[Item] = field(default_factory=list)
    manifest_path: Path | None = None

    def by(self, outcome: str) -> list[Item]:
        return [i for i in self.items if i.outcome == outcome]

    @property
    def ok(self) -> bool:
        return not self.by("failed")


# --------------------------------------------------------------------------- #
# input parsing
# --------------------------------------------------------------------------- #

def _pick(d: dict, keys) -> str:
    for k in keys:
        if d.get(k):
            return str(d[k]).strip()
    return ""


def read_input(path: Path) -> list[Item]:
    if not path.is_file():
        raise HarvestError(
            f"harvest input not found: {path}\n"
            "Scrape the site into a CSV (name,sourceUrl[,brand,category]) first.")
    text = path.read_text(encoding="utf-8-sig")

    records: list[dict]
    if path.suffix.lower() == ".json" or text.lstrip().startswith(("[", "{")):
        data = json.loads(text)
        records = data if isinstance(data, list) else data.get("items", [])
    else:
        records = list(csv.DictReader(text.splitlines()))

    items: list[Item] = []
    for i, rec in enumerate(records, start=1):
        rec = {(k or "").strip(): v for k, v in rec.items()}
        name = _pick(rec, _NAME_KEYS)
        url = _pick(rec, _URL_KEYS)
        if not name and not url:
            continue
        if not name or not url:
            raise HarvestError(f"input row {i}: needs both a name and a URL (got {rec!r})")
        pos_fields = {_camel_to_snake(k): rec.get(k, "").strip() for k in _POS_KEYS}
        items.append(Item(
            name=clean_source_name(name), url=url,
            brand=_pick(rec, ("brand",)), category=_pick(rec, ("category", "cat")),
            status=_pick(rec, ("status",)), notes=_pick(rec, ("notes", "note")),
            **pos_fields,
        ))
    if not items:
        raise HarvestError(f"{path} had no usable rows")
    return items


def _assign_local_files(items: list[Item]) -> None:
    used: set[str] = set()
    for it in items:
        stem = slugify(it.name) or "item"
        cand, n = stem, 1
        while cand.lower() in used:
            n += 1
            cand = f"{stem}_{n}"
        used.add(cand.lower())
        it.local_file = cand  # extension added after download


# --------------------------------------------------------------------------- #
# download
# --------------------------------------------------------------------------- #

def _ext_for(url: str, content_type: str) -> str:
    suf = Path(urlparse(url).path).suffix.lower()
    if suf in _IMG_EXT:
        return ".jpg" if suf == ".jpeg" else suf
    return _MIME_EXT.get((content_type or "").split(";")[0].strip().lower(), ".jpg")


def _download(url: str, dest_stem: Path, width: int | None, timeout: int) -> tuple[str, str]:
    """Fetch `url` to `<dest_stem><ext>`; return (final_filename, detail)."""
    import requests

    u = url
    if width and "?" not in u:
        u = f"{u}?width={width}"
    p = urlparse(u)
    headers = {"User-Agent": BROWSER_UA, "Accept": "image/avif,image/webp,image/*,*/*;q=0.8"}
    if p.scheme and p.netloc:
        headers["Referer"] = f"{p.scheme}://{p.netloc}/"

    r = requests.get(u, headers=headers, timeout=timeout)
    r.raise_for_status()
    if len(r.content) < 1024:
        raise HarvestError(f"suspiciously small response ({len(r.content)} B)")
    ext = _ext_for(url, r.headers.get("content-type", ""))
    final = dest_stem.with_name(dest_stem.name + ext)
    final.write_bytes(r.content)
    return final.name, f"{len(r.content) // 1024} KB"


# --------------------------------------------------------------------------- #
# orchestration
# --------------------------------------------------------------------------- #

def run(cfg: Config,
        input_path: Path | None = None,
        *,
        append: bool = False,
        width: int | None = None,
        force: bool = False,
        dry_run: bool = False,
        timeout: int = 30) -> HarvestResult:
    src = input_path or (cfg.workdir / "harvest_input.csv")
    items = read_input(src)
    _assign_local_files(items)

    existing_files: set[str] = set()
    if append and cfg.manifest_path.is_file():
        from .manifest import read_manifest
        for r in read_manifest(cfg.manifest_path, kept_only=False):
            existing_files.add(Path(r.local_file).stem.lower())

    result = HarvestResult(items=items)
    if dry_run:
        for it in items:
            it.outcome = "skipped"
            it.detail = f"[dry-run] {it.local_file}.<ext>  <-  {it.url}"
        return result

    cfg.images_dir.mkdir(parents=True, exist_ok=True)
    for it in items:
        if append and it.local_file.lower() in existing_files:
            it.outcome, it.detail = "skipped", "already in manifest"
            # still need an extension for the manifest row
            it.local_file += Path(urlparse(it.url).path).suffix.lower() or ".jpg"
            continue
        stem = cfg.images_dir / it.local_file
        prior = next((p for p in cfg.images_dir.glob(it.local_file + ".*")), None)
        if prior and not force:
            it.outcome, it.detail = "exists", prior.name
            it.local_file = prior.name
            continue
        try:
            fname, detail = _download(it.url, stem, width, timeout)
        except Exception as e:  # noqa: BLE001 - per-item, keep going
            it.outcome, it.detail = "failed", str(e)[:160]
        else:
            it.outcome, it.detail, it.local_file = "downloaded", detail, fname

    _write_manifest(cfg, result, append=append)
    return result


def _write_manifest(cfg: Config, result: HarvestResult, *, append: bool) -> None:
    rows = [{
        "sourceName": it.name, "brand": it.brand,
        "sourceUrl": it.url, "localFile": it.local_file, "category": it.category,
        "status": it.status or ("skip" if it.outcome == "failed" else ""),
        "notes": it.notes or (it.detail if it.outcome == "failed" else ""),
        "itemId": it.item_id, "style": it.style, "webUrl": it.web_url,
        "shortDescription": it.short_description, "description": it.description,
        "sellingPrice": it.selling_price, "basePrice": it.base_price,
        "colorName": it.color_name, "colorGroup": it.color_group, "size": it.size,
        "sizeSortSequence": it.size_sort_sequence,
        "colorSortSequence": it.color_sort_sequence,
        "storeDepartment": it.store_department, "productClass": it.product_class,
        "style1": it.style1, "style2": it.style2, "adjustQuantity": it.adjust_quantity,
        "rating": it.rating, "earringType": it.earring_type, "metalType": it.metal_type,
        "departmentNumber": it.department_number, "departmentName": it.department_name,
        "vasTypeId": it.vas_type_id, "locationId": it.location_id,
        "caLocationId": it.ca_location_id, "weight": it.weight, "volume": it.volume,
    } for it in result.items]

    path = cfg.manifest_path
    mode = "a" if (append and path.is_file()) else "w"
    with path.open(mode, newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS)
        if mode == "w":
            w.writeheader()
        w.writerows(rows)
    result.manifest_path = path
