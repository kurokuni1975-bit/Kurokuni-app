#!/usr/bin/env python3
"""CLI: python -m listing.main --file items.json [--dry-run] [--delay 2]

Run from ~/workspace/ebay-api so that the ``listing`` package imports.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys

# make `python -m listing.main` work regardless of cwd quirks
_PKG_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PKG_ROOT not in sys.path:
    sys.path.insert(0, _PKG_ROOT)

from listing.bulk import run_bulk, DEFAULT_DELAY  # noqa: E402
from listing.listing import EbayListingClient, ListingError  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="eBay bulk listing via Sell Inventory API "
                    "(createInventoryItem -> createOffer -> publishOffer)."
    )
    p.add_argument("--file", required=True,
                   help="input .json or .csv file (see listing/examples/)")
    p.add_argument("--dry-run", action="store_true",
                   help="validate only: no API calls, print payload previews")
    p.add_argument("--delay", type=float, default=DEFAULT_DELAY,
                   help=f"seconds between items (default {DEFAULT_DELAY})")
    p.add_argument("--marketplace", default=None,
                   help="marketplaceId override, e.g. EBAY_US (default from env)")
    p.add_argument("--out", default=None,
                   help="where to write the JSON results report")
    p.add_argument("--limit", type=int, default=None,
                   help="only process the first N items")
    p.add_argument("--token", default=None,
                   help="access token override (default: auth.get_valid_token())")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.dry_run:
        print("DRY-RUN: validating only, no eBay API calls will be made.\n")

    client = EbayListingClient(token=args.token,
                               marketplace_id=args.marketplace,
                               dry_run=args.dry_run)
    try:
        summary = run_bulk(args.file, client=client, dry_run=args.dry_run,
                           delay=args.delay, out=args.out, limit=args.limit)
    except ListingError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    print(f"\nTotal: {summary['total']} | "
          f"Succeeded: {summary['succeeded']} | "
          f"Failed: {summary['failed']}")
    for f in summary["failures"]:
        print(f"  FAIL {f['sku']}: {f['error']}")
    for r in summary["results"]:
        if not args.dry_run:
            print(f"  OK   {r['sku']} -> listing {r.get('listing_id')}")
    return 0 if not summary["failures"] else 1


if __name__ == "__main__":
    sys.exit(main())
