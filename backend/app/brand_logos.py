"""Brand logos, from Wikidata to Wikimedia Commons.

Idea 3 wanted pictures of the places. Photographs are not in this data - 20 of
21,280 OSM elements carry an `image` tag, and the providers that do have photos
are paid, uncacheable, or forbid storing what they return. Logos are: 601
distinct `brand:wikidata` ids cover 4,077 outlets, and Wikidata and Commons are
free and keyless to query for this optional identity layer.

This buys visual identity for the chains only. A hawker stall has no logo and
never will, so the interface must treat a missing one as the ordinary case
rather than as a hole - see the category glyph on the client.

Two things about the route taken here.

Wikimedia's `api.php` refuses this client outright (403, their bot policy), so
the entity comes from `Special:EntityData/<QID>.json`, which is the documented
stable route and answers 200. And a Commons file's URL is *derived*, not looked
up: the path is the first one and two hex digits of the MD5 of the underscored
file name. That is a published rule rather than a guess, and it means no second
request per logo - 601 requests for the whole catalogue instead of 1,202.

Licensing and attribution vary by Commons file. The database deliberately keeps
the original Commons file name beside the derived URL, preserving enough
provenance to identify the source file/page and inspect its individual terms
later. The application makes no blanket licensing claim for all logo files.
"""

from __future__ import annotations

import hashlib
import urllib.parse
from typing import Any

WIKIDATA_ENTITY_URL = "https://www.wikidata.org/wiki/Special:EntityData/{qid}.json"
COMMONS_UPLOAD_BASE = "https://upload.wikimedia.org/wikipedia/commons"

ATTRIBUTION = "Brand logos via Wikidata and Wikimedia Commons"

# Not decoration. Wikimedia answers 403 to a terse User-Agent and 200 to the
# same request carrying a contact URL - measured, both routes. Browsers send
# their own and are unaffected, so this governs ingestion, not the page.
USER_AGENT = "along-sg/0.8 (https://github.com/wenhaoyay/along-sg)"

# P154 is the logo proper. P8972 is the small/icon variant, taken only when
# there is no P154, because it is often a monogram that identifies less.
LOGO_PROPERTIES = ("P154", "P8972")

# Raster formats a browser can draw. Commons also holds TIFF, XCF and PDF, and
# an <img> pointing at one of those renders as a broken image.
RENDERABLE_SUFFIXES = (".svg", ".png", ".jpg", ".jpeg", ".gif", ".webp")


def commons_file_url(file_name: str) -> str:
    """The direct URL of a Commons file, derived rather than looked up.

    Commons shards uploads by the MD5 of the file name with spaces as
    underscores: the first hex digit, then the first two. Published, stable,
    and the reason this needs no second request per logo.
    """
    underscored = file_name.replace(" ", "_")
    digest = hashlib.md5(underscored.encode("utf-8")).hexdigest()
    quoted = urllib.parse.quote(underscored)
    return f"{COMMONS_UPLOAD_BASE}/{digest[0]}/{digest[:2]}/{quoted}"


def _claim_value(claims: dict[str, Any], prop: str) -> str | None:
    for statement in claims.get(prop) or ():
        if not isinstance(statement, dict):
            continue
        # A claim can be deprecated, or present with no value at all - both are
        # ordinary on Wikidata and neither is a file name.
        if statement.get("rank") == "deprecated":
            continue
        snak = statement.get("mainsnak") or {}
        if snak.get("snaktype") != "value":
            continue
        value = (snak.get("datavalue") or {}).get("value")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def logo_file_name(entity: dict[str, Any]) -> str | None:
    """The best logo file on one Wikidata entity, or nothing."""
    claims = entity.get("claims")
    if not isinstance(claims, dict):
        return None
    for prop in LOGO_PROPERTIES:
        value = _claim_value(claims, prop)
        if value and value.lower().endswith(RENDERABLE_SUFFIXES):
            return value
    return None


def entity_label(entity: dict[str, Any]) -> str | None:
    labels = entity.get("labels")
    if not isinstance(labels, dict):
        return None
    entry = labels.get("en")
    if isinstance(entry, dict):
        value = entry.get("value")
        return value.strip() if isinstance(value, str) and value.strip() else None
    return None


def resolve_entity_payload(payload: dict[str, Any], qid: str) -> dict[str, Any] | None:
    """Resolve one requested QID from an EntityData payload without guessing.

    A direct entity is accepted. Wikidata redirects/merges can answer under a
    different key, which is safe only when exactly one entity object is present.
    Anything else is a parsing/resolution failure and must not be interpreted as
    evidence that an existing logo was removed.
    """
    entities = payload.get("entities")
    if not isinstance(entities, dict):
        return None
    entity = entities.get(qid)
    if isinstance(entity, dict):
        return entity
    values = [item for item in entities.values() if isinstance(item, dict)]
    return values[0] if len(values) == 1 else None


def parse_entity_payload(payload: dict[str, Any], qid: str) -> dict[str, Any] | None:
    """One resolvable EntityData response into a storable row, or nothing."""
    entity = resolve_entity_payload(payload, qid)
    if entity is None:
        return None
    file_name = logo_file_name(entity)
    if not file_name:
        return None
    return {
        "wikidata_id": qid,
        "brand_label": entity_label(entity),
        "file_name": file_name,
        "url": commons_file_url(file_name),
    }
