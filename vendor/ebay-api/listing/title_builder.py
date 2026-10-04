"""Title builder for myvintage73 eBay listings.

Implements the seller's title formula from
~/workspace/ebay-listing/style-guide.md ::

    VINTAGE [era] [brand/team] [descriptors...] [item type] [SZ size] [tail tags]

Rules enforced:
  * always starts with ``VINTAGE``
  * ALL CAPS (digits / symbols allowed)
  * era token directly after VINTAGE:
      1950-1999 -> two digits + apostrophe (90', 92')
      2000+     -> full year (2001) -- NEVER 01'
      2000s generic -> Y2K
  * ``SZ <size>`` sits near the end of the title
  * max 80 chars (eBay hard limit); over-long titles are shortened by
    dropping middle descriptors first
"""

from __future__ import annotations

import re

MAX_TITLE_LEN = 80

_ERA_TOKEN_RE = re.compile(r"^(\d{2}'|Y2K|\d{4})$")


def format_era(era) -> str:
    """Normalize an era value to the style-guide token.

    Accepts:
      * int year, e.g. 1992 -> ``92'`` ; 2001 -> ``2001``
      * int decade, e.g. 1990 -> ``90'``
      * two-digit int, e.g. 90 -> ``90'``
      * str already in style-guide form: ``"90'"``, ``"Y2K"``, ``"2001"``
      * None -> ``""`` (no era token; used for hats/bags/unknown era)
    """
    if era is None or era == "":
        return ""
    if isinstance(era, bool):
        return ""
    if isinstance(era, int):
        if 0 <= era < 100:          # two-digit shorthand -> 1900s
            return f"{era:02d}'"
        if 1950 <= era <= 1999:     # 90' style
            return f"{era % 100:02d}'"
        return str(era)             # 2000+ -> full year, never 01'
    s = str(era).strip().upper()
    # tolerate "1990s"/"90s" style input
    m = re.fullmatch(r"(\d{2}|\d{4})S", s)
    if m:
        return format_era(int(m.group(1)))
    if re.fullmatch(r"0\d'", s):
        # 00'-09' is ambiguous (1900s vs 2000s); style guide bans 01' style
        # for 2000s items -- use the full year (2001) instead.
        raise ValueError(
            f"Ambiguous era token {s!r}: use a full year like '2001' "
            f"(style guide bans 01'-style for the 2000s)."
        )
    if _ERA_TOKEN_RE.fullmatch(s):
        return s
    raise ValueError(f"Unrecognized era value: {era!r}")


def build_title(parts: dict) -> str:
    """Build a title from parts dict.

    parts keys:
        era            int/str/None  (see format_era)
        condition_flag str, e.g. "NWT" (placed right after era)
        brand          str, e.g. "PHANTOM OF THE OPERA"
        descriptors    list[str], e.g. ["SINGLE STITCH", "WHITE", "COTTON"]
        item_type      str, e.g. "T-SHIRT" / "JERSEY" / "SNAPBACK HAT"
        size           str, e.g. "XLARGE" / "40" / "7 5/8"
        size_prefix    str, default "SZ" (use "" for ONE SIZE hats)
        tail           list[str], trailing tags e.g. ["MADE IN USA"]
    """
    tokens = ["VINTAGE"]

    era = format_era(parts.get("era"))
    if era:
        tokens.append(era)

    flag = (parts.get("condition_flag") or "").strip().upper()
    if flag:
        tokens.append(flag)

    brand = (parts.get("brand") or "").strip().upper()
    if brand:
        tokens.append(brand)

    item_type = (parts.get("item_type") or "").strip().upper()

    size = (parts.get("size") or "").strip().upper()
    if size:
        prefix = parts.get("size_prefix", "SZ").strip().upper()
        size_token = f"{prefix} {size}".strip() if prefix else size
    else:
        size_token = ""

    tail_tokens: list[str] = []
    for t in parts.get("tail") or []:
        t = str(t).strip().upper()
        if t:
            tail_tokens.append(t)

    head = tokens  # VINTAGE [era] [flag] [brand...]
    desc_tokens: list[str] = []
    for d in parts.get("descriptors") or []:
        d = str(d).strip().upper()
        if d:
            desc_tokens.append(d)

    end: list[str] = []
    if item_type:
        end.append(item_type)
    if size_token:
        end.append(size_token)
    end.extend(tail_tokens)

    def assemble() -> str:
        return " ".join(head + desc_tokens + end)

    title = assemble()
    if len(title) > MAX_TITLE_LEN and desc_tokens:
        # Style guide: over-long titles drop trailing descriptors first.
        # Brand / era / flag / item type / size are never dropped here.
        while desc_tokens and len(assemble()) > MAX_TITLE_LEN:
            desc_tokens.pop()
        title = assemble()
    return shorten_title(title, MAX_TITLE_LEN)


def validate_title(title: str) -> list[str]:
    """Return a list of style-guide violations (empty == clean)."""
    issues: list[str] = []
    if not title:
        return ["title is empty"]
    if not title.startswith("VINTAGE"):
        issues.append("must start with VINTAGE")
    if any(ch.islower() for ch in title):
        issues.append("must be ALL CAPS")
    if len(title) > MAX_TITLE_LEN:
        issues.append(f"exceeds {MAX_TITLE_LEN} chars ({len(title)})")
    tokens = title.split()
    if len(tokens) > 1 and not _ERA_TOKEN_RE.fullmatch(tokens[1]):
        # token[1] may be a condition flag (NWT/DEADSTOCK) or brand when no era;
        # only flag it if it looks like neither
        if tokens[1] not in {"NWT", "DEADSTOCK", "MINT", "MINTY"}:
            issues.append(
                f"expected era token right after VINTAGE, found {tokens[1]!r}"
            )
    # SZ should sit in the last 3 tokens (or title ends with a size-like token)
    if "SZ" in tokens:
        sz_idx = len(tokens) - 1 - tokens[::-1].index("SZ")
        if sz_idx < len(tokens) - 3:
            issues.append("SZ size marker should be near the end of the title")
    return issues


def shorten_title(title: str, max_len: int = MAX_TITLE_LEN) -> str:
    """Shorten a raw title string to ``max_len``.

    Standalone fallback (no zone info): protects the first 3 and last 3
    tokens (VINTAGE + era/flag ... item type + SZ size) and drops the
    longest middle token iteratively. Prefer ``build_title``, which drops
    trailing descriptors with full zone knowledge.
    """
    title = " ".join(title.split())
    if len(title) <= max_len:
        return title
    tokens = title.split()
    # protected zones: first 3 tokens, last 3 tokens
    while len(" ".join(tokens)) > max_len:
        if len(tokens) <= 6:
            break  # nothing safe left to drop; hard truncate below
        middle = tokens[3:-3]
        if not middle:
            break
        drop = max(middle, key=len)
        tokens.remove(drop)
    result = " ".join(tokens)
    return result[:max_len].rstrip() if len(result) > max_len else result
