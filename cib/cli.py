"""`python -m cib <command>` entry point.

Phase 1 implements `csv`, `manifest`, and `customers`. The image / upload / WM
stages are stubbed until their phases land (see PLAN.md).
"""

from __future__ import annotations

import argparse
import sys

from . import __version__
from .config import ConfigError, list_customers, load_config


def _print_err(msg: str) -> None:
    print(f"error: {msg}", file=sys.stderr)


# --------------------------------------------------------------------------- #
# commands
# --------------------------------------------------------------------------- #

def cmd_customers(args) -> int:
    names = list_customers()
    if not names:
        print("no customers configured under customers/")
        return 0
    for n in names:
        print(n)
    return 0


def cmd_manifest(args) -> int:
    from .manifest import ManifestError, read_manifest

    cfg = load_config(args.customer)
    try:
        kept = read_manifest(cfg.manifest_path, kept_only=True)
        allrows = read_manifest(cfg.manifest_path, kept_only=False)
    except ManifestError as e:
        _print_err(str(e))
        return 1

    skipped = len(allrows) - len(kept)
    print(f"{cfg.manifest_path}")
    print(f"  {len(kept)} kept, {skipped} skipped")
    for r in kept:
        print(f"  [{r.category or '-':8}] {r.source_name}  <-  {r.local_file}")
    return 0


def cmd_new_customer(args) -> int:
    from .config import ConfigError as _CfgErr
    from .scaffold import new_customer

    columns = [c.strip() for c in args.columns.split(",")] if args.columns else None
    try:
        path = new_customer(args.name, args.website, args.dir, columns)
    except _CfgErr as e:
        _print_err(str(e))
        return 1
    print(f"wrote {path}")
    print("next: ask Claude to harvest, then `cib names`, `cib process`, `cib run`.")
    return 0


def cmd_harvest(args) -> int:
    from pathlib import Path as _Path

    from .harvest import HarvestError, run as harvest_run

    try:
        cfg = load_config(args.customer)
        result = harvest_run(
            cfg, _Path(args.input) if args.input else None,
            append=args.append, width=args.width, force=args.force, dry_run=args.dry_run)
    except (HarvestError, ConfigError) as e:
        _print_err(str(e))
        return 1

    for it in result.items:
        tag = {"downloaded": "ok  ", "exists": "have", "skipped": "skip",
               "failed": "FAIL"}.get(it.outcome, it.outcome)
        print(f"  [{tag}] {it.name}  {it.detail}")

    d, e, s, f = (len(result.by(k)) for k in ("downloaded", "exists", "skipped", "failed"))
    print(f"\ndownloaded {d}, had {e}, skipped {s}, failed {f}")
    if result.manifest_path:
        print(f"manifest: {result.manifest_path}")
        print("next: `cib review` + `cib names` to check, then `cib process`.")
    return 0 if result.ok else 1


def cmd_names(args) -> int:
    from .manifest import ManifestError
    from .names import apply_clean, review

    try:
        cfg = load_config(args.customer)
        if args.clean:
            changed, collided = apply_clean(cfg)
            for old, new in changed:
                print(f"  {old!r}  ->  {new!r}")
            print(f"\n{len(changed)} name(s) cleaned in {cfg.manifest_path}")
            if collided:
                print(f"{len(collided)} kept unchanged (cleaned name collides): "
                      + ", ".join(collided))
            return 0
        rows = review(cfg)
    except (ManifestError, ConfigError) as e:
        _print_err(str(e))
        return 1

    diff = [r for r in rows if r.proposed != r.current]
    coll = [r for r in rows if r.collides_with]
    for r in rows:
        mark = "  ~" if r.proposed != r.current else "   "
        line = f"{mark} {r.line:>3}  {r.current}"
        if r.proposed != r.current:
            line += f"   ->  {r.proposed}"
        if r.collides_with:
            line += f"   [!] same cleaned name as: {', '.join(r.collides_with)}"
        print(line)
    print(f"\n{len(rows)} kept · {len(diff)} would change with --clean · {len(coll)} name collision(s)")
    print("review, then: `cib names --customer <c> --clean` (bulk) and/or hand-edit "
          "the sourceName column of manifest.csv, before `cib process`.")
    return 0


def cmd_csv(args) -> int:
    from .build_csv import BuildError, run as build_run

    try:
        cfg = load_config(args.customer)
    except ConfigError as e:
        _print_err(str(e))
        return 1

    try:
        result = build_run(cfg, publish=args.publish, dry_run=args.dry_run)
    except (BuildError, ConfigError) as e:
        _print_err(str(e))
        return 1
    else:
        _report_build(cfg, result, args)
        return 0


