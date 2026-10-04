"""eBay Sell Inventory API - 3-step listing flow.

    1. PUT    /sell/inventory/v1/inventory_item/{sku}   (createOrReplaceInventoryItem)
    2. POST   /sell/inventory/v1/offer                  (createOffer)
    3. POST   /sell/inventory/v1/offer/{offerId}/publish (publishOffer)

Verified API facts (2026-10-03, eBay developer docs):
  * Images: ``imageUrls`` accepts seller self-hosted **HTTPS** URLs -- eBay
    Picture Services upload is NOT required. >= 1 image required before
    publish; up to 24 per listing.
  * Best Offer: enabled inline on the offer via
    ``listingPolicies.bestOfferTerms = {bestOfferEnabled, autoAcceptPrice?,
    autoDeclinePrice?}`` -- no separate policy object needed.
  * Condition: ConditionEnum. For US clothing categories the valid values
    are NEW / NEW_WITH_TAGS / LIKE_NEW / NEW_OTHER / NEW_WITH_DEFECTS /
    USED_EXCELLENT / USED_VERY_GOOD / USED_GOOD / USED_ACCEPTABLE.
    ``conditionDescription`` (max 1000 chars) carries the seller's
    uppercase condition note for used items.
  * Description: max 4000 chars, basic HTML only (b/br/ul/li/table).
    Required before publish.
  * Offer requires listingPolicies with payment/return/fulfillment policy
    IDs (from the seller's eBay business policies / Account API).

Auth: token comes from ``auth.get_valid_token()`` (module 1, developed in
parallel). The import is done lazily inside ``get_token()`` so this module
imports cleanly even when ``auth`` does not exist yet; in that case a
clear ``ListingError`` is raised only when a real API call is attempted.
``EBAY_ACCESS_TOKEN`` env var overrides (useful for tests).
"""

from __future__ import annotations

import logging
import os
import time
from urllib.parse import quote

import requests

from .category_map import resolve_category, marketplace_id_for
from .title_builder import build_title, validate_title, MAX_TITLE_LEN

log = logging.getLogger(__name__)

PROD_BASE = "https://api.ebay.com"
SANDBOX_BASE = "https://api.sandbox.ebay.com"
API_PATH = "/sell/inventory/v1"

REQUEST_TIMEOUT = 30
MAX_RETRIES = 3

#: Project spec wants the box number stored as customLabel. Sibling module
#: research (sku/api_research.md) found the Inventory API does not support
#: custom label updates; createInventoryItem may therefore 400 on this
#: field. Strategy: try WITH customLabel first, and on a 400 that names
#: the field, retry once WITHOUT it (warning logged). Either way the box
#: number is preserved in the bulk report.
INCLUDE_CUSTOM_LABEL = True


class ListingError(Exception):
    """Raised for validation failures and eBay API errors."""


# --------------------------------------------------------------------------
# config / auth
# --------------------------------------------------------------------------

def get_base_url() -> str:
    return SANDBOX_BASE if os.environ.get("EBAY_ENV") == "sandbox" else PROD_BASE


def get_token() -> str:
    """Return a valid OAuth access token.

    Order: EBAY_ACCESS_TOKEN env -> auth.get_valid_token() ->
    auth.token_store.get_valid_token(). Raises ListingError if the auth
    module is not available yet.
    """
    env_token = os.environ.get("EBAY_ACCESS_TOKEN")
    if env_token:
        return env_token
    try:
        from auth import get_valid_token  # type: ignore
    except ImportError:
        try:
            from auth.token_store import get_valid_token  # type: ignore
        except ImportError:
            raise ListingError(
                "auth 모듈이 아직 준비되지 않았습니다 (get_valid_token 없음). "
                "auth 모듈 연결 후 다시 시도하거나, 테스트용으로 "
                "EBAY_ACCESS_TOKEN 환경변수를 설정하세요."
            )
    return get_valid_token()


# --------------------------------------------------------------------------
# HTTP with retry (replaced by common/ client once it lands)
# --------------------------------------------------------------------------

