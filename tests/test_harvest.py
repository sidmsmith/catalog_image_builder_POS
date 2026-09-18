"""`cib harvest` tests: input parsing, filename derivation, download orchestration."""

from __future__ import annotations

import json
import types
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from cib import harvest
from cib.harvest import HarvestError
from test_phase1 import make_customer


class _Resp:
    def __init__(self, content=b"x" * 4096, ctype="image/png"):
        self.content = content
        self.headers = {"content-type": ctype}

    def raise_for_status(self):
        pass


def _stub_requests(resp=None, capture=None):
    mod = types.SimpleNamespace()

    def get(url, **kw):
        if capture is not None:
            capture.append((url, kw))
        return resp or _Resp()
    mod.get = get
    return mod


class InputParsingTests(unittest.TestCase):
    def _write(self, p: Path, text: str) -> Path:
        p.write_text(text, encoding="utf-8")
        return p

    def test_csv_with_aliases_and_optional_columns(self):
        with TemporaryDirectory() as d:
            p = self._write(Path(d) / "in.csv",
                            "name,url,brand\n"
                            "Deep Sleep,https://x/ds.png,Red Seal\n"
                            "NikeCourt Lite - Men's,https://x/nc.jpg,\n")
            items = harvest.read_input(p)
            self.assertEqual(items[0].name, "Deep Sleep")
            self.assertEqual(items[0].brand, "Red Seal")
            self.assertEqual(items[1].name, "NikeCourt Lite")   # clean_source_name applied

    def test_json_list(self):
        with TemporaryDirectory() as d:
            p = self._write(Path(d) / "in.json", json.dumps(
                [{"sourceName": "Zinc", "sourceUrl": "https://x/z.png"}]))
            items = harvest.read_input(p)
            self.assertEqual(items[0].name, "Zinc")

    def test_row_missing_url_raises(self):
        with TemporaryDirectory() as d:
            p = self._write(Path(d) / "in.csv", "name,url\nOnly a name,\n")
            with self.assertRaises(HarvestError):
                harvest.read_input(p)


class FilenameTests(unittest.TestCase):
    def test_unique_local_files_for_colliding_names(self):
        items = [harvest.Item("Vitamin C", "u1"), harvest.Item("Vitamin C", "u2"),
                 harvest.Item("Vitamin C", "u3")]
        harvest._assign_local_files(items)
        self.assertEqual([i.local_file for i in items],
                         ["Vitamin_C", "Vitamin_C_2", "Vitamin_C_3"])

    def test_ext_from_url_then_content_type(self):
        self.assertEqual(harvest._ext_for("https://x/a.PNG?w=1", ""), ".png")
        self.assertEqual(harvest._ext_for("https://x/a.jpeg", ""), ".jpg")
        self.assertEqual(harvest._ext_for("https://x/img", "image/webp"), ".webp")
        self.assertEqual(harvest._ext_for("https://x/img", ""), ".jpg")


class RunTests(unittest.TestCase):
    def _cfg(self, tmp):
        cfg = make_customer(tmp, manifest_rows=[])
        # make_customer writes a header-only manifest; harvest overwrites it
        return cfg

    def _input(self, cfg, rows):
        p = cfg.workdir / "harvest_input.csv"
        p.write_text("name,sourceUrl,category,itemId\n"
                     + "\n".join(f"{n},{u},{c},{i}" for n, u, c, i in rows) + "\n", encoding="utf-8")
        return p

    def test_dry_run_writes_nothing(self):
        with TemporaryDirectory() as d:
            tmp = Path(d)
            cfg = self._cfg(tmp)
            self._input(cfg, [("Deep Sleep", "https://x/ds.png", "supplement", "ACME-01")])
            result = harvest.run(cfg, dry_run=True)
            self.assertEqual(result.by("skipped")[0].detail[:9], "[dry-run]")
            self.assertIsNone(result.manifest_path)
            self.assertFalse(any(cfg.images_dir.glob("*")))

    def test_downloads_and_writes_manifest(self):
        import sys
        with TemporaryDirectory() as d:
            tmp = Path(d)
            cfg = self._cfg(tmp)
            self._input(cfg, [("Deep Sleep", "https://x/ds.png", "supplement", "ACME-01"),
                              ("Zinc", "https://x/z", "supplement", "ACME-02")])  # z has no ext
            cap = []
            orig = sys.modules.get("requests")
            sys.modules["requests"] = _stub_requests(capture=cap)
            try:
                result = harvest.run(cfg, width=1400)
            finally:
                if orig is not None:
                    sys.modules["requests"] = orig
                else:
                    sys.modules.pop("requests", None)

            self.assertEqual(len(result.by("downloaded")), 2)
            self.assertTrue((cfg.images_dir / "Deep_Sleep.png").is_file())
            self.assertTrue((cfg.images_dir / "Zinc.png").is_file())      # ext from content-type
            self.assertIn("?width=1400", cap[1][0])                       # width appended to ext-less URL

            from cib.manifest import read_manifest
            rows = read_manifest(cfg.manifest_path)
            self.assertEqual({r.source_name for r in rows}, {"Deep Sleep", "Zinc"})
            self.assertEqual(rows[0].local_file, "Deep_Sleep.png")

    def test_missing_input_file_raises(self):
        with TemporaryDirectory() as d:
            tmp = Path(d)
            cfg = self._cfg(tmp)
            with self.assertRaises(HarvestError):
                harvest.run(cfg)

    def test_append_does_not_duplicate_existing_rows(self):
        # Regression: --append must add only the genuinely new rows. Running
        # it a second time against the same two-item input plus one new item
        # must leave exactly 3 manifest rows, not 5 (the first two rewritten
        # a second time in addition to the new one).
        import sys
        with TemporaryDirectory() as d:
            tmp = Path(d)
            cfg = self._cfg(tmp)
            self._input(cfg, [("Deep Sleep", "https://x/ds.png", "supplement", "ACME-01"),
                              ("Zinc", "https://x/z.png", "supplement", "ACME-02")])
            orig = sys.modules.get("requests")
            sys.modules["requests"] = _stub_requests()
            try:
                harvest.run(cfg)
                self._input(cfg, [("Deep Sleep", "https://x/ds.png", "supplement", "ACME-01"),
                                  ("Zinc", "https://x/z.png", "supplement", "ACME-02"),
                                  ("Iron", "https://x/i.png", "supplement", "ACME-03")])
                harvest.run(cfg, append=True)
            finally:
                if orig is not None:
                    sys.modules["requests"] = orig
                else:
                    sys.modules.pop("requests", None)

            from cib.manifest import read_manifest
            rows = read_manifest(cfg.manifest_path)
            self.assertEqual(len(rows), 3)
            self.assertEqual([r.source_name for r in rows], ["Deep Sleep", "Zinc", "Iron"])


if __name__ == "__main__":
    unittest.main()
