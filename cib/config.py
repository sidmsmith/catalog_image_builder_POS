"""Load and validate a customer's config.json, plus secrets from .env.

Nothing here reaches the network. Stage modules ask a Config for exactly the
values they need.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

# Project root = parent of the `cib/` package directory.
ROOT = Path(__file__).resolve().parent.parent
CUSTOMERS_DIR = ROOT / "customers"


class ConfigError(Exception):
    """Raised for a missing/malformed config or a missing required path."""


# --------------------------------------------------------------------------- #
# .env loading (no hard dependency on python-dotenv)
# --------------------------------------------------------------------------- #

def _load_dotenv(path: Path) -> dict[str, str]:
    """Parse a simple KEY=VALUE .env file. Ignores blanks and # comments.

    Values already present in the real environment win over the file, matching
    python-dotenv's default and letting a shell override a stored value.
    """
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key:
            values[key] = val
    return values


# --------------------------------------------------------------------------- #
# Config object
# --------------------------------------------------------------------------- #

@dataclass
class Config:
    customer: str
    source: str
    output_csv_dir: Path
    output_csv_name: str
    csv_columns: list[str]
    images_dir: Path
    cloudinary: dict
    image_spec: dict
    naming: dict

    # repo-local working directory for this customer (holds out/, images/)
    workdir: Path
    _env: dict[str, str] = field(default_factory=dict, repr=False)

    # ---- derived paths -------------------------------------------------- #

    @property
    def out_dir(self) -> Path:
        return self.workdir / "out"

    def prune_out(self, glob: str, keep: int = 5) -> list[Path]:
        """Delete all but the `keep` newest `out/<glob>` files (local scratch
        history — the real artifact is the published CSV in OneDrive)."""
        if not self.out_dir.is_dir():
            return []
        files = sorted(self.out_dir.glob(glob),
                       key=lambda p: (p.stat().st_mtime, p.name), reverse=True)
        removed = files[keep:]
        for p in removed:
            p.unlink(missing_ok=True)
        return removed

    @property
    def manifest_path(self) -> Path:
        return self.workdir / "manifest.csv"

    @property
    def published_csv_path(self) -> Path:
        return self.output_csv_dir / self.output_csv_name

    # ---- secrets (looked up lazily, only by stages that need them) ------ #

    def secret(self, key: str) -> str:
        val = os.environ.get(key) or self._env.get(key)
        if not val:
            raise ConfigError(
                f"Missing secret {key!r}. Add it to {ROOT / '.env'} "
                f"(see .env.example)."
            )
        return val

    # ---- validation --------------------------------------------------- #

    def require_publish_target(self) -> Path:
        if not self.output_csv_dir.is_dir():
            raise ConfigError(f"outputCsvDir not found: {self.output_csv_dir}")
        return self.published_csv_path


_REQUIRED_KEYS = ("customer", "source", "outputCsvDir", "imagesDir", "csvColumns")


def load_config(customer: str) -> Config:
    """Read customers/<customer>/config.json and return a Config."""
    cust_dir = CUSTOMERS_DIR / customer
    cfg_path = cust_dir / "config.json"
    if not cfg_path.is_file():
        raise ConfigError(f"No config for customer {customer!r}: {cfg_path} missing")

    try:
        raw = json.loads(cfg_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ConfigError(f"{cfg_path} is not valid JSON: {e}") from e

    missing = [k for k in _REQUIRED_KEYS if not raw.get(k)]
    if missing:
        raise ConfigError(f"{cfg_path} is missing required keys: {', '.join(missing)}")

    naming = raw.get("naming") or {}
    return Config(
        customer=raw["customer"],
        source=raw["source"],
        output_csv_dir=Path(raw["outputCsvDir"]),
        output_csv_name=raw.get("outputCsvName", f"{raw['customer']}Items.csv"),
        csv_columns=list(raw["csvColumns"]),
        images_dir=Path(raw["imagesDir"]),
        cloudinary=raw.get("cloudinary") or {},
        image_spec=raw.get("imageSpec") or {},
        naming={"style": naming.get("style", "TitleCase_Underscores"),
                "versionSuffix": bool(naming.get("versionSuffix", True))},
        workdir=cust_dir,
        _env=_load_dotenv(ROOT / ".env"),
    )


def list_customers() -> list[str]:
    if not CUSTOMERS_DIR.is_dir():
        return []
    return sorted(p.name for p in CUSTOMERS_DIR.iterdir()
                  if (p / "config.json").is_file())
