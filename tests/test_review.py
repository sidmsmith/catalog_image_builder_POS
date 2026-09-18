"""Review contact-sheet tests: card staging (processed / raw / none) and HTML."""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from cib import review
from cib.review import ReviewError
from test_phase1 import FIVE, make_customer


def _touch_processed(cfg, stems):
    d = cfg.images_dir / "processed"
    d.mkdir(parents=True, exist_ok=True)
    for s in stems:
        (d / f"{s}.png").write_bytes(b"\x89PNG\r\n\x1a\n")


def _touch_raw(cfg, names):
    cfg.images_dir.mkdir(parents=True, exist_ok=True)
    for n in names:
        (cfg.images_dir / n).write_bytes(b"\xff\xd8\xff")  # jpg magic


class StageTests(unittest.TestCase):
    def test_processed_raw_none_and_skip(self):
        with TemporaryDirectory() as d:
            tmp = Path(d)
            cfg = make_customer(tmp, manifest_rows=FIVE)
            # kept order: Waistcoat, Cardigan, Sling Bag, Court Vision  (Better Sweater = skip)
            _touch_processed(cfg, ["Wool_Fleece_Zip_Waistcoat_v01", "Something_Orphan_v01"])
            _touch_raw(cfg, ["Nor_Short_Cardigan.jpg", "Bain_Sling_Bag.jpg"])
            cards, orphans = review._cards(cfg)

            by = {c.name: c.stage for c in cards}
            self.assertEqual(by["Wool Fleece Zip Waistcoat"], "processed")
            self.assertEqual(by["Nor Short Cardigan"], "raw")
            self.assertEqual(by["Bain Sling Bag"], "raw")
            self.assertEqual(by["Court Vision Low Shoes"], "none")
            self.assertEqual(by["Better Sweater Fleece"], "skip")
            self.assertEqual(orphans, ["Something_Orphan_v01.png"])

    def test_stem_keys_off_localfile_not_display_name(self):
        rows = [
            {"sourceName": "Nor Short Cardigan", "localFile": "skip_me.jpg", "status": "skip"},
            {"sourceName": "Renamed Later", "itemId": "ACME-02",
             "localFile": "Nor_Short_Cardigan.jpg", "status": "keep"},
        ]
        with TemporaryDirectory() as d:
            tmp = Path(d)
            cfg = make_customer(tmp, manifest_rows=rows)
            cards, _ = review._cards(cfg)
            kept = [c for c in cards if c.status == "keep"][0]
            self.assertEqual(kept.stem, "Nor_Short_Cardigan_v01")

    def test_empty_manifest_raises(self):
        with TemporaryDirectory() as d:
            tmp = Path(d)
            cfg = make_customer(tmp, manifest_rows=[])
            with self.assertRaises(ReviewError):
                review.run(cfg, open_browser=False)


class HtmlTests(unittest.TestCase):
    def test_name_review_page_shows_raw_images(self):
        with TemporaryDirectory() as d:
            tmp = Path(d)
            cfg = make_customer(tmp, manifest_rows=FIVE)
            _touch_raw(cfg, ["Wool_Fleece_Zip_Waistcoat.jpg", "Nor_Short_Cardigan.jpg",
                             "Bain_Sling_Bag.jpg", "Court_Vision_Low_Shoes.jpg"])
            page = review.run(cfg, open_browser=False).read_text(encoding="utf-8")
            self.assertIn("<title>Review — Acme</title>", page)
            self.assertIn("name review", page)          # phase label
            self.assertIn("4 raw", page)
            self.assertIn("Wool_Fleece_Zip_Waistcoat.jpg", page)  # raw image src

    def test_image_review_page_shows_processed_and_urls(self):
        with TemporaryDirectory() as d:
            tmp = Path(d)
            cfg = make_customer(tmp, manifest_rows=FIVE)
            _touch_processed(cfg, ["Wool_Fleece_Zip_Waistcoat_v01"])
            page = review.run(cfg, open_browser=False).read_text(encoding="utf-8")
            self.assertIn("image review", page)
            self.assertIn("1 processed", page)
            self.assertIn("3 no-image", page)
            self.assertIn("sidney/Wool_Fleece_Zip_Waistcoat_v01.png", page)


if __name__ == "__main__":
    unittest.main()
