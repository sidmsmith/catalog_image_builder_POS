"""Phase 3 tests: upload planning, dry-run, and missing-file handling.

The actual Cloudinary call is not exercised here (needs live creds); it is a
thin wrapper over cloudinary.uploader.upload. Everything up to that point is
covered.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from cib import cloudinary_upload as up
from cib.cloudinary_upload import UploadError
from test_phase1 import FIVE, make_customer


def _with_processed(cfg, stems):
    d = cfg.images_dir / "processed"
    d.mkdir(parents=True, exist_ok=True)
    for s in stems:
        (d / f"{s}.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 64)


class PlanTests(unittest.TestCase):
    def test_plan_matches_csv_stems(self):
        with TemporaryDirectory() as d:
            tmp = Path(d)
            cfg = make_customer(tmp, manifest_rows=FIVE)
            plan = up._plan(cfg, only=None)
            stems = [s for s, _ in plan]
            self.assertEqual(stems, ["Wool_Fleece_Zip_Waistcoat_v01",
                                     "Nor_Short_Cardigan_v01",
                                     "Bain_Sling_Bag_v01",
                                     "Court_Vision_Low_Shoes_v01"])
            self.assertTrue(all(p.name.endswith(".png") for _, p in plan))

    def test_only_filter(self):
        with TemporaryDirectory() as d:
            tmp = Path(d)
            cfg = make_customer(tmp, manifest_rows=FIVE)
            plan = up._plan(cfg, only="sling")
            self.assertEqual([s for s, _ in plan], ["Bain_Sling_Bag_v01"])


class DryRunTests(unittest.TestCase):
    def test_dry_run_lists_deterministic_urls_and_writes_nothing(self):
        with TemporaryDirectory() as d:
            tmp = Path(d)
            cfg = make_customer(tmp, manifest_rows=FIVE)
            _with_processed(cfg, ["Wool_Fleece_Zip_Waistcoat_v01", "Nor_Short_Cardigan_v01",
                                  "Bain_Sling_Bag_v01", "Court_Vision_Low_Shoes_v01"])
            result = up.run(cfg, dry_run=True)
            self.assertEqual(len(result.by("uploaded")), 4)
            self.assertEqual(
                result.outcomes[0].url,
                "https://res.cloudinary.com/com-manh-cp/image/upload/sidney/"
                "Wool_Fleece_Zip_Waistcoat_v01.png")
            self.assertIsNone(result.record_path)  # nothing written on dry-run

    def test_dry_run_flags_missing_processed_file(self):
        with TemporaryDirectory() as d:
            tmp = Path(d)
            cfg = make_customer(tmp, manifest_rows=FIVE)
            _with_processed(cfg, ["Wool_Fleece_Zip_Waistcoat_v01"])  # only 1 of 4
            result = up.run(cfg, dry_run=True)
            self.assertEqual(len(result.by("missing")), 3)
            self.assertFalse(result.ok)


class RealPathTests(unittest.TestCase):
    """Exercise the non-dry-run path with cloudinary stubbed (regression:
    `cloudinary.uploader` must be imported, not just `cloudinary`)."""

    def test_configure_imports_uploader_submodule(self):
        # regression: `import cloudinary` alone does not attach `.uploader`
        import ast
        src = (Path(up.__file__)).read_text(encoding="utf-8")
        cfg_fn = next(n for n in ast.walk(ast.parse(src))
                      if isinstance(n, ast.FunctionDef) and n.name == "_configure")
        imported = {a.name for n in ast.walk(cfg_fn)
                    if isinstance(n, ast.Import) for a in n.names}
        self.assertIn("cloudinary.uploader", imported)

    def test_upload_call_path_reaches_uploader(self):
        import cloudinary
        import cloudinary.uploader

        orig_cfg, orig_up = cloudinary.config, cloudinary.uploader.upload
        cloudinary.config = lambda **k: None
        cloudinary.uploader.upload = lambda f, **k: {
            "secure_url": f"https://res.cloudinary.com/x/{k['public_id']}.png"}
        import os
        os.environ["CLOUDINARY_API_KEY"] = "k"
        os.environ["CLOUDINARY_API_SECRET"] = "s"
        try:
            with TemporaryDirectory() as d:
                tmp = Path(d)
                cfg = make_customer(tmp, manifest_rows=FIVE)
                cfg.cloudinary["cloudName"] = "com-manh-cp"
                _with_processed(cfg, ["Wool_Fleece_Zip_Waistcoat_v01", "Nor_Short_Cardigan_v01",
                                      "Bain_Sling_Bag_v01", "Court_Vision_Low_Shoes_v01"])
                result = up.run(cfg, dry_run=False, verify=False)
                self.assertEqual(len(result.by("uploaded")), 4)
                self.assertTrue(result.record_path.is_file())
        finally:
            cloudinary.config, cloudinary.uploader.upload = orig_cfg, orig_up
            os.environ.pop("CLOUDINARY_API_KEY", None)
            os.environ.pop("CLOUDINARY_API_SECRET", None)


class GuardTests(unittest.TestCase):
    def test_real_run_refuses_when_processed_missing(self):
        with TemporaryDirectory() as d:
            tmp = Path(d)
            cfg = make_customer(tmp, manifest_rows=FIVE)
            with self.assertRaises(UploadError):
                up.run(cfg, dry_run=False)

    def test_empty_plan_raises(self):
        with TemporaryDirectory() as d:
            tmp = Path(d)
            cfg = make_customer(tmp, manifest_rows=FIVE)
            with self.assertRaises(UploadError):
                up.run(cfg, dry_run=True, only="nothing-matches-this")


if __name__ == "__main__":
    unittest.main()