def _api(method: str, path: str, token: str, payload: dict | None = None,
         timeout: int = REQUEST_TIMEOUT) -> dict:
    """Call the Inventory API with timeout + exponential backoff on 429/5xx."""
    url = get_base_url() + API_PATH + path
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Content-Language": "en-US",
    }
    last_err: Exception | None = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            resp = requests.request(method, url, headers=headers,
                                    json=payload, timeout=timeout)
        except requests.RequestException as exc:
            last_err = exc
            log.warning("request failed (attempt %d): %s", attempt + 1, exc)
        else:
            if resp.status_code in (429,) or 500 <= resp.status_code < 600:
                last_err = ListingError(f"HTTP {resp.status_code}: {resp.text[:300]}")
                log.warning("retryable status %s (attempt %d)",
                            resp.status_code, attempt + 1)
            elif 200 <= resp.status_code < 300:
                return resp.json() if resp.text else {}
            else:
                # non-retryable client error -- surface eBay's message
                raise ListingError(
                    f"eBay API error HTTP {resp.status_code}: {resp.text[:500]}"
                )
        if attempt < MAX_RETRIES:
            time.sleep(2 ** attempt)
    raise ListingError(f"eBay API failed after {MAX_RETRIES + 1} attempts: {last_err}")


# --------------------------------------------------------------------------
# condition mapping
# --------------------------------------------------------------------------

#: Inventory API ConditionEnum values valid for clothing on EBAY_US
#: Note (2026-10-04): Apparel categories do NOT support USED_GOOD (5000),
#: USED_VERY_GOOD (4000), USED_ACCEPTABLE (6000). They use apparel-specific:
#: PRE_OWNED_EXCELLENT (2990), USED_EXCELLENT (3000, displays as "Pre-owned - Good"),
#: PRE_OWNED_FAIR (3010). See https://developer.ebay.com/api-docs/sell/static/metadata/condition-id-values.html
VALID_CONDITIONS = {
    "NEW", "NEW_WITH_TAGS", "LIKE_NEW", "NEW_OTHER", "NEW_WITH_DEFECTS",
    "USED_EXCELLENT", "USED_VERY_GOOD", "USED_GOOD", "USED_ACCEPTABLE",
    "PRE_OWNED_EXCELLENT", "PRE_OWNED_FAIR",
}

#: friendly / style-guide names -> ConditionEnum
CONDITION_ALIASES = {
    "new": "NEW",
    "nwt": "NEW_WITH_TAGS",
    "new with tags": "NEW_WITH_TAGS",
    "new_with_tags": "NEW_WITH_TAGS",
    "like new": "LIKE_NEW",
    "like_new": "LIKE_NEW",
    "new other": "NEW_OTHER",
    "new_other": "NEW_OTHER",
    "new with defects": "NEW_WITH_DEFECTS",
    "new_with_defects": "NEW_WITH_DEFECTS",
    "pre-owned - excellent": "PRE_OWNED_EXCELLENT",
    "preowned excellent": "PRE_OWNED_EXCELLENT",
    "pre-owned - good": "USED_EXCELLENT",
    "preowned good": "USED_EXCELLENT",
    "pre-owned - fair": "PRE_OWNED_FAIR",
    "preowned fair": "PRE_OWNED_FAIR",
    "used": "USED_EXCELLENT",
    "used excellent": "USED_EXCELLENT",
    "used very good": "USED_VERY_GOOD",
    "used good": "USED_EXCELLENT",
    "used acceptable": "PRE_OWNED_FAIR",
}

#: ConditionEnum -> display text used in the description
CONDITION_DISPLAY = {
    "NEW": "New",
    "NEW_WITH_TAGS": "New with tags",
    "LIKE_NEW": "Like new",
    "NEW_OTHER": "New other",
    "NEW_WITH_DEFECTS": "New with defects",
    "USED_EXCELLENT": "Pre-owned - Good",
    "USED_VERY_GOOD": "Pre-owned - Very Good",
    "USED_GOOD": "Pre-owned - Good",
    "USED_ACCEPTABLE": "Pre-owned - Acceptable",
    "PRE_OWNED_EXCELLENT": "Pre-owned - Excellent",
    "PRE_OWNED_FAIR": "Pre-owned - Fair",
}


