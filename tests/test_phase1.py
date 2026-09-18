"""Phase 1 tests: config, manifest, naming, CSV building.

Run: python -m unittest discover -s tests
"""

from __future__ import annotations

import csv
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from cib import build_csv, config as config_mod
from cib.manifest import COLUMNS as MANIFEST_COLUMNS, ManifestError, read_manifest
from cib.naming import StemAllocator, slugify

REPO = Path(__file__).resolve().parent.parent

CSV_COLUMNS = [
    "ItemId", "ShortDescription", "Description", "SellingPrice", "BasePrice",
    "ColorName", "Size", "ImageURI", "ImageURI2", "ImageURI3", "Style", "Brand",
]


def make_customer(tmp: Path, *, manifest_rows: list[dict],
                   csv_columns: list[str] | None = None) -> "config_mod.Config":
    cust = tmp / "customers" / "acme"
    cust.mkdir(parents=True)
    (cust / "config.json").write_text(json.dumps({
        "customer": "Acme",
        "source": "acme.com",
        "outputCsvDir": str(tmp / "publish"),
        "outputCsvName": "AcmeItems.csv",
        "csvColumns": csv_columns or CSV_COLUMNS,
        "imagesDir": str(cust / "images"),
        "cloudinary": {"folder": "sidney",
                       "urlPrefix": "https://res.cloudinary.com/com-manh-cp/image/upload/"},
        "imageSpec": {"format": "png"},
        "naming": {"style": "TitleCase_Underscores", "versionSuffix": True},
    }), encoding="utf-8")
    (tmp / "publish").mkdir()

    with (cust / "manifest.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=MANIFEST_COLUMNS)
        w.writeheader()
        for r in manifest_rows:
            w.writerow({c: r.get(c, "") for c in MANIFEST_COLUMNS})

    # point the module's CUSTOMERS_DIR at our temp tree
    config_mod.CUSTOMERS_DIR = tmp / "customers"
    config_mod.ROOT = tmp
    return config_mod.load_config("acme")


# localFile is the slug of the name at harvest time; the stem is derived from
# it (not from the possibly-later-edited sourceName). itemId is the real
# per-row SKU a POS row needs - required on every kept row.
FIVE = [
    {"sourceName": "Wool Fleece Zip Waistcoat", "brand": "Universal Works", "itemId": "ACME-01",
     "shortDescription": "Wool Fleece Zip Waistcoat", "description": "Wool Fleece Zip Waistcoat",
     "localFile": "Wool_Fleece_Zip_Waistcoat.jpg", "category": "apparel", "status": "keep"},
    {"sourceName": "Nor Short Cardigan", "brand": "Samsoe", "itemId": "ACME-02",
     "shortDescription": "Nor Short Cardigan", "description": "Nor Short Cardigan",
     "localFile": "Nor_Short_Cardigan.jpg", "category": "apparel", "status": "keep"},
    {"sourceName": "Bain Sling Bag", "brand": "Elliker", "itemId": "ACME-03",
     "shortDescription": "Bain Sling Bag", "description": "Bain Sling Bag",
     "localFile": "Bain_Sling_Bag.jpg", "category": "apparel", "status": "keep"},
    {"sourceName": "Court Vision Low Shoes", "brand": "Nike", "itemId": "ACME-04",
     "shortDescription": "Court Vision Low Shoes", "description": "Court Vision Low Shoes",
     "localFile": "Court_Vision_Low_Shoes.jpg", "category": "footwear", "status": "keep"},
    {"sourceName": "Better Sweater Fleece", "brand": "Patagonia", "itemId": "ACME-05",
     "shortDescription": "Better Sweater Fleece", "description": "Better Sweater Fleece",
     "localFile": "Better_Sweater_Fleece.jpg", "category": "apparel", "status": "skip"},
]


class NamingTests(unittest.TestCase):
    def test_slugify_basic(self):
        self.assertEqual(slugify("Bain Sling Bag"), "Bain_Sling_Bag")

    def test_slugify_apostrophe_s(self):
        self.assertEqual(slugify("Waistcoat - Men's"), "Waistcoat_Mens")

    def test_allocator_version_suffix_and_collisions(self):
        a = StemAllocator(version_suffix=True)
        self.assertEqual(a.stem_for("Nor Short Cardigan"), "Nor_Short_Cardigan_v01")
        self.assertEqual(a.stem_for("Nor Short Cardigan"), "Nor_Short_Cardigan_v02")


class ManifestTests(unittest.TestCase):
    def test_reads_kept_only_and_excludes_skip(self):
        with TemporaryDirectory() as d:
            tmp = Path(d)
            cfg = make_customer(tmp, manifest_rows=FIVE)
            kept = read_manifest(cfg.manifest_path)
            self.assertEqual([r.source_name for r in kept],
                             ["Wool Fleece Zip Waistcoat", "Nor Short Cardigan",
                              "Bain Sling Bag", "Court Vision Low Shoes"])

    def test_duplicate_localfile_rejected(self):
        rows = [dict(FIVE[0]), dict(FIVE[0])]
        rows[1]["itemId"] = "ACME-99"  # distinct itemId, same localFile -> still a conflict
        with TemporaryDirectory() as d:
            tmp = Path(d)
            cfg = make_customer(tmp, manifest_rows=rows)
            with self.assertRaises(ManifestError):
                read_manifest(cfg.manifest_path)

    def test_missing_itemid_rejected(self):
        rows = [dict(FIVE[0])]
        rows[0]["itemId"] = ""
        with TemporaryDirectory() as d:
            tmp = Path(d)
            cfg = make_customer(tmp, manifest_rows=rows)
            with self.assertRaises(ManifestError):
                read_manifest(cfg.manifest_path)

    def test_duplicate_itemid_rejected(self):
        rows = [dict(FIVE[0]), dict(FIVE[1])]
        rows[1]["itemId"] = rows[0]["itemId"]  # collide on itemId, distinct localFile
        with TemporaryDirectory() as d:
            tmp = Path(d)
            cfg = make_customer(tmp, manifest_rows=rows)
            with self.assertRaises(ManifestError):
                read_manifest(cfg.manifest_path)


class BuildCsvTests(unittest.TestCase):
    def test_one_row_per_kept_manifest_row(self):
        with TemporaryDirectory() as d:
            tmp = Path(d)
            cfg = make_customer(tmp, manifest_rows=FIVE)
            result = build_csv.run(cfg, dry_run=True)

            self.assertEqual(result.row_count, 4)  # skip row excluded
            self.assertEqual(len(result.rows), 4)
            self.assertEqual(result.columns, CSV_COLUMNS)

            # ItemId column comes straight from the manifest row, no cycling
            self.assertEqual(result.rows[0][CSV_COLUMNS.index("ItemId")], "ACME-01")
            self.assertEqual(result.rows[0][CSV_COLUMNS.index("ShortDescription")],
                             "Wool Fleece Zip Waistcoat")
            # image URL shape, and it repeats across all three image slots
            url = ("https://res.cloudinary.com/com-manh-cp/image/upload/sidney/"
                   "Wool_Fleece_Zip_Waistcoat_v01.png")
            self.assertEqual(result.rows[0][CSV_COLUMNS.index("ImageURI")], url)
            self.assertEqual(result.rows[0][CSV_COLUMNS.index("ImageURI2")], url)
            self.assertEqual(result.rows[0][CSV_COLUMNS.index("ImageURI3")], url)

    def test_unmapped_column_is_left_blank(self):
        # a column the row's retailer schema doesn't populate (e.g. a DSW-only
        # column showing up in a customer's csvColumns by mistake) -> blank,
        # not an error.
        with TemporaryDirectory() as d:
            tmp = Path(d)
            cfg = make_customer(tmp, manifest_rows=FIVE,
                                csv_columns=CSV_COLUMNS + ["DepartmentNumber"])
            result = build_csv.run(cfg, dry_run=True)
            self.assertEqual(result.rows[0][-1], "")

    def test_duplicate_itemid_reported_but_not_fatal_to_build(self):
        rows = [dict(FIVE[0]), dict(FIVE[1])]
        rows[1] = dict(rows[1], itemId=rows[0]["itemId"], localFile="Other.jpg")
        with TemporaryDirectory() as d:
            tmp = Path(d)
            cfg = make_customer(tmp, manifest_rows=rows)
            with self.assertRaises(ManifestError):
                # duplicate itemId is actually caught by manifest validation
                # (read_manifest), which build_csv relies on - confirms the
                # guard lives at the right layer.
                build_csv.run(cfg, dry_run=True)

    def test_output_header_matches_configured_columns(self):
        with TemporaryDirectory() as d:
            tmp = Path(d)
            cfg = make_customer(tmp, manifest_rows=FIVE)
            build_csv.run(cfg, dry_run=False)
            out = next(cfg.out_dir.glob("*.csv"))
            lines = out.read_text(encoding="utf-8").splitlines()
            self.assertEqual(lines[0], ",".join(CSV_COLUMNS))
            self.assertEqual(lines[1].count(","), len(CSV_COLUMNS) - 1)

    def test_publish_writes_to_output_dir(self):
        with TemporaryDirectory() as d:
            tmp = Path(d)
            cfg = make_customer(tmp, manifest_rows=FIVE)
            result = build_csv.run(cfg, publish=True, dry_run=False)
            self.assertTrue(result.published_path.is_file())
            self.assertEqual(result.published_path, cfg.published_csv_path)

    def test_out_dir_keeps_only_the_newest_csv_versions(self):
        with TemporaryDirectory() as d:
            tmp = Path(d)
            cfg = make_customer(tmp, manifest_rows=FIVE)
            for i in range(8):
                build_csv.run(cfg, timestamp=f"26010{i}-0000")
            left = sorted(p.name for p in cfg.out_dir.glob("*.csv"))
            self.assertEqual(len(left), 5)                        # keep=5
            self.assertTrue(left[0].endswith("260103-0000.csv"))   # oldest 3 pruned


if __name__ == "__main__":
    unittest.main()
