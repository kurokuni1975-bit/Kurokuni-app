"""eBay listing package — Sell Inventory API based bulk listing.

Modules:
    title_builder   Style-guide based title generation / validation
                    (~/workspace/ebay-listing/style-guide.md)
    category_map    eBay category IDs for vintage clothing (EBAY_US tree)
    listing         3-step flow: createInventoryItem -> createOffer -> publishOffer
    bulk            CSV/JSON bulk registration with failure log
    main            CLI entry point: python -m listing.main --file items.json [--dry-run]
"""

from .listing import EbayListingClient, ListingError, create_listing  # noqa: F401
from .title_builder import build_title, validate_title, format_era  # noqa: F401
from .category_map import resolve_category, CATEGORIES  # noqa: F401

__all__ = [
    "EbayListingClient",
    "ListingError",
    "create_listing",
    "build_title",
    "validate_title",
    "format_era",
    "resolve_category",
    "CATEGORIES",
]