def normalize_condition(value: str) -> str:
    """Map a friendly condition name to the Inventory API ConditionEnum."""
    if not value:
        raise ListingError("condition is required")
    key = str(value).strip()
    if key.upper() in VALID_CONDITIONS:
        return key.upper()
    alias = CONDITION_ALIASES.get(key.lower())
    if alias:
        return alias
    raise ListingError(
        f"Unknown condition {value!r}. Valid: {sorted(VALID_CONDITIONS)} "
        f"or friendly names like 'Pre-owned - Good', 'Used', 'NWT'."
    )


# --------------------------------------------------------------------------
# description builder (style-guide template -> basic HTML)
# --------------------------------------------------------------------------

def build_description_html(parts: dict) -> str:
    """Build the listing description HTML from style-guide parts.

    parts: {
        measurements: {pit_to_pit: 21, length: 27, shoulder: .., sleeve: ..},
        condition: <ConditionEnum or friendly>,
        condition_note: "FADED, STAINS",   # uppercase, blunt (style guide)
        extra: ["<p>...</p>", ...],          # optional extra paragraphs
    }
    """
    chunks: list[str] = []

    m = parts.get("measurements") or {}
    if m:
        segs = []
        if m.get("pit_to_pit"):
            segs.append(f"{m['pit_to_pit']} inches pit to pit")
        if m.get("length"):
            segs.append(f"{m['length']} inches top to bottom (back)")
        if m.get("shoulder"):
            segs.append(f"{m['shoulder']} inches shoulder")
        if m.get("sleeve"):
            segs.append(f"{m['sleeve']} inches sleeve")
        if segs:
            chunks.append(
                "<p><b>Seller's measurements:</b> " + ", ".join(segs) + ".</p>"
            )

    cond = parts.get("condition")
    if cond:
        enum = normalize_condition(cond)
        chunks.append(
            f"<p><b>Condition:</b> {CONDITION_DISPLAY.get(enum, enum)}</p>"
        )

    note = (parts.get("condition_note") or "").strip()
    if note:
        chunks.append(f"<p><b>Condition note:</b> {note.upper()}</p>")

    for para in parts.get("extra") or []:
        chunks.append(str(para))

    html = "\n".join(chunks)
    if len(html) > 4000:
        raise ListingError(
            f"Description exceeds eBay 4000-char limit ({len(html)} chars)."
        )
    return html


# --------------------------------------------------------------------------
# item normalization / validation
# --------------------------------------------------------------------------

def normalize_item(item_data: dict) -> dict:
    """Fill defaults and derive title/description/category for an item."""
    item = dict(item_data)  # shallow copy

    item["marketplace_id"] = marketplace_id_for(item.get("marketplace_id"))
    item["currency"] = (item.get("currency") or "USD").upper()
    item["quantity"] = int(item.get("quantity", 1))
    item["best_offer"] = bool(item.get("best_offer", True))

    if not item.get("title") and item.get("title_parts"):
        item["title"] = build_title(item["title_parts"])
    if not item.get("description") and item.get("description_parts"):
        item["description"] = build_description_html(item["description_parts"])

    cat = resolve_category(item.get("category") or item.get("category_id"))
    item["_category"] = cat
    item["_condition_enum"] = normalize_condition(item.get("condition", "USED_GOOD"))
    return item


