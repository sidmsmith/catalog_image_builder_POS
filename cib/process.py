"""Background removal + trim + square-canvas resize.

For each kept manifest row: read ``images/<localFile>``, remove the background
(``rembg``), trim to the subject, and center it on a transparent square canvas.
Output goes to ``images/processed/<stem>.png`` where ``<stem>`` is allocated the
same way the ``csv`` stage allocates it, so the two agree.

``rembg`` and ``pillow`` are imported lazily so ``cib csv`` keeps working with
no dependencies installed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .config import Config
from .manifest import read_manifest
from .naming import StemAllocator

# birefnet-general (~1 GB, ~20 s/image at 1600 px) handles white/translucent
# footwear soles that isnet-general-use (~180 MB, ~1 s/image) turns see-through.
# Footwear is half the catalogue, so quality is the default; pass --fast /
# --model isnet-general-use for a quick draft pass.
DEFAULT_MODEL = "birefnet-general"
DEFAULT_WORKING_RES = 1600


class ProcessError(Exception):
    pass


@dataclass
class ItemOutcome:
    source_name: str
    src: Path
    dst: Path
    status: str          # "processed" | "skipped" | "missing" | "failed"
    detail: str = ""


@dataclass
class ProcessResult:
    outcomes: list[ItemOutcome] = field(default_factory=list)

    def by(self, status: str) -> list[ItemOutcome]:
        return [o for o in self.outcomes if o.status == status]

    @property
    def ok(self) -> bool:
        return not self.by("failed") and not self.by("missing")


# --------------------------------------------------------------------------- #
# image ops
# --------------------------------------------------------------------------- #

def _import_deps():
    try:
        from PIL import Image
    except ImportError as e:  # pragma: no cover
        raise ProcessError(
            "Pillow is not installed. Activate the project venv and run "
            "`pip install -r requirements.txt`."
        ) from e
    return Image


def _make_session(model: str):
    try:
        from rembg import new_session
    except ImportError as e:  # pragma: no cover
        raise ProcessError(
            "rembg is not installed. Activate the project venv and run "
            "`pip install -r requirements.txt`."
        ) from e
    return new_session(model)


def remove_background(img, session, alpha_matting: bool):
    from rembg import remove
    return remove(img, session=session, alpha_matting=alpha_matting)


def trim_to_alpha(img, Image):
    """Crop to the bounding box of non-transparent pixels."""
    alpha = img.getchannel("A")
    bbox = alpha.getbbox()
    return img.crop(bbox) if bbox else img


def fit_on_canvas(img, canvas: int, Image):
    """Scale so the longest side == canvas, center on a transparent square."""
    w, h = img.size
    if max(w, h) == 0:
        return img
    scale = canvas / max(w, h)
    new = (max(1, round(w * scale)), max(1, round(h * scale)))
    img = img.resize(new, Image.LANCZOS)
    out = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))
    out.paste(img, ((canvas - new[0]) // 2, (canvas - new[1]) // 2), img)
    return out


def _downscale(img, box: int, Image):
    w, h = img.size
    if not box or max(w, h) <= box:
        return img
    scale = box / max(w, h)
    return img.resize((max(1, round(w * scale)), max(1, round(h * scale))), Image.LANCZOS)


def process_one(src: Path, dst: Path, spec: dict, session, Image) -> str:
    img = Image.open(src).convert("RGBA")
    orig = img.size

    # The final canvas is small; removing the background at full camera
    # resolution just wastes time (and rembg resamples internally anyway).
    img = _downscale(img, int(spec.get("workingResolution", DEFAULT_WORKING_RES)), Image)

    mode = (spec.get("removeBackground") or "rembg").lower()

    # "skip" is the bypass a user can choose at the image-review checkpoint
    # when cropping/transparency isn't worth the time for this batch - the
    # harvested image passes through unchanged (just re-encoded to PNG, and
    # already downscaled above if it was huge). No rembg, no trim, no canvas.
    if mode == "skip":
        dst.parent.mkdir(parents=True, exist_ok=True)
        img.save(dst, "PNG")
        return f"{orig[0]}x{orig[1]} -> passthrough (no background removal) -> {img.size[0]}x{img.size[1]}"

    if mode == "rembg":
        img = remove_background(img, session, bool(spec.get("alphaMatting", False)))
    elif mode == "none":
        pass
    elif mode == "cloudinary":
        raise ProcessError(
            "removeBackground='cloudinary' is not wired up. Use 'rembg' (local) "
            "for now, or 'none' if the source is already transparent."
        )
    else:
        raise ProcessError(f"unknown removeBackground mode: {mode!r}")

    if spec.get("trim", True):
        img = trim_to_alpha(img, Image)
    trimmed = img.size

    canvas = spec.get("canvas")
    if canvas:
        img = fit_on_canvas(img, int(canvas), Image)

    dst.parent.mkdir(parents=True, exist_ok=True)
    img.save(dst, "PNG")
    return f"{orig[0]}x{orig[1]} -> trim {trimmed[0]}x{trimmed[1]} -> {img.size[0]}x{img.size[1]}"


# --------------------------------------------------------------------------- #
# orchestration
# --------------------------------------------------------------------------- #

def run(cfg: Config,
        force: bool = False,
        only: str | None = None,
        limit: int | None = None,
        model: str | None = None) -> ProcessResult:
    rows = read_manifest(cfg.manifest_path, kept_only=True)
    alloc = StemAllocator(cfg.naming["style"], cfg.naming["versionSuffix"])
    plan = [(r, alloc.stem_for_row(r)) for r in rows]

    if only:
        needle = only.lower()
        plan = [(r, s) for r, s in plan
                if needle in r.local_file.lower() or needle in s.lower()]
    if limit:
        plan = plan[:limit]

    processed_dir = cfg.images_dir / "processed"
    spec = cfg.image_spec
    result = ProcessResult()

    session = None
    Image = None

    for row, stem in plan:
        src = cfg.images_dir / row.local_file
        dst = processed_dir / f"{stem}.png"

        if not src.is_file():
            result.outcomes.append(ItemOutcome(row.source_name, src, dst, "missing",
                                               "source image not found"))
            continue
        if dst.is_file() and not force:
            result.outcomes.append(ItemOutcome(row.source_name, src, dst, "skipped",
                                               "already processed (use --force)"))
            continue

        if Image is None:
            Image = _import_deps()
        if session is None and (spec.get("removeBackground") or "rembg").lower() == "rembg":
            session = _make_session(model or spec.get("rembgModel") or DEFAULT_MODEL)

        try:
            detail = process_one(src, dst, spec, session, Image)
        except Exception as e:  # noqa: BLE001 - report per-image, keep going
            result.outcomes.append(ItemOutcome(row.source_name, src, dst, "failed", str(e)))
        else:
            result.outcomes.append(ItemOutcome(row.source_name, src, dst, "processed", detail))

    return result
