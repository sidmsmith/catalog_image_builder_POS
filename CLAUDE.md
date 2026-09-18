# Catalog Image Builder — POS — Project Instructions

Follows this repo's `AGENTS.md` and `SECURITY_BASELINE.md` (Work-ecosystem
conventions, kept here so the repo is self-contained).

## What this project is

A fork of `catalog_image_builder` (the Manhattan WM version, at
`../catalog_image_builder`) for **POS retailers** — Reeds, DSW, and others
added later. A local Python CLI (`cib`) turns a harvested product manifest
into that retailer's own **POS item CSV** (not a generic WM format — each
customer's `config.json` declares its exact column list/order) and pushes
images to Cloudinary. **There is no WM step in this repo at all** — no `wm`
subcommand, no SS-DEMO, no Manhattan secrets. See `README.md` for the full
architecture.

## Division of labor — do not blur these

- **Harvest (Claude, interactive):** browsing retailer sites, choosing which
  products and which shot, capturing price/color/size/style-grouping, and
  assigning each item's real `itemId` (continuing that retailer's own
  numbering — never invent a numbering scheme). The *judgement*.
- **`cib harvest` + backend:** deterministic. `cib harvest` turns curated
  input into downloads + `manifest.csv`; the rest of the CLI processes it.
  No scraping, no AI, no image *search* inside the CLI.

Recipe: `HARVESTING.md`. A POS harvest usually needs a product-page visit
per item (not just its listing tile) to get price/color/size — this is a
bigger harvest lift per item than the WM version's "name + one image".

## Two review checkpoints — always stop and ask

Same discipline as the WM version. `cib review` is the user's window for
both — every kept row with its image and name.

1. **Names** — after harvest, before `cib process`. Wait for edits.
2. **Images** — after `cib process`. Wait for swap/drop decisions before
   `csv` / `upload`.

## Onboarding a new customer

`cib new-customer "<Display Name>" --website <site> --dir <base folder> --columns "<retailer's real CSV header>"`.
If the user has a sample of the retailer's actual POS CSV export, use its
literal header (order matters) as `--columns` — that's the format `cib csv`
will reproduce. Without one, `scaffold.DEFAULT_CSV_COLUMNS` is a reasonable
generic fallback to refine later in `config.json`.

## Row model — no ItemId cycling

The WM version cycles a handful of harvested images across a flat pool of
placeholder demo ItemIds. **This fork does not do that.** Every manifest row
is a real product variant with its own real `itemId`, and `cib csv` emits
exactly one output row per kept manifest row. A DSW-style product can fan
out into many manifest rows (one per color × size) sharing the same image
set — that's expected, not a bug.

## When the user asks "what do you need to run this?" (or how to run it)

Answer from README's **"What to tell Claude to run this"** section: an
existing customer needs one sentence; a new customer needs name / site /
folder / (ideally) a sample of their real CSV. Then walk the harvest →
name-review → process → image-review → csv → (go-ahead) → upload flow —
note there is no WM step to mention.

## Runtime

- Local only. Python 3.14, project `.venv` (separate from
  `../catalog_image_builder`'s venv — this repo was forked without copying
  it; recreate with `pip install -r requirements.lock`).
- Secrets in `.env` (gitignored) — Cloudinary only.

## Origin

Forked from `catalog_image_builder` (private, `github.com/sidmsmith/catalog_image_builder`)
to serve POS retailers instead of the Manhattan WM demo. The harvest
mechanism, background-removal pipeline, Cloudinary upload, naming/stem
allocation, and two-checkpoint review workflow are unchanged from that
project. `build_csv.py`, `config.py`'s schema, and the manifest's field list
were rewritten for the real-SKU-per-row POS model; `wm_update.py` and the
`wm` subcommand were removed outright.

## Conventions

- Every CLI stage is idempotent and re-runnable.
- Side-effectful stages support `--dry-run`.
- Commit and push after each phase / unit of work lands (see `AGENTS.md`).
  This repo has **no remote configured yet** — set one up before relying on
  push for backup/sharing.