def _report_build(cfg, result, args) -> None:
    print(f"customer      : {cfg.customer}")
    print(f"output rows   : {result.row_count}")
    if result.duplicate_item_ids:
        preview = ", ".join(result.duplicate_item_ids[:10])
        more = "" if len(result.duplicate_item_ids) <= 10 else f" (+{len(result.duplicate_item_ids) - 10})"
        print(f"dup ItemIds   : {len(result.duplicate_item_ids)} -> {preview}{more}")

    if args.dry_run:
        print("\n[dry run] no files written. First 5 rows:")
        print("  " + ",".join(result.columns))
        for row in result.rows[:5]:
            print("  " + ",".join(row))
        return

    print(f"\nwrote {result.out_path}")
    if result.published_path:
        print(f"published {result.published_path}")
    elif args.publish is False:
        print("(not published to outputCsvDir; pass --publish to copy there)")


def cmd_process(args) -> int:
    from .process import ProcessError, run as process_run

    try:
        cfg = load_config(args.customer)
    except ConfigError as e:
        _print_err(str(e))
        return 1

    model = "isnet-general-use" if args.fast else args.model
    try:
        result = process_run(cfg, force=args.force, only=args.only,
                             limit=args.limit, model=model)
    except (ProcessError, ConfigError) as e:
        _print_err(str(e))
        return 1

    for o in result.outcomes:
        tag = {"processed": "ok  ", "skipped": "skip", "missing": "MISS", "failed": "FAIL"}[o.status]
        print(f"  [{tag}] {o.source_name}  {o.detail}")

    p, s = len(result.by("processed")), len(result.by("skipped"))
    m, f = len(result.by("missing")), len(result.by("failed"))
    print(f"\nprocessed {p}, skipped {s}, missing {m}, failed {f}")
    print(f"output: {cfg.images_dir / 'processed'}")
    return 0 if result.ok else 1


def cmd_upload(args) -> int:
    from .cloudinary_upload import UploadError, run as upload_run
    from .config import ConfigError as _CfgErr

    try:
        cfg = load_config(args.customer)
        result = upload_run(cfg, dry_run=args.dry_run, only=args.only,
                            verify=not args.no_verify)
    except (UploadError, _CfgErr) as e:
        _print_err(str(e))
        return 1

    for o in result.outcomes:
        tag = {"uploaded": "up  ", "verified": "ok  ", "unverified": "WARN",
               "missing": "MISS", "failed": "FAIL"}.get(o.status, o.status)
        print(f"  [{tag}] {o.stem}  {o.detail}")

    u = len(result.by("uploaded")) + len(result.by("verified")) + len(result.by("unverified"))
    print(f"\nuploaded {u}, unverified {len(result.by('unverified'))}, "
          f"missing {len(result.by('missing'))}, failed {len(result.by('failed'))}")
    if result.record_path:
        print(f"record: {result.record_path}")
    return 0 if result.ok else 1


def cmd_review(args) -> int:
    from .review import ReviewError, run as review_run

    try:
        cfg = load_config(args.customer)
        path = review_run(cfg, open_browser=not args.no_open)
    except (ReviewError, ConfigError) as e:
        _print_err(str(e))
        return 1
    print(f"wrote {path}")
    return 0


def cmd_run(args) -> int:
    """process -> csv -> review, then (with --yes) upload."""
    from .build_csv import BuildError, run as build_run
    from .cloudinary_upload import UploadError, run as upload_run
    from .process import ProcessError, run as process_run
    from .review import run as review_run

    try:
        cfg = load_config(args.customer)
    except ConfigError as e:
        _print_err(str(e))
        return 1

    model = "isnet-general-use" if args.fast else None

    try:
        if not args.skip_process:
            print("== process ==")
            pr = process_run(cfg, force=args.force, model=model)
            for o in pr.outcomes:
                print(f"  [{o.status}] {o.source_name}  {o.detail}")
            if not pr.ok:
                _print_err("process had missing/failed images - stopping")
                return 1

        print("\n== csv ==")
        br = build_run(cfg, publish=args.publish)
        print(f"  {br.row_count} rows -> {br.out_path}")
        if br.published_path:
            print(f"  published {br.published_path}")

        print("\n== review ==")
        rp = review_run(cfg, open_browser=not args.no_open)
        print(f"  {rp}")

        if not args.yes:
            print("\nstopped before upload. Review, then re-run with --yes "
                  "(or run `cib upload`).")
            return 0

        print("\n== upload ==")
        ur = upload_run(cfg, only=None, verify=True)
        for o in ur.outcomes:
            print(f"  [{o.status}] {o.stem}")
        if not ur.ok:
            _print_err("upload had missing/failed images")
            return 1
        return 0

    except (ProcessError, BuildError, UploadError, ConfigError) as e:
        _print_err(str(e))
        return 1


