"""Read / validate customers/<customer>/manifest.csv.

The manifest is written by Claude during a harvest session; the backend only
reads it. See README.md for the column contract.

Columns are a superset of the Reeds and DSW POS item-CSV schemas (minus the
French/CAD columns neither is required to carry going forward). A given
customer's `csvColumns` in config.json picks the subset + order it actually
outputs; unused columns here just stay blank for that customer.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

COLUMNS = [
    # internal / harvest bookkeeping
    "sourceName", "brand", "sourceUrl", "localFile", "category", "status", "notes",
    # core POS fields (present for both Reeds and DSW)
    "itemId", "style", "webUrl", "shortDescription", "description",
    "sellingPrice", "basePrice",
    "colorName", "colorGroup", "size", "sizeSortSequence", "colorSortSequence",
    "storeDepartment", "productClass", "style1", "style2", "adjustQuantity", "rating",
    # Reeds-only (jewelry)
    "earringType", "metalType",
    # DSW-only (footwear / warehouse)
    "departmentNumber", "departmentName", "vasTypeId",
    "locationId", "caLocationId", "weight", "volume",
]

# Rows with these statuses are kept out of every backend stage.
SKIP_STATUSES = {"skip", "reject", "no", "x"}


class ManifestError(Exception):
    pass


@dataclass
class ManifestRow:
    source_name: str
    brand: str
    source_url: str
    local_file: str
    category: str
    status: str
    notes: str
    item_id: str
    style: str
    web_url: str
    short_description: str
    description: str
    selling_price: str
    base_price: str
    color_name: str
    color_group: str
    size: str
    size_sort_sequence: str
    color_sort_sequence: str
    store_department: str
    product_class: str
    style1: str
    style2: str
    adjust_quantity: str
    rating: str
    earring_type: str
    metal_type: str
    department_number: str
    department_name: str
    vas_type_id: str
    location_id: str
    ca_location_id: str
    weight: str
    volume: str
    line: int  # 1-based line in the file, for error messages

    @property
    def kept(self) -> bool:
        return self.status.strip().lower() not in SKIP_STATUSES


def read_manifest(path: Path, kept_only: bool = True) -> list[ManifestRow]:
    if not path.is_file():
        raise ManifestError(
            f"No manifest at {path}. Run a harvest session first "
            f"(ask Claude to harvest into this file)."
        )

    with path.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        header = [h.strip() for h in (reader.fieldnames or [])]
        if header != COLUMNS:
            raise ManifestError(
                f"{path} header mismatch.\n  expected: {COLUMNS}\n  found:    {header}"
            )

        rows: list[ManifestRow] = []
        for i, rec in enumerate(reader, start=2):  # line 1 is the header
            def g(key: str) -> str:
                return (rec.get(key) or "").strip()

            row = ManifestRow(
                source_name=g("sourceName"), brand=g("brand"), source_url=g("sourceUrl"),
                local_file=g("localFile"), category=g("category"), status=g("status"),
                notes=g("notes"), item_id=g("itemId"), style=g("style"), web_url=g("webUrl"),
                short_description=g("shortDescription"), description=g("description"),
                selling_price=g("sellingPrice"), base_price=g("basePrice"),
                color_name=g("colorName"), color_group=g("colorGroup"), size=g("size"),
                size_sort_sequence=g("sizeSortSequence"), color_sort_sequence=g("colorSortSequence"),
                store_department=g("storeDepartment"), product_class=g("productClass"),
                style1=g("style1"), style2=g("style2"), adjust_quantity=g("adjustQuantity"),
                rating=g("rating"), earring_type=g("earringType"), metal_type=g("metalType"),
                department_number=g("departmentNumber"), department_name=g("departmentName"),
                vas_type_id=g("vasTypeId"), location_id=g("locationId"),
                ca_location_id=g("caLocationId"), weight=g("weight"), volume=g("volume"),
                line=i,
            )
            if not any([row.source_name, row.local_file, row.source_url]):
                continue  # blank line
            rows.append(row)

    _validate(rows, path)
    return [r for r in rows if r.kept] if kept_only else rows


def _validate(rows: list[ManifestRow], path: Path) -> None:
    problems: list[str] = []
    seen_files: dict[str, int] = {}
    seen_ids: dict[str, int] = {}

    for r in rows:
        if not r.kept:
            continue
        if not r.source_name:
            problems.append(f"line {r.line}: missing sourceName")
        if not r.item_id:
            problems.append(f"line {r.line}: missing itemId (POS rows need a real SKU)")
        elif r.item_id in seen_ids:
            problems.append(
                f"line {r.line}: itemId {r.item_id!r} also on line {seen_ids[r.item_id]}"
            )
        else:
            seen_ids[r.item_id] = r.line
        if not r.local_file:
            problems.append(f"line {r.line}: missing localFile")
        elif r.local_file in seen_files:
            problems.append(
                f"line {r.line}: localFile {r.local_file!r} also on line "
                f"{seen_files[r.local_file]}"
            )
        else:
            seen_files[r.local_file] = r.line

    if problems:
        raise ManifestError(
            f"{path} has {len(problems)} problem(s):\n  " + "\n  ".join(problems)
        )


def append_rows(path: Path, rows: list[dict]) -> None:
    """Append harvest rows, creating the file with a header if needed.

    Used by the harvest workflow (Claude), not by the CLI stages.
    """
    exists = path.is_file()
    with path.open("a", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS)
        if not exists:
            writer.writeheader()
        for r in rows:
            writer.writerow({c: r.get(c, "") for c in COLUMNS})
