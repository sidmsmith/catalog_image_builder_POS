"""Local contact sheet of the harvest — one HTML page for both review checkpoints.

For every kept manifest row it shows, in priority order:
  1. the processed PNG (``images/processed/<stem>.png``) on a transparency
     checkerboard, with the Cloudinary URL the ``csv`` stage will write — the
     *image* review, after ``cib process``; or
  2. the raw download (``images/<localFile>``) on white, tagged "raw" — the
     *name* review, before processing; or
  3. a "no image" flag.

No server; opened with the default browser.
"""

from __future__ import annotations

import html
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .build_csv import image_url
from .config import Config
from .manifest import read_manifest
from .naming import StemAllocator


class ReviewError(Exception):
    pass


@dataclass
class Card:
    stem: str
    name: str
    brand: str
    category: str
    item_id: str
    status: str          # "keep" | "skip"
    line: int
    processed: Path
    raw: Path
    url: str

    @property
    def stage(self) -> str:
        if self.status == "skip":
            return "skip"
        if self.processed.is_file():
            return "processed"
        if self.raw.is_file():
            return "raw"
        return "none"


def _cards(cfg: Config) -> tuple[list[Card], list[str]]:
    all_rows = read_manifest(cfg.manifest_path, kept_only=False)
    processed_dir = cfg.images_dir / "processed"

    # Stems are allocated from KEPT rows only, in file order - exactly as the
    # csv / process / upload stages do it, so the filenames here always match.
    alloc = StemAllocator(cfg.naming["style"], cfg.naming["versionSuffix"])
    kept_stem = {r.line: alloc.stem_for_row(r) for r in all_rows if r.kept}

    cards: list[Card] = []
    for r in all_rows:
        stem = kept_stem.get(r.line, "")
        cards.append(Card(
            stem, r.source_name, r.brand, r.category, r.item_id,
            "keep" if r.kept else "skip", r.line,
            processed_dir / f"{stem}.png" if stem else processed_dir / "-",
            cfg.images_dir / r.local_file if r.local_file else cfg.images_dir / "-",
            image_url(cfg, stem) if stem else "",
        ))

    known = {f"{s}.png" for s in kept_stem.values()}
    orphans = []
    if processed_dir.is_dir():
        orphans = sorted(p.name for p in processed_dir.glob("*.png") if p.name not in known)
    return cards, orphans


_CSS = """
:root { color-scheme: light; }
* { box-sizing: border-box; }
body { margin: 0; font: 14px/1.5 -apple-system, Segoe UI, Roboto, sans-serif;
       background: #f4f4f5; color: #18181b; }
header { padding: 20px 28px; background: #fff; border-bottom: 1px solid #e4e4e7; position: sticky; top: 0; }
h1 { margin: 0 0 4px; font-size: 18px; }
.sub { color: #71717a; font-size: 13px; }
.warn { margin: 14px 28px 0; padding: 12px 16px; border-radius: 8px;
        background: #fef2f2; border: 1px solid #fecaca; color: #991b1b; font-size: 13px; }
.warn ul { margin: 6px 0 0; padding-left: 20px; }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(230px, 1fr));
        gap: 16px; padding: 20px 28px; }
.card { background: #fff; border: 1px solid #e4e4e7; border-radius: 10px; overflow: hidden; }
.card.skip { opacity: .5; }
.card.none { border-color: #fca5a5; }
.thumb { height: 230px; display: flex; align-items: center; justify-content: center; background: #fff; }
.thumb.transparent {
  background-image:
    linear-gradient(45deg, #e4e4e7 25%, transparent 25%),
    linear-gradient(-45deg, #e4e4e7 25%, transparent 25%),
    linear-gradient(45deg, transparent 75%, #e4e4e7 75%),
    linear-gradient(-45deg, transparent 75%, #e4e4e7 75%);
  background-size: 16px 16px; background-position: 0 0, 0 8px, 8px -8px, -8px 0; }
.thumb img { max-width: 100%; max-height: 100%; }
.thumb .none { color: #ef4444; font-size: 12px; font-weight: 600; }
.meta { padding: 10px 12px; }
.name { font-weight: 600; }
.tags { color: #71717a; font-size: 12px; margin-top: 2px; }
.url { margin-top: 6px; font-size: 11px; color: #3f6212; word-break: break-all; }
.badge { display: inline-block; font-size: 11px; padding: 1px 6px; border-radius: 4px;
         background: #e4e4e7; color: #3f3f46; }
.badge.raw { background: #dbeafe; color: #1e40af; }
.badge.skip { background: #fee2e2; color: #991b1b; }
.badge.none { background: #fef08a; color: #713f12; }
"""


