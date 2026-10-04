"""eBay category ID map for myvintage73 (vintage clothing, EBAY_US tree).

Marketplace decision (documented 2026-10-03):
  * The seller is registered in Canada but lists in USD on ebay.com.
  * ``marketplaceId`` on the offer selects the *listing site*, not the
    seller's registration country. A Canadian seller CAN list on ebay.com
    via the EBAY_US marketplace with USD prices (standard cross-border
    selling; eBay converts/shows the listing on ebay.com).
  * Using EBAY_CA would put the listing on ebay.ca priced in CAD --
    wrong for this seller. Hence the default is EBAY_US and category IDs
    below come from the US category tree.
  * Override per run: env EBAY_MARKETPLACE_ID, or ``marketplace_id`` in
    item data / CLI ``--marketplace``.

Category IDs marked ``verified: True`` were confirmed on 2026-10-03 from
live eBay browse-page URLs (``/b/<slug>/<id>/``). IDs marked
``verified: False`` are best-known values from the eBay category tree and
MUST be re-checked at connection test time (see README "연결 테스트").
Any numeric category ID can also be passed directly per item.
"""

from __future__ import annotations

import os

DEFAULT_MARKETPLACE_ID = os.environ.get("EBAY_MARKETPLACE_ID", "EBAY_US")

#: Human-friendly key -> {id, name, verified}
CATEGORIES: dict[str, dict] = {
    # ---- verified 2026-10-03 via ebay.com browse URLs ----
    "tshirt": {
        "id": "15687",
        "name": "Men's T-Shirts",
        "verified": True,
    },
    "hoodie": {
        "id": "155183",
        "name": "Men's Hoodies & Sweatshirts",
        "verified": True,
    },
    "jacket": {
        "id": "57988",
        "name": "Men's Coats, Jackets & Vests",
        "verified": True,
    },
    "jersey": {
        "id": "24510",
        "name": "Hockey-NHL Fan Apparel & Souvenirs",
        "verified": True,
        "note": "NHL node; other leagues (NFL/MLB/NBA) need their own "
                "fan-apparel node IDs -- verify before use.",
    },
    "bag": {
        "id": "74962",
        "name": "Vintage Bags, Handbags & Cases",
        "verified": True,
        "note": "Under Collectibles > Vintage Accessories; fits the "
                "seller's vintage Coach/Fendi bags.",
    },
    # ---- best-known, VERIFY at connection test ----
    "hat": {
        "id": "52365",
        "name": "Men's Hats",
        "verified": False,
    },
}

#: alias -> canonical key
ALIASES: dict[str, str] = {
    "t-shirt": "tshirt",
    "tee": "tshirt",
    "sweatshirt": "hoodie",
    "crewneck": "hoodie",
    "coat": "jacket",
    "parka": "jacket",
    "vest": "jacket",
    "denim_jacket": "jacket",
    "jersey_hockey": "jersey",
    "hockey_jersey": "jersey",
    "handbag": "bag",
    "purse": "bag",
    "shoulder_bag": "bag",
    "cap": "hat",
    "snapback": "hat",
    "fitted": "hat",
    "beanie": "hat",
}


def resolve_category(key_or_id) -> dict:
    """Resolve a category key/alias or raw numeric ID to a category entry.

    Returns ``{"id": ..., "name": ..., "verified": bool}``.
    Raises ValueError for unknown keys.
    """
    if key_or_id is None:
        raise ValueError("category is required (key like 'tshirt' or numeric id)")
    s = str(key_or_id).strip().lower()
    if s.isdigit():
        for entry in CATEGORIES.values():  # raw ID that matches a known category
            if entry["id"] == s:
                return dict(entry)
        return {"id": s, "name": f"custom:{s}", "verified": False}
    key = ALIASES.get(s, s)
    if key in CATEGORIES:
        return dict(CATEGORIES[key])
    known = sorted(set(CATEGORIES) | set(ALIASES))
    raise ValueError(
        f"Unknown category key {key_or_id!r}. Known keys: {', '.join(known)} "
        f"(or pass a raw numeric eBay category ID)."
    )


def marketplace_id_for(item_marketplace: str | None = None) -> str:
    """Effective marketplaceId: item override > env > EBAY_US default."""
    return item_marketplace or DEFAULT_MARKETPLACE_ID
