# Harvesting — the session recipe

The harvest is Claude-driven: Claude browses the site and decides *which*
products and *which* shot. This doc is the repeatable plumbing around that
judgement, so a harvest is a few steps instead of a bespoke script each time.

## Steps

1. **Scrape the listing pages.** Open each relevant collection / category /
   "all products" page in the browser pane and run `cib/harvest_scrape.js`
   (tune its 3 top consts per site). It returns every plausible product image
   with context (alt, nearest link, nearest heading).

   Sites vary — the scraper is a starting point, not a guarantee. When a site
   hides product data behind JS or a odd DOM, adapt the snippet or read the
   product pages directly (some expose a JSON-LD `image` array with the
   flat-lay / `__studio` / `__front` variants).

2. **Curate into an input file.** From the scraped rows, keep the ~50 you
   want and map them to `customers/<customer>/harvest_input.csv`. Only `name`
   and `sourceUrl` are required (`sourceName`/`url` also accepted; JSON list
   works too) — but a POS row needs real merchandising data, not just a name
   + image, so capture whatever the listing page (or the product page, if
   the listing doesn't show it) actually has:

   ```
   name,sourceUrl,itemId,style,webUrl,sellingPrice,basePrice,colorName,colorGroup,size,brand,category
   Moments Snake Chain Necklace,https://www.reeds.com/.../REEDS-24.jpg,REEDS-24,REEDS24,https://www.reeds.com/...,170,170,Silver,Silver,One Size,Pandora,necklace
   ```

   See `cib/manifest.py`'s `COLUMNS` for the full field list a POS row can
   carry (jewelry-only fields like `earringType`/`metalType`, footwear-only
   fields like `departmentNumber`/`weight`, etc. — leave whatever doesn't
   apply to this retailer blank).

   - **`itemId` is required on every row** — it's the real SKU, not something
     the CLI invents. Continue that retailer's own existing numbering
     (`REEDS-24` follows `REEDS-23`; `DSW17` follows `DSW16`).
   - **`style1`/`style2`** (related/cross-sell item codes) are real
     merchandising data in the samples, not derivable from a fresh
     harvest — hand-pick plausible same-category pairings among the items
     you're harvesting, or leave blank.
   - DSW-style color × size fan-out: capture the real color images and the
     real size run per color from the product page (don't synthesize a
     standard 6-11 run) — one manifest row per color+size combination,
     sharing the same three image URLs across all sizes of one color.
   - Names are run through `clean_source_name` automatically (drops trailing
     ` - Men's` etc.) — do brand-specific cleanup here.

3. **`cib harvest --customer <c>`** — downloads every image (browser UA +
   Referer), derives unique `localFile`s, writes `manifest.csv`.
   - `--width 1400` — append `?width=1400` to URLs with no query string
     (Umbraco / `/media/` CDNs serve a resize).
   - `--append` — add to an existing manifest (growing a catalogue over time).
   - `--dry-run` — parse + plan, download nothing.

4. **`cib review` + `cib names`** — the name-review checkpoint. Send the
   review page to the user, apply their edits.

5. `cib process` → `cib review` again (image review) → `cib run --yes` (or the
   individual `csv --publish` / `upload`). There is no `wm` step in this
   fork — Cloudinary upload is the last stage.

## Notes

- **Downloads:** `cib harvest` uses `requests` with a browser User-Agent and a
  Referer header. `urllib` is unreliably slow from some environments — don't
  fall back to it.
- **Image sourcing for messy catalogues:** if the customer's own site has no
  shoppable catalogue (e.g. a B2B / holding-company site), pull from the
  brands it owns or distributes — their consumer sites usually have clean
  packshots. Group everything under the one customer.
- **Retailer product-page galleries** commonly expose alternate views as
  `…/<stem>__front-<color>.jpg`, `__back`, `__side`, `__studio*` — these are
  the flat-lay / product-only shots; the plain `…/<stem>_<color>.jpg` is often
  an on-model hero. Prefer the studio/front variants.
