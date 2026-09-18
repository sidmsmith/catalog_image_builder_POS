"""List / clean the product names in a manifest, for the review checkpoint.

After a harvest, the user reviews `sourceName` values before `cib process`
runs (the name becomes ShortDescription / Description in the CSV and can't be
changed later without reprocessing). This module prints them and can apply the
standard "drop the trailing - Men's / - Unisex qualifier" cleanup; finer edits
are made by hand in `manifest.csv`.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass

from .config import Config
from .manifest import COLUMNS, read_manifest
from .naming import StemAllocator, clean_source_name


@dataclass
class NameRow:
    line: int
    current: str
    proposed: str
    stem: str
    collides_with: list[str]


def review(cfg: Config) -> list[NameRow]:
    rows = read_manifest(cfg.manifest_path, kept_only=True)
    proposed = [clean_source_name(r.source_name) for r in rows]

    # collisions on the *proposed* display name (distinct products, same label)
    seen: dict[str, list[int]] = {}
    for i, p in enumerate(proposed):
        seen.setdefault(p.lower(), []).append(i)

    alloc = StemAllocator(cfg.naming["style"], cfg.naming["versionSuffix"])
    stems = [alloc.stem_for_row(r) for r in rows]

    out = []
    for i, r in enumerate(rows):
        group = seen[proposed[i].lower()]
        collides = [rows[j].source_name for j in group if j != i]
        out.append(NameRow(r.line, r.source_name, proposed[i], stems[i], collides))
    return out


def apply_clean(cfg: Config) -> tuple[list[tuple[str, str]], list[str]]:
    """Apply `clean_source_name` to every kept row's sourceName, EXCEPT where
    the cleaned name would collide with another kept row's cleaned name — those
    keep their original (suffix-bearing) name.

    Returns (changed [(old, new)], kept_for_collision [names]).
    """
    path = cfg.manifest_path
    with path.open(newline="", encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))

    kept = [r for r in rows if (r.get("status") or "").strip().lower()
            not in {"skip", "reject", "no", "x"}]
    cleaned = {id(r): clean_source_name(r["sourceName"]) for r in kept}
    counts: dict[str, int] = {}
    for c in cleaned.values():
        counts[c.lower()] = counts.get(c.lower(), 0) + 1

    changed: list[tuple[str, str]] = []
    collided: list[str] = []
    for r in kept:
        new = cleaned[id(r)]
        old = r["sourceName"]
        if new == old:
            continue
        if counts[new.lower()] > 1:
            collided.append(old)
            continue
        r["sourceName"] = new
        changed.append((old, new))

    if changed:
        with path.open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=COLUMNS)
            w.writeheader()
            w.writerows(rows)
    return changed, collided
