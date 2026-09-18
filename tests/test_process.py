"""Phase 2 tests: the pure image ops in cib.process.

Background removal itself (rembg) is not unit-tested here - it is a large model
dependency and was validated by eye on real Altitude images (see PLAN.md).
These cover trim / canvas / downscale, which is where the framing bugs live.

Run with the project venv:  .venv\\Scripts\\python -m unittest discover -s tests
"""

from __future__ import annotations

import unittest

try:
    from PIL import Image
    HAVE_PIL = True
except ImportError:
    HAVE_PIL = False


@unittest.skipUnless(HAVE_PIL, "Pillow not installed (use the project venv)")
class ImageOpsTests(unittest.TestCase):
    def setUp(self):
        from cib import process
        self.process = process

    def _canvas_with_box(self, size, box):
        """Transparent `size` image with an opaque red rectangle at `box`."""
        im = Image.new("RGBA", size, (0, 0, 0, 0))
        x0, y0, x1, y1 = box
        for x in range(x0, x1):
            for y in range(y0, y1):
                im.putpixel((x, y), (255, 0, 0, 255))
        return im

    def test_trim_to_alpha_crops_to_subject(self):
        im = self._canvas_with_box((100, 100), (20, 30, 60, 90))
        out = self.process.trim_to_alpha(im, Image)
        self.assertEqual(out.size, (40, 60))

    def test_trim_to_alpha_noop_when_fully_transparent(self):
        im = Image.new("RGBA", (50, 50), (0, 0, 0, 0))
        out = self.process.trim_to_alpha(im, Image)
        self.assertEqual(out.size, (50, 50))

    def test_fit_on_canvas_centers_and_squares(self):
        im = Image.new("RGBA", (200, 100), (0, 128, 255, 255))  # landscape
        out = self.process.fit_on_canvas(im, 600, Image)
        self.assertEqual(out.size, (600, 600))
        # longest side scaled to canvas
        self.assertEqual(out.getchannel("A").getbbox(), (0, 150, 600, 450))

    def test_fit_on_canvas_portrait(self):
        im = Image.new("RGBA", (100, 200), (0, 128, 255, 255))
        out = self.process.fit_on_canvas(im, 600, Image)
        self.assertEqual(out.getchannel("A").getbbox(), (150, 0, 450, 600))

    def test_downscale_only_shrinks(self):
        big = Image.new("RGBA", (4000, 2000))
        small = Image.new("RGBA", (300, 200))
        self.assertEqual(self.process._downscale(big, 1600, Image).size, (1600, 800))
        self.assertEqual(self.process._downscale(small, 1600, Image).size, (300, 200))


class ModelDefaultTests(unittest.TestCase):
    def test_default_model_is_quality(self):
        from cib.process import DEFAULT_MODEL
        self.assertEqual(DEFAULT_MODEL, "birefnet-general")


if __name__ == "__main__":
    unittest.main()
