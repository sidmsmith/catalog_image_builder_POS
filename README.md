# Catalog Image Builder — POS (`cib`)

Build a retailer's own **POS item CSV** from real product imagery — with
transparent, cropped images — and push the images to Cloudinary. This is a
fork of `catalog_image_builder` (the Manhattan WM version): same harvesting
approach and Cloudinary pipeline, but:

- **No WM.** Nothing here ever calls Manhattan WM. There is no `wm`
  subcommand and no `SS-DEMO` org in this repo.
- **The CSV format is the retailer's own POS format**, not a generic
  4-column WM shape. Each customer's `config.json` declares its own exact
  column list (order matters — it's their real import format), so Reeds and
  DSW each get their own header even though they share most fields.
- **Every output row is a real product variant**, not a placeholder ItemId
  cycled with a stand-in image. Claude assigns the real SKU (`itemId`) while
  curating `harvest_input.csv` — continuing that retailer's own numbering
  (`REEDS-24`, `DSW17`...) — and `cib csv` just projects each kept manifest
  row through the customer's column list. There's no reference-ItemId pool
  to cycle images across.

| Half | Who runs it | What it does |
|------|-------------|---------------|
| **Harvest** | Claude, interactively, per site | Browse the retailer, choose the right products and the best shot, capture price/color/size/etc., append rows to `manifest.csv`. Judgement-heavy, deliberately not scripted. |
| **Backend** | A local Python CLI (`cib`) | Deterministic. Reads `manifest.csv` + `config.json`, removes backgrounds, crops, builds the POS CSV, uploads to Cloudinary. No AI, no scraping. |

---

## What to tell Claude to run this

### Existing customer

> **"Harvest ~50 earrings + bracelets from reeds.com for Reeds."**

### New customer

Give Claude **name, website, base folder, and the retailer's real CSV**
(a sample export, if you have one — it becomes the exact column list/order
`cib csv` will produce):

> **"Set up Nordstrom — website nordstrom.com, folder
> `C:/Users/ssmith/OneDrive - Manhattan Associates/Documents/Solutions Consulting/Nordstrom`.
> Here's a sample of their POS CSV format: [attach]."**

Without a sample, Claude falls back to a generic unified schema (see
`scaffold.DEFAULT_CSV_COLUMNS`) that you can edit into `config.json` later.

### What Claude does, and where it pauses for you

```
harvest  →  [PAUSE: name review]  →  process  →  [PAUSE: image review]  →  csv
                                                                            │
                                                    (your "go ahead")  →  upload  ┘
```

Same two-checkpoint discipline as the WM version — **`cib review`** opens
`out/review.html` with every kept item, its image, and its name.

1. **Name review** — before `cib process`. The name becomes
   `ShortDescription`/`Description` and can't change afterward without
   reprocessing.
2. **Image review** — after background removal. Call out swaps/drops.
3. Claude builds the CSV and **stops**. Cloudinary upload happens only
   after you say go — nothing downstream of that (there is no WM step).

---

## Why local, not Vercel

Same reasoning as the WM version: the deliverable is files on disk
(processed PNGs + CSV in OneDrive), `rembg` is too big/slow for serverless,
and Claude Code already runs here with shell + filesystem access.

---

## Layout

```
catalog_image_builder_POS/
  .venv/                        project virtualenv (gitignored)
  .env                          secrets (gitignored) — Cloudinary only, see .env.example
  requirements.txt
  README.md   PLAN.md   CLAUDE.md   HARVESTING.md
  cib/                          the backend package
    config.py                   load + validate config.json (no wm block), load .env
    scaffold.py                 `cib new-customer` — write config.json + manifest
    harvest.py + harvest_scrape.js  `cib harvest` — scraped list -> downloads + manifest
    manifest.py                 read/validate manifest.csv (full POS field superset)
    naming.py                   name cleanup + product-name -> filename stem
    names.py                    `cib names` — the name review checkpoint
    build_csv.py                projects each kept row through the customer's csvColumns
    process.py                  downscale + rembg + trim + 600x600 canvas
    cloudinary_upload.py        upload processed PNGs + verify delivery URL
    review.py                   review.html — image + name per row, both checkpoints
    cli.py                      `python -m cib <command>` (incl. `run` orchestration)
  tests/                        `python -m unittest discover -s tests`
  customers/
    reeds/
      config.json               this customer's settings + its exact CSV column list
      manifest.csv              Claude appends rows here during harvest
      images/                   raw downloads
      images/processed/         transparent 600x600 PNGs (CLI output)
      out/                      generated CSVs, review.html
    dsw/
      ... same shape
```

---

## Config schema (`customers/<name>/config.json`)

```json
{
  "customer": "Reeds",
  "source": "reeds.com",
  "outputCsvDir": "C:/Users/ssmith/OneDrive - Manhattan Associates/Documents/Solutions Consulting/Reeds",
  "outputCsvName": "ReedsItems.csv",
  "csvColumns": [
    "ItemId", "ShortDescription", "WebURL", "Description", "SellingPrice",
    "BasePrice", "ColorName", "ColorGroup", "Size", "SizeSortSequence",
    "ImageURI", "ImageURI2", "ImageURI3", "Style", "Brand", "StoreDepartment",
    "ProductClass", "Style1", "Style2", "AdjustQuantity", "Rating",
    "EarringType", "MetalType"
  ],
  "imagesDir": "C:/Users/ssmith/OneDrive - Manhattan Associates/Documents/Solutions Consulting/Reeds/images",
  "cloudinary": {
    "cloudName": "com-manh-cp",
    "folder": "sidney",
    "preset": "sc_uploads",
    "urlPrefix": "https://res.cloudinary.com/com-manh-cp/image/upload/"
  },
  "imageSpec": {
    "canvas": 600, "fit": "contain", "format": "png", "transparent": true,
    "trim": true, "removeBackground": "rembg", "rembgModel": "birefnet-general",
    "workingResolution": 1600, "alphaMatting": false
  },
  "naming": { "style": "TitleCase_Underscores", "versionSuffix": true }
}
```

Notes:
- **No `wm` block, no `referenceCsv`.** Those are WM-only concepts that don't
  exist in this fork.
- `csvColumns` is the one field that's genuinely per-customer — it's the
  retailer's own real header, verbatim, in their order. `build_csv.FIELD_MAP`
  maps each recognized column name to a manifest field; anything it doesn't
  recognize is written blank rather than erroring (lets one retailer's schema
  carry a column the other doesn't populate).
- Secrets never live here. Cloud name and folder are not secret.
- `imageSpec.removeBackground`: `"rembg"` (local cutout, default), `"none"`
  (source is already transparent — just trim + canvas), or **`"skip"`** —
  the bypass for when cropping/transparency isn't worth the time on a POS
  batch: the harvested image passes through unchanged (no rembg, no trim, no
  canvas fit). Claude asks whether to use `"skip"` at the image-review
  checkpoint rather than deciding on its own — see `CLAUDE.md`.

---

## Manifest schema (`customers/<name>/manifest.csv`)

One row per product variant Claude decides to keep. Far more columns than
the WM version, because a POS CSV row needs real merchandising data, not
just a name + image. Full list in `cib/manifest.py`'s `COLUMNS`; most
important:

| Column | Meaning | Filled by |
|---|---|---|
| `sourceName` | Working display name (drives the image filename stem) | Claude |
| `itemId` | **The real SKU** — continue that retailer's existing numbering (`REEDS-24`, `DSW17`) | Claude |
| `style` | Product-level style code (groups color/size variants) | Claude |
| `webUrl` | The retailer's own PDP URL | Claude |
| `shortDescription` / `description` | Can differ — `description` is often longer marketing copy | Claude |
| `sellingPrice` / `basePrice` | Current vs. list price | Claude |
| `colorName` / `colorGroup` | | Claude |
| `size` / `sizeSortSequence` | | Claude |
| `style1` / `style2` | Related/cross-sell item codes — hand-picked, not inferred | Claude |
| `brand`, `category`, `sourceUrl`, `localFile`, `status`, `notes` | as in the WM version | Claude |
| `earringType`, `metalType` | Reeds-only (jewelry); blank for other retailers | Claude, when relevant |
| `departmentNumber`, `departmentName`, `vasTypeId`, `locationId`, `caLocationId`, `weight`, `volume` | DSW-only (warehouse/footwear); blank for other retailers | Claude, when relevant |

`status = skip` rows are ignored by every backend stage but kept for the
record. **Every kept row needs a real `itemId`** — `cib` will refuse to
build a CSV or even read the manifest for review if one's missing, or if two
rows collide on the same `itemId` or `localFile`.

---

## How the CSV is built (no cycling — one row per variant)

1. Read `manifest.csv`, keep `status != skip`.
2. Emit **exactly one output row per kept manifest row** — no ItemId pool,
   no cycling. The row's real `itemId` goes straight into the `ItemId`
   column.
3. Columns = whatever `config.json`'s `csvColumns` says, in that order.
   `ImageURI`/`ImageURI2`/`ImageURI3`/`ColorImageURI` all get the same
   Cloudinary URL — `cib` only produces one processed shot per manifest row,
   so "extra angle" slots repeat it. Everything else comes from
   `build_csv.FIELD_MAP`; unmapped columns are blank.
4. Output written to `customers/<name>/out/{outputCsvName stem}_<YYMMDD-HHMM>.csv`
   (repo-local, gitignored). Pass `--publish` to also copy it to
   `{outputCsvDir}/{outputCsvName}` in OneDrive.

The image filename `stem` is `TitleCase_Underscores` of `sourceName` plus
`_vNN`, exactly as in the WM version — `csv`/`process`/`upload` all compute
it the same way from the same manifest order, so filenames always agree.

---

## CLI

```bash
# one-time
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

# scaffold a new customer — --columns is the retailer's real CSV header
python -m cib new-customer "Reeds" --website reeds.com \
       --dir "C:/Users/ssmith/OneDrive - .../Solutions Consulting/Reeds" \
       --columns "ItemId,ShortDescription,WebURL,Description,SellingPrice,..."

# harvest: scraped list -> downloads + manifest  (see HARVESTING.md)
python -m cib harvest  --customer reeds                # reads customers/reeds/harvest_input.csv
python -m cib harvest  --customer reeds --width 1400 --dry-run
python -m cib harvest  --customer reeds --append       # add to an existing manifest

# inspect what a harvest produced
python -m cib customers                                # list configured customers
python -m cib manifest --customer reeds                # parsed manifest, kept vs skipped

# name review checkpoint (after harvest, before process)
python -m cib names   --customer reeds                 # list names; show proposed cleanups + collisions
python -m cib names   --customer reeds --clean         # apply "drop - Men's / - Unisex" to every row

python -m cib csv      --customer reeds                # build the POS CSV
python -m cib csv      --customer reeds --dry-run      # report only, write nothing
python -m cib csv      --customer reeds --publish      # also copy to OneDrive outputCsvDir

python -m cib process  --customer reeds                # rembg + trim + 600x600 PNG
python -m cib process  --customer reeds --fast         # quick draft pass (isnet, ~1s/img)
python -m cib review   --customer reeds                # write + open out/review.html
python -m cib upload   --customer reeds --dry-run      # list uploads, send nothing
python -m cib upload   --customer reeds                # push processed PNGs to Cloudinary
python -m cib run      --customer reeds                # process -> csv -> review, then stop
python -m cib run      --customer reeds --yes          # ...continue through upload
```

Every stage is idempotent and safe to re-run.

---

## Harvest session protocol (what Claude does)

Full recipe in **`HARVESTING.md`**. In short, when you say *"harvest from
`<url>` for `<customer>`"*:

1. Claude walks the site's category/listing pages in the browser pane.
   Unlike the WM version's "name + one image" harvest, a POS row needs
   price, color(s) (each with its own image), and the size run — so this
   usually means visiting each product's page, not just its listing tile.
2. Claude curates that into `customers/<customer>/harvest_input.csv` — see
   `manifest.COLUMNS` for the full field set; `itemId` is the one every row
   needs, assigned by continuing that retailer's existing sequence.
3. **`cib harvest --customer <c>`** — cleans names, derives unique
   `localFile`s, downloads every image, writes `manifest.csv`.
4. **Name review** — `cib review` + `cib names`, wait for your edits.
5. `cib process` → **image review** (`cib review` again) → `csv` / `upload`
   on your go-ahead.

For DSW, a single shoe style can fan out into many rows (one per
color × size) — real available sizes are enumerated from the product page
per color, not synthesized.

---

## Security

See `SECURITY_BASELINE.md`. In short:
- Secrets only in `.env` (gitignored) — Cloudinary credentials only; there's
  no WM secret to hold since this fork never talks to WM.
- `.env.example` documents the required keys with placeholder values.