# --------------------------------------------------------------------------- #
# parser
# --------------------------------------------------------------------------- #

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="cib", description="Catalog Image Builder")
    p.add_argument("--version", action="version", version=f"cib {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("customers", help="list configured customers").set_defaults(func=cmd_customers)

    def add_customer(sp):
        sp.add_argument("--customer", required=True, help="customer folder name")

    nc = sub.add_parser("new-customer", help="scaffold customers/<name>/config.json + manifest")
    nc.add_argument("name", help="customer display name, e.g. \"Reeds\"")
    nc.add_argument("--website", required=True, help="site to harvest from, e.g. reeds.com")
    nc.add_argument("--dir", required=True, help="base folder; images/output derived from it")
    nc.add_argument("--columns", help="comma-separated CSV header matching the retailer's own "
                                      "POS export format (default: a generic unified schema)")
    nc.set_defaults(func=cmd_new_customer)

    hv = sub.add_parser("harvest", help="scraped list -> download images + write manifest")
    add_customer(hv)
    hv.add_argument("--input", help="CSV/JSON of name,sourceUrl[,brand,category] "
                                    "(default: customers/<c>/harvest_input.csv)")
    hv.add_argument("--append", action="store_true", help="add to an existing manifest")
    hv.add_argument("--width", type=int, help="append ?width=N to URLs that have no query "
                                              "(Umbraco/media CDNs)")
    hv.add_argument("--force", action="store_true", help="re-download images already present")
    hv.add_argument("--dry-run", action="store_true", help="parse + plan, download nothing")
    hv.set_defaults(func=cmd_harvest)

    mp = sub.add_parser("manifest", help="show the parsed manifest")
    add_customer(mp)
    mp.set_defaults(func=cmd_manifest)

    nm = sub.add_parser("names", help="review / clean product names before processing")
    add_customer(nm)
    nm.add_argument("--clean", action="store_true",
                    help="strip trailing ' - Men's' etc. from every sourceName and save")
    nm.set_defaults(func=cmd_names)

    cp = sub.add_parser("csv", help="build the POS item CSV")
    add_customer(cp)
    cp.add_argument("--publish", action="store_true",
                    help="also copy the CSV to outputCsvDir")
    cp.add_argument("--dry-run", action="store_true", help="write nothing, just report")
    cp.set_defaults(func=cmd_csv)

    pr = sub.add_parser("process", help="remove backgrounds, trim, resize")
    add_customer(pr)
    pr.add_argument("--force", action="store_true", help="re-process images already done")
    pr.add_argument("--only", help="substring filter on localFile / stem")
    pr.add_argument("--limit", type=int, help="process at most N images")
    pr.add_argument("--model", help="override rembg model for this run")
    pr.add_argument("--fast", action="store_true",
                    help="use isnet-general-use (fast draft; weak on white soles)")
    pr.set_defaults(func=cmd_process)

    up = sub.add_parser("upload", help="upload processed PNGs to Cloudinary")
    add_customer(up)
    up.add_argument("--dry-run", action="store_true", help="list what would upload, send nothing")
    up.add_argument("--only", help="substring filter on stem")
    up.add_argument("--no-verify", action="store_true",
                    help="skip the post-upload delivery-URL check")
    up.set_defaults(func=cmd_upload)

    rv = sub.add_parser("review", help="write + open out/review.html contact sheet")
    add_customer(rv)
    rv.add_argument("--no-open", action="store_true", help="write the file, don't open a browser")
    rv.set_defaults(func=cmd_review)

    rn = sub.add_parser("run", help="process -> csv -> review; --yes adds upload")
    add_customer(rn)
    rn.add_argument("--yes", action="store_true", help="also upload to Cloudinary")
    rn.add_argument("--fast", action="store_true", help="process with the fast model")
    rn.add_argument("--force", action="store_true", help="re-process images already done")
    rn.add_argument("--skip-process", action="store_true", help="reuse existing processed PNGs")
    rn.add_argument("--publish", action="store_true", help="copy the CSV to outputCsvDir")
    rn.add_argument("--no-open", action="store_true", help="don't open the review page")
    rn.set_defaults(func=cmd_run)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
