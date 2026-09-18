"""Turn a product name into a stable image filename stem.

Matches the look of the existing Cloudinary assets (e.g. ``Whole_Wheat_Bread``,
``Almond_Butter_v04``): TitleCase words joined by underscores, optional ``_vNN``.
"""

from __future__ import annotations

import re
from pathlib import Path

_MAX_STEM = 60

# Trailing gender / age-group qualifiers retailers append to a product name.
# We strip these for the CSV display name (the user reviews the result before
# processing); the image filename stem keeps enough to stay unique via _vNN.
_QUALIFIERS = (
    "men", "women", "man", "woman", "mens", "womens", "unisex", "kids", "kid",
    "youth", "junior", "juniors", "boys", "boy", "girls", "girl", "baby",
    "toddler", "big kids", "little kids", "big kid", "little kid", "grade school",
    "preschool", "infant",
)
_QUAL_RE = re.compile(
    r"\s*[-–—]\s*(?:" + "|".join(re.escape(q) for q in sorted(_QUALIFIERS, key=len, reverse=True))
    + r")(?:['’]s)?\s*$",
    re.IGNORECASE,
)


def clean_source_name(name: str) -> str:
    """Drop a trailing ' - Men's' / ' - Unisex' / ' - Big Kids' style qualifier.

    'NikeCourt Lite 4 Tennis Shoes - Men's' -> 'NikeCourt Lite 4 Tennis Shoes'
    Leaves everything else (including bracketed notes like '[Narrow]') intact.
    """
    prev = None
    out = name.strip()
    while out != prev:                       # handle rare doubled qualifiers
        prev = out
        out = _QUAL_RE.sub("", out).strip()
    return out or name.strip()


def slugify(name: str, style: str = "TitleCase_Underscores") -> str:
    # "Men's" -> "Mens" rather than "Men_S"
    cleaned = name.replace("’s", "s").replace("'s", "s")
    words = re.findall(r"[A-Za-z0-9]+", cleaned)
    if not words:
        return "Item"
    if style == "TitleCase_Underscores":
        words = [w[:1].upper() + w[1:] if w[0].isalpha() else w for w in words]
    stem = "_".join(words)
    return stem[:_MAX_STEM].rstrip("_")


class StemAllocator:
    """Hands out unique image-file stems, adding ``_vNN`` on demand / collision.

    The stem is derived from the manifest row's **localFile**, not its
    display name — so editing a product name (e.g. dropping " - Men's") never
    changes which processed PNG / Cloudinary asset a CSV row points at.
    """

    def __init__(self, style: str = "TitleCase_Underscores", version_suffix: bool = True):
        self.style = style
        self.version_suffix = version_suffix
        self._counts: dict[str, int] = {}

    def stem_for(self, basis: str) -> str:
        base = slugify(basis, self.style)
        n = self._counts.get(base, 0) + 1
        self._counts[base] = n
        if self.version_suffix or n > 1:
            return f"{base}_v{n:02d}"
        return base

    def stem_for_row(self, row) -> str:
        """`row` is a ManifestRow — key off its localFile."""
        return self.stem_for(Path(row.local_file).stem)
