"""Phase-post tests: name cleaning, the names review, and new-customer scaffold."""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from cib import config as config_mod
from cib import names, scaffold
from cib.naming import clean_source_name
from test_phase1 import make_customer


class CleanNameTests(unittest.TestCase):
    def test_strips_gender_and_age_qualifiers(self):
        cases = {
            "2002R Shoes - Unisex": "2002R Shoes",
            "NikeCourt Lite 4 Tennis Shoes - Men's": "NikeCourt Lite 4 Tennis Shoes",
            "The Roger Advantage Shoes - Women's": "The Roger Advantage Shoes",
            "Antora Rain Jacket - Big Kids": "Antora Rain Jacket",
            "1960 Logo T-shirt - Men’s": "1960 Logo T-shirt",   # curly apostrophe
            "Boston Soft Footbed Mules [Narrow] - Unisex": "Boston Soft Footbed Mules [Narrow]",
        }
        for raw, want in cases.items():
            self.assertEqual(clean_source_name(raw), want)

    def test_leaves_plain_names_untouched(self):
        for n in ["Classic Clog", "Cloud 6 Shoes", "Waterproof Jacket"]:
            self.assertEqual(clean_source_name(n), n)


FIVE_GENDERED = [
    {"sourceName": "Cloud 6 Shoes - Men's", "itemId": "ACME-01",
     "localFile": "Cloud_6_Shoes_Mens.jpg", "status": "keep"},
    {"sourceName": "Cloud 6 Shoes - Women's", "itemId": "ACME-02",
     "localFile": "Cloud_6_Shoes_Womens.jpg", "status": "keep"},
    {"sourceName": "NikeCourt Lite 4 Tennis Shoes - Men's", "itemId": "ACME-03",
     "localFile": "NikeCourt_Lite_4_Tennis_Shoes_Mens.jpg", "status": "keep"},
]


class NamesReviewTests(unittest.TestCase):
    def test_review_flags_changes_and_collisions(self):
        with TemporaryDirectory() as d:
            tmp = Path(d)
            cfg = make_customer(tmp, manifest_rows=FIVE_GENDERED)
            rows = names.review(cfg)
            self.assertEqual(rows[0].proposed, "Cloud 6 Shoes")
            self.assertEqual(rows[0].collides_with, ["Cloud 6 Shoes - Women's"])
            self.assertEqual(rows[2].collides_with, [])

    def test_apply_clean_keeps_collision_pairs_but_cleans_the_rest(self):
        with TemporaryDirectory() as d:
            tmp = Path(d)
            cfg = make_customer(tmp, manifest_rows=FIVE_GENDERED)
            changed, collided = names.apply_clean(cfg)
            self.assertEqual(len(changed), 1)                       # only NikeCourt
            self.assertEqual(sorted(collided),
                             ["Cloud 6 Shoes - Men's", "Cloud 6 Shoes - Women's"])
            from cib.manifest import read_manifest
            got = [r.source_name for r in read_manifest(cfg.manifest_path)]
            self.assertEqual(got, ["Cloud 6 Shoes - Men's", "Cloud 6 Shoes - Women's",
                                   "NikeCourt Lite 4 Tennis Shoes"])

    def test_editing_a_name_does_not_change_the_image_stem(self):
        from cib.manifest import read_manifest
        from cib.naming import StemAllocator

        def stems(cfg):
            a = StemAllocator()
            return [a.stem_for_row(r) for r in read_manifest(cfg.manifest_path)]

        with TemporaryDirectory() as d:
            tmp = Path(d)
            cfg = make_customer(tmp, manifest_rows=FIVE_GENDERED)
            before = stems(cfg)
            names.apply_clean(cfg)               # renames NikeCourt row
            self.assertEqual(stems(cfg), before)  # stems unchanged - keyed off localFile


class ScaffoldTests(unittest.TestCase):
    def test_new_customer_derives_paths_from_dir(self):
        with TemporaryDirectory() as d:
            tmp = Path(d)
            config_mod.CUSTOMERS_DIR = tmp / "customers"
            config_mod.ROOT = tmp
            scaffold.CUSTOMERS_DIR = config_mod.CUSTOMERS_DIR
            base = tmp / "Sprouts"
            base.mkdir()
            path = scaffold.new_customer(
                "Sprouts Farmers Market", "sprouts.com", str(base), None, template="__none__")
            cfg = json.loads(path.read_text())
            self.assertEqual(cfg["customer"], "Sprouts Farmers Market")
            self.assertEqual(cfg["source"], "sprouts.com")
            self.assertTrue(cfg["imagesDir"].endswith("images"))
            self.assertEqual(cfg["cloudinary"]["folder"], "sidney")
            self.assertEqual(cfg["csvColumns"], scaffold.DEFAULT_CSV_COLUMNS)
            self.assertTrue((path.parent / "manifest.csv").is_file())

    def test_new_customer_derives_columns_from_arg(self):
        with TemporaryDirectory() as d:
            tmp = Path(d)
            config_mod.CUSTOMERS_DIR = tmp / "customers"
            config_mod.ROOT = tmp
            scaffold.CUSTOMERS_DIR = config_mod.CUSTOMERS_DIR
            base = tmp / "Reeds"
            base.mkdir()
            path = scaffold.new_customer(
                "Reeds", "reeds.com", str(base), ["ItemId", "ShortDescription"],
                template="__none__")
            cfg = json.loads(path.read_text())
            self.assertEqual(cfg["csvColumns"], ["ItemId", "ShortDescription"])

    def test_new_customer_rejects_missing_dir(self):
        with TemporaryDirectory() as d:
            tmp = Path(d)
            config_mod.CUSTOMERS_DIR = tmp / "customers"
            scaffold.CUSTOMERS_DIR = config_mod.CUSTOMERS_DIR
            from cib.config import ConfigError
            with self.assertRaises(ConfigError):
                scaffold.new_customer("X", "x.com", str(tmp / "nope"), None, template="__none__")

    def test_new_customer_rejects_duplicate(self):
        with TemporaryDirectory() as d:
            tmp = Path(d)
            config_mod.CUSTOMERS_DIR = tmp / "customers"
            scaffold.CUSTOMERS_DIR = config_mod.CUSTOMERS_DIR
            (config_mod.CUSTOMERS_DIR / "sprouts").mkdir(parents=True)
            (config_mod.CUSTOMERS_DIR / "sprouts" / "config.json").write_text("{}")
            from cib.config import ConfigError
            with self.assertRaises(ConfigError):
                scaffold.new_customer("Sprouts", "sprouts.com", str(tmp), None, template="__none__")


if __name__ == "__main__":
    unittest.main()