def validate_item(item_data: dict) -> tuple[list[str], list[str]]:
    """Return (errors, warnings). Empty errors == safe to publish."""
    errors: list[str] = []
    warnings: list[str] = []
    try:
        item = normalize_item(item_data)
    except (ValueError, ListingError) as exc:
        return [str(exc)], []

    sku = str(item.get("sku") or "")
    if not sku:
        errors.append("sku is required")
    elif len(sku) > 50:
        errors.append(f"sku exceeds 50 chars ({len(sku)})")

    title = item.get("title") or ""
    if not title:
        errors.append("title is required (or title_parts to build one)")
    else:
        for issue in validate_title(title):
            (errors if "exceeds" in issue else warnings).append(f"title: {issue}")

    price = item.get("price_usd")
    try:
        if price is None or float(price) <= 0:
            errors.append("price_usd must be > 0")
    except (TypeError, ValueError):
        errors.append(f"price_usd is not a number: {price!r}")

    urls = item.get("image_urls") or []
    if not urls:
        errors.append("at least 1 image URL is required before publish")
    for u in urls:
        if not str(u).startswith("https://"):
            errors.append(f"image URL must be HTTPS: {u}")
    if len(urls) > 24:
        errors.append(f"max 24 images per listing ({len(urls)} given)")

    desc = item.get("description") or ""
    if not desc:
        errors.append("description is required before publish")
    elif len(desc) > 4000:
        errors.append(f"description exceeds 4000 chars ({len(desc)})")

    if not item["_category"].get("verified"):
        warnings.append(
            f"category {item['_category']['id']} ({item['_category']['name']}) "
            f"is not verified -- confirm in the US category tree before publish"
        )

    for pid_env in ("EBAY_PAYMENT_POLICY_ID", "EBAY_RETURN_POLICY_ID",
                    "EBAY_FULFILLMENT_POLICY_ID"):
        if not os.environ.get(pid_env):
            errors.append(f"{pid_env} env var is required (listingPolicies)")

    if item["best_offer"]:
        # bestOfferTerms is inline on the offer -- nothing extra required
        pass

    return errors, warnings


# --------------------------------------------------------------------------
# payload builders
# --------------------------------------------------------------------------

def build_inventory_item_payload(item: dict) -> dict:
    """Payload for PUT /inventory_item/{sku}."""
    aspects = {}
    for name, values in (item.get("aspects") or {}).items():
        aspects[str(name)] = [str(v) for v in values] if isinstance(values, list) else [str(values)]

    payload: dict = {
        "sku": item["sku"],
        "locale": "en-US",
        "condition": item["_condition_enum"],
        "product": {
            "title": item["title"],
            "description": item["description"],
            "imageUrls": list(item["image_urls"]),
            "aspects": aspects,
        },
        "availability": {
            "shipToLocationAvailability": {"quantity": item["quantity"]}
        },
    }
    note = (item.get("condition_note")
            or (item.get("description_parts") or {}).get("condition_note")
            or "").strip()
    if note and not item["_condition_enum"].startswith("NEW"):
        payload["conditionDescription"] = note.upper()[:1000]
    if INCLUDE_CUSTOM_LABEL and item.get("box_number"):
        payload["customLabel"] = str(item["box_number"])
    return payload


def build_offer_payload(item: dict) -> dict:
    """Payload for POST /offer."""
    price = float(item["price_usd"])
    currency = item["currency"]
    policies = {
        "paymentPolicyId": os.environ["EBAY_PAYMENT_POLICY_ID"],
        "returnPolicyId": os.environ["EBAY_RETURN_POLICY_ID"],
        "fulfillmentPolicyId": os.environ["EBAY_FULFILLMENT_POLICY_ID"],
    }
    if item["best_offer"]:
        terms: dict = {"bestOfferEnabled": True}
        if item.get("auto_accept_price"):
            terms["autoAcceptPrice"] = {
                "value": f"{float(item['auto_accept_price']):.2f}",
                "currency": currency,
            }
        if item.get("min_offer_price"):
            terms["autoDeclinePrice"] = {
                "value": f"{float(item['min_offer_price']):.2f}",
                "currency": currency,
            }
        policies["bestOfferTerms"] = terms

    return {
        "sku": item["sku"],
        "marketplaceId": item["marketplace_id"],
        "format": "FIXED_PRICE",
        "availableQuantity": item["quantity"],
        "categoryId": item["_category"]["id"],
        "listingDuration": "GTC",  # Good Till Cancelled, like the seller's listings
        # eBay ignores itemLocation in offer payloads; use a pre-registered
        # inventory location instead (Location API, e.g. KUROKUNI-WAREHOUSE).
        "merchantLocationKey": os.environ.get("EBAY_LOCATION_KEY", "KUROKUNI-WAREHOUSE"),
        "pricingSummary": {
            "price": {"value": f"{price:.2f}", "currency": currency}
        },
        "listingPolicies": policies,
    }


