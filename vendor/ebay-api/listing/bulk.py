"""Bulk listing registration: CSV/JSON in -> sequential create_listing calls.

Design notes:
  * One item at a time (matches the Inventory API 3-step flow and keeps
    failures isolated). A failure is recorded and the run continues.
  * Pacing: ``delay`` seconds between items (default from EBAY_LISTING_DELAY
    env, else 2.0s) + exponential backoff on 429/5xx inside listing._api.
    (Bulk *API* endpoints /bulk_create_offer etc. are a future optimization.)
  * Results are written to a JSON report: successes with listing IDs,
    failures with error messages.

CSV columns (header row required):
    sku,title,price_usd,image_urls,category,condition
    optional: currency,title_parts_json,description,description_parts_json,
      image_urls (| separated), category_id, condition_note, box_number,
      best_offer (true/false), min_offer_price, auto_accept_price, quantity,
      aspects_json, marketplace_id

JSON format: a list of item dicts, or {"items": [...]} -- same schema as
create_listing(item_data) in listing.py.
"""

from __future__ import annotations

import csv
import json
import logging
import os
import time
from datetime import datetime, timezone

from .listing import EbayListingClient, ListingError

log = logging.getLogger(__name__)

DEFAULT_DELAY = float(os.environ.get("EBAY_LISTING_DELAY", "2.0"))


def _parse_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def _row_to_item(row: dict) -> dict:
    item: dict = {
        "sku": (row.get("sku") or "").strip(),
        "price_usd": row.get("price_usd"),
        "category": (row.get("category") or "").strip() or None,
        "category_id": (row.get("category_id") or "").strip() or None,
        "condition": (row.get("condition") or "USED_GOOD").strip(),
        "box_number": (row.get("box_number") or "").strip() or None,
        "best_offer": _parse_bool(row.get("best_offer", "true")),
        "currency": (row.get("currency") or "USD").strip(),
        "marketplace_id": (row.get("marketplace_id") or "").strip() or None,
    }
    if row.get("title"):
        item["title"] = row["title"].strip()
    if row.get("title_parts_json"):
        item["title_parts"] = json.loads(row["title_parts_json"])
    if row.get("description"):
        item["description"] = row["description"]
    if row.get("description_parts_json"):
        item["description_parts"] = json.loads(row["description_parts_json"])
    if row.get("image_urls"):
        item["image_urls"] = [u.strip() for u in str(row["image_urls"]).split("|") if u.strip()]
    if row.get("condition_note"):
        item["condition_note"] = row["condition_note"]
    if row.get("min_offer_price"):
        item["min_offer_price"] = float(row["min_offer_price"])
    if row.get("auto_accept_price"):
        item["auto_accept_price"] = float(row["auto_accept_price"])
    if row.get("quantity"):
        item["quantity"] = int(row["quantity"])
    if row.get("aspects_json"):
        item["aspects"] = json.loads(row["aspects_json"])
    return item


def load_items(path: str) -> list[dict]:
    """Load items from a .json or .csv file."""
    path = os.path.expanduser(path)
    if path.lower().endswith(".json"):
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        items = data["items"] if isinstance(data, dict) else data
        if not isinstance(items, list):
            raise ListingError(f"{path}: expected a list or {{'items': [...]}}")
        return items
    if path.lower().endswith(".csv"):
        with open(path, encoding="utf-8-sig", newline="") as f:
            return [_row_to_item(r) for r in csv.DictReader(f)]
    raise ListingError(f"unsupported file type: {path} (use .json or .csv)")


def run_bulk(path: str,
             client: EbayListingClient | None = None,
             dry_run: bool = False,
             delay: float | None = None,
             out: str | None = None,
             limit: int | None = None) -> dict:
    """Register all items in *path* sequentially. Never stops on failure.

    Returns a summary dict and writes a JSON report to *out*
    (default: bulk_results_<timestamp>.json next to the input file).
    """
    items = load_items(path)
    if limit:
        items = items[:limit]
    delay = DEFAULT_DELAY if delay is None else delay
    client = client or EbayListingClient(dry_run=dry_run)

    started = datetime.now(timezone.utc).isoformat()
    succeeded: list[dict] = []
    failed: list[dict] = []

    for i, raw in enumerate(items):
        sku = raw.get("sku", f"row-{i}")
        try:
            result = client.create_listing(raw)
            succeeded.append(result)
            log.info("[%d/%d] OK sku=%s listing=%s",
                     i + 1, len(items), sku, result.get("listing_id"))
        except Exception as exc:  # noqa: BLE001 -- record, don't stop
            err = f"{type(exc).__name__}: {exc}"
            failed.append({"sku": sku, "error": err})
            log.error("[%d/%d] FAIL sku=%s: %s", i + 1, len(items), sku, err)
        if delay and i < len(items) - 1:
            time.sleep(delay)

    summary = {
        "started_at": started,
        "ended_at": datetime.now(timezone.utc).isoformat(),
        "input": path,
        "dry_run": dry_run,
        "total": len(items),
        "succeeded": len(succeeded),
        "failed": len(failed),
        "results": succeeded,
        "failures": failed,
    }
    out_path = out or os.path.join(
        os.path.dirname(os.path.abspath(path)),
        f"bulk_results_{datetime.now(timezone.utc):%Y%m%d_%H%M%S}.json",
    )
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    log.info("bulk done: %d ok / %d failed -- report: %s",
             len(succeeded), len(failed), out_path)
    return summary