def build_html(cfg: Config, cards: list[Card], orphans: list[str]) -> str:
    kept = [c for c in cards if c.status == "keep"]
    n_proc = sum(c.stage == "processed" for c in kept)
    n_raw = sum(c.stage == "raw" for c in kept)
    n_none = sum(c.stage == "none" for c in kept)
    skipped = [c for c in cards if c.status == "skip"]
    phase = "image review" if n_proc else "name review"

    warns = []
    if n_none:
        warns.append("Kept rows with <b>no image on disk</b> (harvest problem): "
                     "<ul>" + "".join(f"<li>{html.escape(c.name)} — line {c.line} "
                                      f"(localFile: {html.escape(c.raw.name)})</li>"
                                      for c in kept if c.stage == "none") + "</ul>")
    if n_raw and n_proc:
        warns.append(f"{n_raw} row(s) still show the <b>raw</b> download — "
                     "run <code>cib process</code> (or re-run it) to finish them.")
    if orphans:
        warns.append("Processed PNGs with no kept manifest row "
                     "(stale — from a removed / now-skipped item; safe to delete): "
                     "<ul>" + "".join(f"<li>{html.escape(o)}</li>" for o in orphans) + "</ul>")

    def card_html(c: Card) -> str:
        st = c.stage
        cls = f"card {st}"
        thumb_cls, url = "thumb", ""
        if st == "skip":
            inner, badge = '<span class="none">skipped</span>', '<span class="badge skip">skip</span>'
        elif st == "none":
            inner, badge = '<span class="none">no image</span>', '<span class="badge none">no image</span>'
        elif st == "raw":
            inner = f'<img src="{html.escape(c.raw.as_uri())}" alt="">'
            badge = '<span class="badge raw">raw</span>'
        else:  # processed
            thumb_cls = "thumb transparent"
            inner = f'<img src="{html.escape(c.processed.as_uri())}" alt="">'
            badge = '<span class="badge">processed</span>'
            url = f'<div class="url">{html.escape(c.url)}</div>'
        tags = " · ".join(t for t in (c.item_id, c.brand, c.category) if t)
        return (f'<div class="{cls}"><div class="{thumb_cls}">{inner}</div>'
                f'<div class="meta"><div class="name">{html.escape(c.name)} {badge}</div>'
                f'<div class="tags">{html.escape(tags)} — line {c.line}</div>{url}</div></div>')

    order = ([c for c in kept if c.stage == "processed"]
             + [c for c in kept if c.stage == "raw"]
             + [c for c in kept if c.stage == "none"]
             + skipped)
    return f"""<!doctype html><html><head><meta charset="utf-8">
<title>Review — {html.escape(cfg.customer)}</title><style>{_CSS}</style></head><body>
<header>
  <h1>{html.escape(cfg.customer)} — {phase}</h1>
  <div class="sub">{n_proc} processed · {n_raw} raw · {n_none} no-image · {len(skipped)} skipped
     · {len(orphans)} orphan · {len(kept)} kept total · generated {datetime.now():%Y-%m-%d %H:%M}</div>
</header>
{"".join(f'<div class="warn">{w}</div>' for w in warns)}
<div class="grid">{"".join(card_html(c) for c in order)}</div>
</body></html>"""


def run(cfg: Config, open_browser: bool = True) -> Path:
    cards, orphans = _cards(cfg)
    if not cards:
        raise ReviewError(f"manifest {cfg.manifest_path} has no rows")

    cfg.out_dir.mkdir(parents=True, exist_ok=True)
    path = cfg.out_dir / "review.html"
    path.write_text(build_html(cfg, cards, orphans), encoding="utf-8")

    if open_browser:
        import webbrowser
        webbrowser.open(path.as_uri())
    return path