# --------------------------------------------------------------------------
# client
# --------------------------------------------------------------------------

class EbayListingClient:
    """Wraps the 3-step Inventory API listing flow."""

    def __init__(self, token: str | None = None,
                 marketplace_id: str | None = None,
                 dry_run: bool = False):
        self._token = token
        self.marketplace_id = marketplace_id
        self.dry_run = dry_run

    @property
    def token(self) -> str:
        if not self._token:
            self._token = get_token()
        return self._token

    # -- step 1 -----------------------------------------------------------
    def create_inventory_item(self, item: dict) -> str:
        sku = item["sku"]
        payload = build_inventory_item_payload(item)
        if self.dry_run:
            log.info("[dry-run] would PUT inventory_item/%s", sku)
            return sku
        path = f"/inventory_item/{quote(sku, safe='')}"
        try:
            _api("PUT", path, self.token, payload)
        except ListingError as exc:
            # customLabel may not exist in this API version: retry without it
            if INCLUDE_CUSTOM_LABEL and "customlabel" in str(exc).lower():
                log.warning("customLabel rejected by eBay, retrying without it")
                payload = {k: v for k, v in payload.items()
                           if k != "customLabel"}
                _api("PUT", path, self.token, payload)
            else:
                raise
        log.info("inventory item created: %s", sku)
        return sku

    # -- step 2 -----------------------------------------------------------
    def create_offer(self, item: dict) -> str:
        payload = build_offer_payload(item)
        if self.dry_run:
            log.info("[dry-run] would POST offer for sku %s", item["sku"])
            return f"DRYRUN-OFFER-{item['sku']}"
        resp = _api("POST", "/offer", self.token, payload)
        offer_id = resp.get("offerId")
        if not offer_id:
            raise ListingError(f"createOffer returned no offerId: {resp}")
        log.info("offer created: %s (sku %s)", offer_id, item["sku"])
        return offer_id

    # -- step 3 -----------------------------------------------------------
    def publish_offer(self, offer_id: str) -> str:
        if self.dry_run:
            log.info("[dry-run] would POST offer/%s/publish", offer_id)
            return f"DRYRUN-LISTING-{offer_id}"
        resp = _api("POST", f"/offer/{quote(offer_id, safe='')}/publish", self.token)
        listing_id = resp.get("listingId")
        if not listing_id:
            raise ListingError(f"publishOffer returned no listingId: {resp}")
        log.info("offer published: %s -> listing %s", offer_id, listing_id)
        return listing_id

    # -- full flow ---------------------------------------------------------
    def create_listing(self, item_data: dict) -> dict:
        """Run validate -> inventory item -> offer -> publish.

        Returns {"sku", "offer_id", "listing_id", "title", "marketplace_id"}.
        With dry_run=True no HTTP is made; returns payload previews instead.
        """
        item = normalize_item(item_data)
        if self.marketplace_id:
            item["marketplace_id"] = self.marketplace_id

        errors, warnings = validate_item(item)
        for w in warnings:
            log.warning("sku %s: %s", item.get("sku"), w)
        if errors:
            raise ListingError(
                f"validation failed for sku {item.get('sku')}: " + "; ".join(errors)
            )

        if self.dry_run:
            return {
                "dry_run": True,
                "sku": item["sku"],
                "title": item["title"],
                "marketplace_id": item["marketplace_id"],
                "warnings": warnings,
                "payloads": {
                    "inventory_item": build_inventory_item_payload(item),
                    "offer": build_offer_payload(item),
                },
            }

        sku = self.create_inventory_item(item)
        offer_id = self.create_offer(item)
        listing_id = self.publish_offer(offer_id)
        return {
            "sku": sku,
            "offer_id": offer_id,
            "listing_id": listing_id,
            "title": item["title"],
            "marketplace_id": item["marketplace_id"],
        }


def create_listing(item_data: dict, token: str | None = None,
                   dry_run: bool = False,
                   marketplace_id: str | None = None) -> dict:
    """Convenience wrapper: full 3-step flow for one item."""
    return EbayListingClient(token=token, dry_run=dry_run,
                             marketplace_id=marketplace_id).create_listing(item_data)
