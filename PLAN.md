# Build Plan — POS fork

Forked from `../catalog_image_builder` (full build history and phase-by-phase
record live in that repo's `PLAN.md` and git log — this tool inherited a
complete, working harvest/process/upload pipeline, not a from-scratch build).

## What changed for POS

- [x] `cib/config.py` — dropped `wm` block and `referenceCsv`; added `csvColumns`
- [x] `cib/build_csv.py` — rewritten: one output row per kept manifest row
      (real `itemId` from the row), no ItemId-pool cycling; output header
      driven by the customer's `csvColumns`
- [x] `cib/manifest.py` — column set expanded to the full POS field superset
      (price, color, size, style grouping, retailer-specific extras);
      `itemId` now required + validated for duplicates
- [x] `cib/harvest.py` — captures the expanded POS field set per row
- [x] `cib/scaffold.py` — `new-customer` takes `--columns` (the retailer's
      real CSV header) instead of a reference-CSV path
- [x] `cib/cli.py` — `wm` subcommand removed; `run` no longer has a WM stage
- [x] `cib/wm_update.py`, `tests/test_wm.py` — deleted
- [x] `customers/reeds/`, `customers/dsw/` — scaffolded with each retailer's
      real CSV column order (from their sample exports); `cib csv` output
      verified byte-for-byte structurally against a real Reeds sample row
- [x] Docs (`README.md`, `CLAUDE.md`, `HARVESTING.md`, `SECURITY_BASELINE.md`,
      `.env.example`) updated for the POS model
- [x] Test suite updated for the new schema/row model (49 tests passing)
- [ ] Actual harvest of Reeds/DSW products — not started; scaffolding only

## Unchanged from the WM version

Cloudinary upload, background-removal/crop `process` step, naming/stem
allocation, and the two-checkpoint review workflow.
