"""Upload processed PNGs to Cloudinary.

Each ``images/processed/<stem>.png`` is uploaded with ``public_id = <stem>`` in
the configured folder, ``overwrite=True`` + ``invalidate=True`` (so re-runs
replace the asset and bust the CDN cache). The delivery URL the ``csv`` stage
writes is built deterministically from folder + stem, so after a successful
upload that URL resolves; this stage verifies it.

``cloudinary`` and ``requests`` are imported lazily so the offline stages stay
dependency-free.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .build_csv import image_url
from .config import Config
from .manifest import read_manifest
from .naming import StemAllocator

DEFAULT_PRESET = "sc_uploads"


class UploadError(Exception):
    pass


@dataclass
class UploadOutcome:
    stem: str
    src: Path
    status: str            # uploaded | missing | failed | verified | unverified
    url: str = ""
    detail: str = ""


@dataclass
class UploadResult:
    outcomes: list[UploadOutcome] = field(default_factory=list)
    record_path: Path | None = None

    def by(self, status: str) -> list[UploadOutcome]:
        return [o for o in self.outcomes if o.status == status]

    @property
    def ok(self) -> bool:
        return not self.by("missing") and not self.by("failed")


# --------------------------------------------------------------------------- #
# planning
# --------------------------------------------------------------------------- #

def _plan(cfg: Config, only: str | None) -> list[tuple[str, Path]]:
    """[(stem, processed_png_path)] for kept manifest rows, in file order."""
    rows = read_manifest(cfg.manifest_path, kept_only=True)
    alloc = StemAllocator(cfg.naming["style"], cfg.naming["versionSuffix"])
    processed = cfg.images_dir / "processed"
    plan = [(alloc.stem_for_row(r), processed) for r in rows]
    plan = [(stem, d / f"{stem}.png") for stem, d in plan]
    if only:
        needle = only.lower()
        plan = [(s, p) for s, p in plan if needle in s.lower()]
    return plan


# --------------------------------------------------------------------------- #
# cloudinary + verification
# --------------------------------------------------------------------------- #

def _configure(cfg: Config):
    import cloudinary
    import cloudinary.api  # noqa: F401  - registers the submodules on `cloudinary`
    import cloudinary.uploader  # noqa: F401

    cloud = cfg.cloudinary.get("cloudName")
    if not cloud:
        raise UploadError("config cloudinary.cloudName is not set")
    cloudinary.config(
        cloud_name=cloud,
        api_key=cfg.secret("CLOUDINARY_API_KEY"),
        api_secret=cfg.secret("CLOUDINARY_API_SECRET"),
        secure=True,
    )
    return cloudinary


def _upload_one(cloudinary, src: Path, folder: str, stem: str, preset: str | None):
    opts = dict(public_id=stem, folder=folder, overwrite=True, invalidate=True,
                resource_type="image")
    if preset:
        opts["upload_preset"] = preset
    res = cloudinary.uploader.upload(str(src), **opts)
    return res.get("secure_url") or res.get("url", "")


def _verify(url: str, timeout: int = 20) -> tuple[bool, str]:
    import requests
    try:
        r = requests.head(url, timeout=timeout, allow_redirects=True)
        if r.status_code == 200:
            return True, ""
        # some CDNs don't answer HEAD; retry GET
        r = requests.get(url, timeout=timeout, stream=True)
        return (r.status_code == 200), f"HTTP {r.status_code}"
    except Exception as e:  # noqa: BLE001
        return False, str(e)


# --------------------------------------------------------------------------- #
# orchestration
# --------------------------------------------------------------------------- #

def run(cfg: Config,
        dry_run: bool = False,
        only: str | None = None,
        verify: bool = True) -> UploadResult:
    plan = _plan(cfg, only)
    if not plan:
        raise UploadError("no processed images to upload - run `cib process` first")

    folder = (cfg.cloudinary.get("folder") or "").strip("/")
    preset = cfg.cloudinary.get("preset") or DEFAULT_PRESET
    result = UploadResult()

    missing = [p for _, p in plan if not p.is_file()]
    for stem, src in plan:
        if not src.is_file():
            result.outcomes.append(UploadOutcome(stem, src, "missing",
                                                 detail="processed PNG not found"))

    if dry_run:
        for stem, src in plan:
            if src.is_file():
                kb = src.stat().st_size / 1024
                result.outcomes.append(UploadOutcome(
                    stem, src, "uploaded", url=image_url(cfg, stem),
                    detail=f"[dry-run] {kb:.0f} KB -> {folder}/{stem} (preset {preset})"))
        return result

    if missing:
        raise UploadError(
            f"{len(missing)} processed image(s) missing; run `cib process` first:\n  "
            + "\n  ".join(p.name for p in missing))

    cloudinary = _configure(cfg)
    for stem, src in plan:
        url = image_url(cfg, stem)
        try:
            returned = _upload_one(cloudinary, src, folder, stem, preset)
        except Exception as e:  # noqa: BLE001
            result.outcomes.append(UploadOutcome(stem, src, "failed", detail=str(e)))
            continue

        status, detail = "uploaded", returned
        if verify:
            ok, why = _verify(url)
            status = "verified" if ok else "unverified"
            detail = returned if ok else f"{returned}  (delivery URL check: {why})"
        result.outcomes.append(UploadOutcome(stem, src, status, url=url, detail=detail))

    _write_record(cfg, result)
    return result


def _write_record(cfg: Config, result: UploadResult) -> None:
    cfg.out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%y%m%d-%H%M")
    path = cfg.out_dir / f"uploads_{ts}.json"
    path.write_text(json.dumps(
        {o.stem: {"url": o.url, "status": o.status} for o in result.outcomes
         if o.status in ("uploaded", "verified", "unverified")},
        indent=2), encoding="utf-8")
    cfg.prune_out("uploads_*.json", keep=5)
    result.record_path = path
