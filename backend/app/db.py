from __future__ import annotations

import sqlite3
from datetime import datetime
from math import cos, radians, sqrt
from pathlib import Path
from typing import Any, Iterable

from app.domain import Coordinate, Hub, Store
from app.poi_taxonomy import BRAND_ALIASES, CATEGORIES, canonical_brand, normalize_text


def _seed_distance_km(
    latitude: float, longitude: float, other: tuple[float, float]
) -> float:
    """Great-circle kilometres, used only to decide whether two hub rows are the
    same building. Kept local so ingestion does not import a provider."""
    from math import asin, sin

    lat1, lon1 = radians(latitude), radians(longitude)
    lat2, lon2 = radians(other[0]), radians(other[1])
    inner = (
        sin((lat2 - lat1) / 2) ** 2
        + cos(lat1) * cos(lat2) * sin((lon2 - lon1) / 2) ** 2
    )
    return 2 * 6371.0088 * asin(sqrt(inner))


HUB_SEED = (
    (1, "Waterway Point", 1.4067, 103.9023, "mall", "punggol-station", "waterway-point"),
    (2, "NEX Serangoon", 1.3509, 103.8488, "mall", "serangoon-station", "nex"),
    (3, "Plaza Singapura", 1.3006, 103.8452, "mall", "dhoby-ghaut-station", "plaza-singapura"),
    (4, "ION Orchard", 1.3040, 103.8318, "mall", "orchard-station", "ion-orchard"),
    (5, "Tampines Mall", 1.3526, 103.9447, "mall", "tampines-station", "tampines-mall"),
    (6, "Jurong Point", 1.3397, 103.7068, "mall", "boon-lay-station", "jurong-point"),
    (7, "Bugis Junction", 1.2997, 103.8550, "mall", "bugis-station", "bugis-junction"),
    (8, "VivoCity", 1.2643, 103.8223, "mall", "harbourfront-station", "vivocity"),
    (9, "Lot One", 1.3851, 103.7449, "mall", "choa-chu-kang-station", "lot-one"),
    (10, "Toa Payoh HDB Hub", 1.3320, 103.8483, "station_area", "toa-payoh-station", "toa-payoh-hdb-hub"),
    (11, "313@Somerset", 1.3010, 103.8385, "mall", "somerset-station", "313-somerset"),
    (12, "Northpoint City", 1.4295, 103.8354, "mall", "yishun-station", "northpoint-city"),
)

OUTLET_SEED = (
    (1, 1, "FairPrice Finest", "groceries"), (2, 1, "Guardian", "pharmacy"),
    (3, 1, "POPStation", "parcel"), (4, 2, "FairPrice Xtra", "groceries"),
    (5, 2, "Watsons", "pharmacy"), (6, 2, "POPStation", "parcel"),
    (7, 2, "Challenger", "electronics"), (8, 3, "Cold Storage", "groceries"),
    (9, 3, "Guardian", "pharmacy"), (10, 3, "Challenger", "electronics"),
    (11, 4, "CS Fresh", "groceries"), (12, 4, "Guardian", "pharmacy"),
    (13, 5, "FairPrice", "groceries"), (14, 5, "Watsons", "pharmacy"),
    (15, 5, "SingPost POPStation", "parcel"), (16, 6, "FairPrice Xtra", "groceries"),
    (17, 6, "Guardian", "pharmacy"), (18, 6, "Challenger", "electronics"),
    (19, 7, "Cold Storage", "groceries"), (20, 7, "Watsons", "pharmacy"),
    (21, 7, "SingPost", "parcel"), (22, 8, "FairPrice Xtra", "groceries"),
    (23, 8, "Guardian", "pharmacy"), (24, 8, "Best Denki", "electronics"),
    (25, 9, "FairPrice", "groceries"), (26, 9, "Watsons", "pharmacy"),
    (27, 10, "FairPrice", "groceries"), (28, 10, "Guardian", "pharmacy"),
    (29, 10, "SingPost", "parcel"), (30, 10, "DBS/POSB", "banking"),
)

BRAND_CATEGORY_SEED = {
    "7-eleven": ("convenience",), "cheers": ("convenience", "coffee"),
    "cold-storage": ("groceries",), "dbs-posb": ("banking",),
    "fairprice": ("groceries", "convenience"),
    "guardian": ("pharmacy", "convenience"),
    "jollibee": ("fast_food", "fried_chicken"),
    "kfc": ("fast_food", "fried_chicken"), "koi-the": ("bubble_tea", "coffee"),
    "liho-tea": ("bubble_tea", "coffee"), "mcdonalds": ("fast_food",),
    "mr-coconut": ("bubble_tea", "fast_food", "coffee"),
    "ocbc": ("banking",), "popeyes": ("fast_food", "fried_chicken"),
    "singpost": ("parcel",), "starbucks": ("coffee",),
    "subway": ("fast_food",), "texas-chicken": ("fast_food", "fried_chicken"),
    "toast-box": ("coffee",), "uob": ("banking",), "watsons": ("pharmacy",),
}


class HubRepository:
    def __init__(self, path: Path):
        self.path = path

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS hubs (
                    id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE,
                    latitude REAL NOT NULL, longitude REAL NOT NULL,
                    semantic_type TEXT NOT NULL DEFAULT 'standalone',
                    transport_area_id TEXT, consolidation_group_id TEXT,
                    source TEXT NOT NULL DEFAULT 'curated', source_id TEXT,
                    last_verified_at TEXT, opening_hours TEXT,
                    closure_status TEXT NOT NULL DEFAULT 'unknown',
                    transport_node_distance_m REAL, address TEXT
                );
                CREATE TABLE IF NOT EXISTS brands (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, slug TEXT NOT NULL UNIQUE,
                    canonical_name TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS brand_aliases (
                    alias_normalized TEXT PRIMARY KEY,
                    brand_id INTEGER NOT NULL REFERENCES brands(id)
                );
                CREATE TABLE IF NOT EXISTS brand_categories (
                    brand_id INTEGER NOT NULL REFERENCES brands(id),
                    category_slug TEXT NOT NULL REFERENCES categories(slug),
                    PRIMARY KEY(brand_id, category_slug)
                );
                CREATE TABLE IF NOT EXISTS categories (
                    slug TEXT PRIMARY KEY, name TEXT NOT NULL,
                    parent_slug TEXT REFERENCES categories(slug)
                );
                CREATE TABLE IF NOT EXISTS outlets (
                    id INTEGER PRIMARY KEY, hub_id INTEGER NOT NULL REFERENCES hubs(id),
                    name TEXT NOT NULL, category TEXT NOT NULL,
                    brand_id INTEGER REFERENCES brands(id),
                    source TEXT NOT NULL DEFAULT 'curated', source_id TEXT,
                    last_verified_at TEXT, opening_hours TEXT,
                    closure_status TEXT NOT NULL DEFAULT 'unknown',
                    original_name TEXT, alt_names TEXT, cuisine TEXT,
                    shop TEXT, amenity TEXT, search_metadata TEXT,
                    UNIQUE(hub_id, name, category)
                );
                CREATE TABLE IF NOT EXISTS outlet_categories (
                    outlet_id INTEGER NOT NULL REFERENCES outlets(id) ON DELETE CASCADE,
                    category_slug TEXT NOT NULL REFERENCES categories(slug),
                    PRIMARY KEY(outlet_id, category_slug)
                );
                CREATE TABLE IF NOT EXISTS transport_nodes (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL,
                    latitude REAL NOT NULL, longitude REAL NOT NULL,
                    node_type TEXT NOT NULL, source TEXT NOT NULL,
                    source_id TEXT NOT NULL, last_verified_at TEXT,
                    UNIQUE(source, source_id)
                );
                -- The static bus network, keyed on LTA's five-digit stop code -
                -- the same code OneMap returns on every bus leg, which is what
                -- makes an arrival lookup a join rather than a guess.
                CREATE TABLE IF NOT EXISTS bus_stops (
                    stop_code TEXT PRIMARY KEY,
                    road_name TEXT, description TEXT,
                    latitude REAL NOT NULL, longitude REAL NOT NULL,
                    last_verified_at TEXT
                );
                CREATE TABLE IF NOT EXISTS bus_routes (
                    service_no TEXT NOT NULL,
                    direction INTEGER NOT NULL,
                    stop_sequence INTEGER NOT NULL,
                    stop_code TEXT NOT NULL,
                    operator TEXT, distance_km REAL,
                    weekday_first TEXT, weekday_last TEXT,
                    saturday_first TEXT, saturday_last TEXT,
                    sunday_first TEXT, sunday_last TEXT,
                    last_verified_at TEXT,
                    PRIMARY KEY (service_no, direction, stop_sequence)
                );
                CREATE INDEX IF NOT EXISTS idx_bus_routes_stop ON bus_routes(stop_code);
                """
            )
            self._migrate_columns(connection, "hubs", {
                "semantic_type": "TEXT NOT NULL DEFAULT 'standalone'",
                "transport_area_id": "TEXT", "consolidation_group_id": "TEXT",
                "source": "TEXT NOT NULL DEFAULT 'curated'", "source_id": "TEXT",
                "last_verified_at": "TEXT", "opening_hours": "TEXT",
                "closure_status": "TEXT NOT NULL DEFAULT 'unknown'",
                "transport_node_distance_m": "REAL",
                "address": "TEXT",
            })
            self._migrate_columns(connection, "outlets", {
                "brand_id": "INTEGER REFERENCES brands(id)",
                "source": "TEXT NOT NULL DEFAULT 'curated'", "source_id": "TEXT",
                "last_verified_at": "TEXT", "opening_hours": "TEXT",
                "closure_status": "TEXT NOT NULL DEFAULT 'unknown'",
                "original_name": "TEXT", "alt_names": "TEXT", "cuisine": "TEXT",
                "shop": "TEXT", "amenity": "TEXT", "search_metadata": "TEXT",
            })
            connection.executescript(
                """
                CREATE INDEX IF NOT EXISTS idx_outlets_category ON outlets(category);
                CREATE INDEX IF NOT EXISTS idx_outlets_name_nocase ON outlets(name COLLATE NOCASE);
                CREATE INDEX IF NOT EXISTS idx_brands_name_nocase ON brands(canonical_name COLLATE NOCASE);
                CREATE INDEX IF NOT EXISTS idx_categories_name_nocase ON categories(name COLLATE NOCASE);
                CREATE INDEX IF NOT EXISTS idx_outlet_categories_category ON outlet_categories(category_slug);
                CREATE INDEX IF NOT EXISTS idx_hubs_coordinate ON hubs(latitude, longitude);
                CREATE INDEX IF NOT EXISTS idx_hubs_transport_area ON hubs(transport_area_id);
                CREATE UNIQUE INDEX IF NOT EXISTS idx_hubs_source_id ON hubs(source, source_id) WHERE source_id IS NOT NULL;
                CREATE UNIQUE INDEX IF NOT EXISTS idx_outlets_source_id ON outlets(source, source_id) WHERE source_id IS NOT NULL;
                CREATE VIRTUAL TABLE IF NOT EXISTS outlet_search USING fts5(
                    outlet_id UNINDEXED, name, brand, aliases, categories, cuisine,
                    shop, amenity, hub, address, metadata,
                    tokenize='unicode61 remove_diacritics 2'
                );
                """
            )
            self._seed_taxonomy(connection)
            self._seed_curated_data(connection)
            self._rebuild_search_index(connection)

    @staticmethod
    def _migrate_columns(connection: sqlite3.Connection, table: str, definitions: dict[str, str]) -> None:
        existing = {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
        for column, definition in definitions.items():
            if column not in existing:
                connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    @staticmethod
    def _seed_taxonomy(connection: sqlite3.Connection) -> None:
        connection.executemany(
            "INSERT OR IGNORE INTO categories(slug, name, parent_slug) VALUES (?, ?, ?)",
            ((item.slug, item.name, item.parent_slug) for item in CATEGORIES),
        )
        connection.executemany(
            """INSERT INTO brands(slug, canonical_name) VALUES (?, ?)
               ON CONFLICT(slug) DO UPDATE SET canonical_name=excluded.canonical_name""",
            sorted(set(BRAND_ALIASES.values())),
        )
        brand_ids = dict(connection.execute("SELECT slug, id FROM brands"))
        connection.executemany(
            "INSERT OR REPLACE INTO brand_aliases(alias_normalized, brand_id) VALUES (?, ?)",
            ((alias, brand_ids[slug]) for alias, (slug, _) in BRAND_ALIASES.items()),
        )
        connection.executemany(
            "INSERT OR IGNORE INTO brand_categories(brand_id, category_slug) VALUES (?, ?)",
            (
                (brand_ids[slug], category)
                for slug, categories in BRAND_CATEGORY_SEED.items()
                for category in categories
            ),
        )

    @staticmethod
    def _seed_curated_data(connection: sqlite3.Connection) -> None:
        # The seed bootstraps an empty catalog and runs again on every startup.
        # Once ingestion has superseded a seed hub with the real thing, that
        # name belongs to the ingested row, so re-seeding it would collide with
        # UNIQUE(hubs.name) and take the whole server down at startup.
        superseded = {
            row[0] for row in connection.execute(
                "SELECT name FROM hubs WHERE source<>'curated'"
            )
        }
        seed_hubs = [row for row in HUB_SEED if row[1] not in superseded]
        connection.executemany(
            """
            INSERT INTO hubs(id, name, latitude, longitude, semantic_type,
                transport_area_id, consolidation_group_id, source, closure_status)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'curated', 'open')
            ON CONFLICT(id) DO UPDATE SET name=excluded.name,
                latitude=excluded.latitude, longitude=excluded.longitude,
                semantic_type=excluded.semantic_type,
                transport_area_id=excluded.transport_area_id,
                consolidation_group_id=excluded.consolidation_group_id
            """,
            seed_hubs,
        )
        seeded_hub_ids = {row[0] for row in seed_hubs}
        seed_outlets = [row for row in OUTLET_SEED if row[1] in seeded_hub_ids]
        connection.executemany(
            """
            INSERT OR IGNORE INTO outlets(id, hub_id, name, category, source, closure_status)
            VALUES (?, ?, ?, ?, 'curated', 'open')
            """,
            seed_outlets,
        )
        brand_ids = dict(connection.execute("SELECT slug, id FROM brands"))
        # Only the outlets that were actually seeded - outlet_categories has a
        # foreign key onto outlets(id), so the skipped ones would fail here.
        for outlet_id, _hub_id, name, category in seed_outlets:
            slug, _ = canonical_brand(name)
            if slug:
                connection.execute("UPDATE outlets SET brand_id=? WHERE id=?", (brand_ids[slug], outlet_id))
            connection.execute(
                "INSERT OR IGNORE INTO outlet_categories(outlet_id, category_slug) VALUES (?, ?)",
                (outlet_id, category),
            )

    def count_outlets(self, active_only: bool = True) -> int:
        where = "WHERE closure_status != 'closed'" if active_only else ""
        with self._connect() as connection:
            return int(connection.execute(f"SELECT COUNT(*) FROM outlets {where}").fetchone()[0])

    def category_catalog(self) -> tuple[str, ...]:
        with self._connect() as connection:
            return tuple(
                row[0] for row in connection.execute(
                    """SELECT c.slug FROM categories c
                       WHERE NOT EXISTS (
                           SELECT 1 FROM categories child WHERE child.parent_slug=c.slug
                       ) ORDER BY c.slug"""
                )
            )

    def category_catalog_entries(self) -> tuple[dict[str, Any], ...]:
        """Return the live, populated taxonomy used by consumer discovery."""
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT c.slug, c.name, c.parent_slug,
                       COUNT(DISTINCT CASE WHEN o.closure_status != 'closed' THEN o.id END)
                FROM categories c
                LEFT JOIN outlet_categories oc ON oc.category_slug=c.slug
                LEFT JOIN outlets o ON o.id=oc.outlet_id
                GROUP BY c.slug, c.name, c.parent_slug
                ORDER BY c.parent_slug IS NOT NULL, c.parent_slug, c.name
                """
            ).fetchall()
        entries = {
            row[0]: {"slug": row[0], "name": row[1], "parent_slug": row[2],
                     "outlet_count": int(row[3])}
            for row in rows
        }
        for entry in entries.values():
            if entry["outlet_count"] == 0:
                entry["outlet_count"] = sum(
                    int(child["outlet_count"]) for child in entries.values()
                    if child["parent_slug"] == entry["slug"]
                )
        return tuple(entry for entry in entries.values() if entry["outlet_count"] > 0)

    def brand_catalog(self) -> tuple[dict[str, Any], ...]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT b.slug, b.canonical_name,
                       GROUP_CONCAT(DISTINCT ba.alias_normalized),
                       GROUP_CONCAT(DISTINCT COALESCE(oc.category_slug, bc.category_slug)),
                       COUNT(DISTINCT o.id)
                FROM brands b
                LEFT JOIN outlets o ON o.brand_id=b.id AND o.closure_status != 'closed'
                LEFT JOIN brand_aliases ba ON ba.brand_id=b.id
                LEFT JOIN outlet_categories oc ON oc.outlet_id=o.id
                LEFT JOIN brand_categories bc ON bc.brand_id=b.id
                GROUP BY b.id ORDER BY b.canonical_name
                """
            ).fetchall()
        return tuple({
            "slug": row[0], "canonical_name": row[1],
            "aliases": tuple(filter(None, (row[2] or "").split(","))),
            "categories": tuple(filter(None, (row[3] or "").split(","))),
            "outlet_count": int(row[4]),
        } for row in rows)

    def search_catalog(
        self, query: str = "", category: str | None = None, limit: int = 20,
    ) -> tuple[dict[str, Any], ...]:
        """Search canonical chains and independent named POIs without exposing IDs."""
        needle = normalize_text(query)
        category_matches: list[dict[str, Any]] = []
        if not category:
            for entry in self.category_catalog_entries():
                if not needle or needle in normalize_text(entry["name"]) or needle in normalize_text(entry["slug"]):
                    category_matches.append({
                        "display_name": entry["name"], "kind": "category",
                        "canonical_brand": None, "categories": (entry["slug"],),
                        "outlet_count": entry["outlet_count"], "example_location": None,
                    })
            category_matches.sort(key=lambda item: (
                0 if normalize_text(item["display_name"]) == needle else 1,
                -int(item["outlet_count"]), item["display_name"],
            ))
        like = f"%{needle}%"
        category_clause = "AND oc.category_slug=?" if category else ""
        params: list[Any] = [needle, like, like, like]
        if category:
            params.append(category)
        params.extend((needle, max(1, min(limit, 50))))
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT COALESCE(b.canonical_name, o.name) AS display_name,
                       CASE WHEN b.id IS NULL THEN 'place' ELSE 'brand' END AS kind,
                       b.canonical_name,
                       GROUP_CONCAT(DISTINCT oc.category_slug),
                       COUNT(DISTINCT o.id),
                       MIN(h.name)
                FROM outlets o
                JOIN hubs h ON h.id=o.hub_id
                LEFT JOIN brands b ON b.id=o.brand_id
                LEFT JOIN brand_aliases ba ON ba.brand_id=b.id
                JOIN outlet_categories oc ON oc.outlet_id=o.id
                WHERE o.closure_status != 'closed' AND h.closure_status != 'closed'
                  AND (?='' OR LOWER(COALESCE(b.canonical_name, '')) LIKE ?
                       OR LOWER(o.name) LIKE ? OR LOWER(COALESCE(ba.alias_normalized, '')) LIKE ?)
                  {category_clause}
                GROUP BY kind, COALESCE(b.canonical_name, o.name)
                ORDER BY CASE WHEN LOWER(COALESCE(b.canonical_name, o.name))=? THEN 0 ELSE 1 END,
                         COUNT(DISTINCT o.id) DESC, display_name
                LIMIT ?
                """,
                params,
            ).fetchall()
        place_matches = tuple({
            "display_name": row[0], "kind": row[1], "canonical_brand": row[2],
            "categories": tuple(filter(None, (row[3] or "").split(","))),
            "outlet_count": int(row[4]), "example_location": row[5],
        } for row in rows)
        combined = [*category_matches, *place_matches]
        return tuple(combined[:max(1, min(limit, 50))])

    def search_hubs(self, query: str, limit: int = 6) -> tuple[dict[str, Any], ...]:
        needle = normalize_text(query)
        compact = needle.replace(" ", "")
        token_like = "%" + "%".join(needle.split()) + "%"
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT h.id, h.name, h.latitude, h.longitude, h.semantic_type,
                       h.address, tn.name
                FROM hubs h LEFT JOIN transport_nodes tn ON tn.id=h.transport_area_id
                WHERE h.closure_status != 'closed'
                  AND (LOWER(h.name) LIKE ? OR LOWER(h.name) LIKE ?
                       OR REPLACE(REPLACE(REPLACE(LOWER(h.name), ' ', ''), '@', ''), '-', '') LIKE ?)
                ORDER BY CASE WHEN REPLACE(REPLACE(REPLACE(LOWER(h.name), ' ', ''), '@', ''), '-', '')=? THEN 0 ELSE 1 END,
                         h.name LIMIT ?
                """, (f"%{needle}%", token_like, f"%{compact}%", compact, max(1, min(limit, 20))),
            ).fetchall()
        return tuple({
            "id": row[0], "name": row[1], "latitude": row[2], "longitude": row[3],
            "semantic_type": row[4], "address": row[5], "transport_node_name": row[6],
        } for row in rows)

    def search_discovery(
        self, terms: tuple[str, ...], category: str | None = None, limit: int = 20,
    ) -> tuple[dict[str, Any], ...]:
        tokens = [normalize_text(term) for term in terms if normalize_text(term)]
        if not tokens:
            return ()
        fts_query = " OR ".join(f'"{token.replace(chr(34), "")}"' for token in tokens)
        params: list[Any] = [fts_query]
        category_clause = ""
        if category:
            category_clause = "AND EXISTS (SELECT 1 FROM outlet_categories filter_oc WHERE filter_oc.outlet_id=o.id AND filter_oc.category_slug=?)"
            params.append(category)
        params.append(max(1, min(limit, 50)))
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                WITH matches AS (
                    SELECT outlet_id
                    FROM outlet_search WHERE outlet_search MATCH ?
                )
                SELECT o.id, COALESCE(b.canonical_name, o.name), b.canonical_name,
                       h.name, h.latitude, h.longitude, h.address, o.source,
                       GROUP_CONCAT(DISTINCT oc.category_slug),
                       o.original_name, o.alt_names, o.cuisine, o.shop, o.amenity,
                       o.search_metadata, 0.0
                FROM matches
                JOIN outlets o ON o.id=CAST(matches.outlet_id AS INTEGER)
                JOIN hubs h ON h.id=o.hub_id
                LEFT JOIN brands b ON b.id=o.brand_id
                LEFT JOIN outlet_categories oc ON oc.outlet_id=o.id
                WHERE o.closure_status != 'closed'
                  AND h.closure_status != 'closed' {category_clause}
                GROUP BY o.id ORDER BY COALESCE(b.canonical_name, o.name)
                LIMIT ?
                """, params,
            ).fetchall()
        results = []
        for row in rows:
            searchable = " | ".join(str(item or "") for item in row[1:15]).casefold()
            evidence = tuple(term for term in tokens if term in searchable)
            results.append({
                "display_name": row[1], "canonical_brand": row[2], "hub_name": row[3],
                "latitude": row[4], "longitude": row[5], "address": row[6], "source": row[7],
                "categories": tuple(filter(None, (row[8] or "").split(","))),
                "evidence": evidence, "evidence_exact": tokens[0] in searchable, "rank": row[15],
            })
        results.sort(key=lambda item: (
            0 if item["evidence_exact"] else 1,
            -len(item["evidence"]), item["display_name"].casefold(),
        ))
        return tuple(results)

    def resolve_brand(self, value: str) -> dict[str, Any] | None:
        needle = normalize_text(value)
        for brand in self.brand_catalog():
            names = {
                normalize_text(brand["canonical_name"]),
                normalize_text(brand["slug"]),
                *(normalize_text(alias) for alias in brand["aliases"]),
            }
            if needle in names:
                return brand
        return None

    def resolve_place(self, value: str, category: str | None = None) -> dict[str, Any] | None:
        needle = normalize_text(value)
        for item in self.search_catalog(value, category, 50):
            if item["kind"] == "place" and normalize_text(item["display_name"]) == needle:
                return item
        return None

    def stats(self) -> dict[str, int]:
        queries = {
            "outlets": "SELECT COUNT(*) FROM outlets",
            "active_outlets": "SELECT COUNT(*) FROM outlets WHERE closure_status != 'closed'",
            "brands": "SELECT COUNT(DISTINCT brand_id) FROM outlets WHERE brand_id IS NOT NULL",
            "categories": "SELECT COUNT(DISTINCT category_slug) FROM outlet_categories",
            "hubs": "SELECT COUNT(*) FROM hubs",
            "malls": "SELECT COUNT(*) FROM hubs WHERE semantic_type='mall'",
            "transport_nodes": "SELECT COUNT(*) FROM transport_nodes",
            "known_hours": "SELECT COUNT(*) FROM outlets WHERE opening_hours IS NOT NULL AND opening_hours != ''",
            "known_freshness": "SELECT COUNT(*) FROM outlets WHERE last_verified_at IS NOT NULL",
            "closed_outlets": "SELECT COUNT(*) FROM outlets WHERE closure_status='closed'",
        }
        with self._connect() as connection:
            return {key: int(connection.execute(query).fetchone()[0]) for key, query in queries.items()}

    def _descendant_categories(self, connection: sqlite3.Connection, categories: tuple[str, ...]) -> tuple[str, ...]:
        placeholders = ",".join("?" for _ in categories)
        rows = connection.execute(
            f"""
            WITH RECURSIVE descendants(slug) AS (
                SELECT slug FROM categories WHERE slug IN ({placeholders})
                UNION ALL SELECT c.slug FROM categories c
                JOIN descendants d ON c.parent_slug=d.slug
            ) SELECT DISTINCT slug FROM descendants
            """,
            categories,
        ).fetchall()
        return tuple(row[0] for row in rows) or categories

    def find_for_categories(self, categories: tuple[str, ...]) -> list[Hub]:
        if not categories:
            return []
        with self._connect() as connection:
            expanded = self._descendant_categories(connection, categories)
            placeholders = ",".join("?" for _ in expanded)
            hub_ids = [row[0] for row in connection.execute(
                f"""
                SELECT DISTINCT h.id FROM hubs h
                JOIN outlets o ON o.hub_id=h.id
                JOIN outlet_categories oc ON oc.outlet_id=o.id
                WHERE oc.category_slug IN ({placeholders})
                  AND h.closure_status != 'closed' AND o.closure_status != 'closed'
                ORDER BY h.id
                """,
                expanded,
            )]
            if not hub_ids:
                return []
            id_placeholders = ",".join("?" for _ in hub_ids)
            rows = connection.execute(
                f"""
                SELECT h.id, h.name, h.latitude, h.longitude, h.semantic_type,
                    h.transport_area_id, h.consolidation_group_id, h.source,
                    h.source_id, h.last_verified_at, h.opening_hours,
                    h.closure_status, h.transport_node_distance_m, h.address,
                    tn.name,
                    o.name, o.category, b.canonical_name, o.opening_hours,
                    o.closure_status, o.source, o.source_id,
                    GROUP_CONCAT(oc.category_slug)
                FROM hubs h JOIN outlets o ON o.hub_id=h.id AND o.closure_status != 'closed'
                LEFT JOIN transport_nodes tn ON tn.id=h.transport_area_id
                LEFT JOIN brands b ON b.id=o.brand_id
                LEFT JOIN outlet_categories oc ON oc.outlet_id=o.id
                WHERE h.id IN ({id_placeholders})
                GROUP BY h.id, o.id ORDER BY h.id, o.id
                """,
                hub_ids,
            ).fetchall()
            mall_rows = connection.execute(
                "SELECT name, latitude, longitude FROM hubs WHERE semantic_type='mall' AND closure_status != 'closed'"
            ).fetchall()

        grouped: dict[int, dict[str, Any]] = {}
        for row in rows:
            (hub_id, hub_name, latitude, longitude, semantic_type,
             transport_area_id, consolidation_group_id, hub_source, hub_source_id,
             last_verified_at, hub_hours, hub_status, transport_distance, address,
             transport_node_name,
             store_name, primary_category, canonical_name, store_hours,
             store_status, store_source, store_source_id, category_csv) = row
            entry = grouped.setdefault(hub_id, {
                "name": hub_name, "coordinate": Coordinate(latitude, longitude),
                "semantic_type": semantic_type, "transport_area_id": transport_area_id,
                "consolidation_group_id": consolidation_group_id, "source": hub_source,
                "source_id": hub_source_id,
                "last_verified_at": datetime.fromisoformat(last_verified_at) if last_verified_at else None,
                "opening_hours": hub_hours, "closure_status": hub_status,
                "transport_node_distance_m": transport_distance, "address": address,
                "transport_node_name": transport_node_name, "stores": [],
            })
            extra_categories = tuple(
                item for item in (category_csv or primary_category).split(",")
                if item != primary_category
            )
            entry["stores"].append(Store(
                store_name, primary_category, canonical_name, extra_categories,
                store_hours, store_status, store_source, store_source_id,
            ))
        mall_grid: dict[tuple[int, int], list[tuple[str, float, float]]] = {}
        grid_size = 0.004
        for mall_name, mall_latitude, mall_longitude in mall_rows:
            key = (int(mall_latitude / grid_size), int(mall_longitude / grid_size))
            mall_grid.setdefault(key, []).append((mall_name, mall_latitude, mall_longitude))
        result = []
        for hub_id, data in grouped.items():
            nearby_name = None
            nearby_distance = None
            if data["semantic_type"] != "mall":
                cell = (
                    int(data["coordinate"].latitude / grid_size),
                    int(data["coordinate"].longitude / grid_size),
                )
                local_malls = [
                    mall
                    for latitude_offset in (-1, 0, 1)
                    for longitude_offset in (-1, 0, 1)
                    for mall in mall_grid.get(
                        (cell[0] + latitude_offset, cell[1] + longitude_offset), ()
                    )
                ]
                nearby = sorted(
                    (
                        (_approx_distance_m(data["coordinate"], Coordinate(lat, lon)), name)
                        for name, lat, lon in local_malls
                    ),
                    key=lambda item: item[0],
                )
                if nearby and nearby[0][0] <= 350:
                    nearby_distance, nearby_name = round(nearby[0][0], 1), nearby[0][1]
            result.append(Hub(hub_id, data["name"], data["coordinate"], tuple(data["stores"]),
                data["semantic_type"], data["transport_area_id"],
                data["consolidation_group_id"], data["source"], data["source_id"],
                data["last_verified_at"], data["opening_hours"],
                data["closure_status"], data["transport_node_distance_m"],
                data["address"], data["transport_node_name"], nearby_name,
                nearby_distance))
        return result

    def replace_bus_network(
        self,
        stops: Iterable[dict[str, Any]],
        routes: Iterable[dict[str, Any]],
        verified_at: str | None = None,
    ) -> tuple[int, int]:
        """Swap in a fresh capture of the static bus network.

        Replaced wholesale rather than merged: LTA publishes the network as a
        complete snapshot, and a retired stop or a rerouted service has to
        disappear rather than linger. Empty input is refused so that a failed
        or truncated fetch cannot quietly empty the tables.
        """
        stop_records, route_records = list(stops), list(routes)
        if not stop_records or not route_records:
            raise ValueError(
                "Refusing to replace the bus network with an empty capture "
                f"({len(stop_records)} stops, {len(route_records)} route rows)"
            )
        with self._connect() as connection:
            connection.execute("DELETE FROM bus_routes")
            connection.execute("DELETE FROM bus_stops")
            connection.executemany(
                """
                INSERT INTO bus_stops(stop_code, road_name, description,
                    latitude, longitude, last_verified_at)
                VALUES (:stop_code, :road_name, :description, :latitude,
                    :longitude, :last_verified_at)
                """,
                [{**row, "last_verified_at": verified_at} for row in stop_records],
            )
            connection.executemany(
                """
                INSERT INTO bus_routes(service_no, direction, stop_sequence,
                    stop_code, operator, distance_km, weekday_first, weekday_last,
                    saturday_first, saturday_last, sunday_first, sunday_last,
                    last_verified_at)
                VALUES (:service_no, :direction, :stop_sequence, :stop_code,
                    :operator, :distance_km, :weekday_first, :weekday_last,
                    :saturday_first, :saturday_last, :sunday_first, :sunday_last,
                    :last_verified_at)
                """,
                [{**row, "last_verified_at": verified_at} for row in route_records],
            )
        return len(stop_records), len(route_records)

    def bus_stop(self, stop_code: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            connection.row_factory = sqlite3.Row
            row = connection.execute(
                "SELECT stop_code, road_name, description, latitude, longitude"
                " FROM bus_stops WHERE stop_code=?",
                (stop_code,),
            ).fetchone()
        return dict(row) if row else None

    def bus_routes_at_stop(self, stop_code: str) -> list[dict[str, Any]]:
        """Every service calling here, with its published operating window.

        One row per direction, because a service can pass a stop outbound and
        not inbound, and the first and last bus differ between them.
        """
        with self._connect() as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                "SELECT service_no, direction, operator, weekday_first, weekday_last,"
                " saturday_first, saturday_last, sunday_first, sunday_last"
                " FROM bus_routes WHERE stop_code=? ORDER BY service_no, direction",
                (stop_code,),
            ).fetchall()
        return [dict(row) for row in rows]

    def bus_network_counts(self) -> tuple[int, int]:
        with self._connect() as connection:
            stops = connection.execute("SELECT COUNT(*) FROM bus_stops").fetchone()[0]
            routes = connection.execute("SELECT COUNT(*) FROM bus_routes").fetchone()[0]
        return stops, routes

    def replace_source_data(
        self, source: str, transport_nodes: Iterable[dict[str, Any]],
        hubs: Iterable[dict[str, Any]], outlets: Iterable[dict[str, Any]],
    ) -> None:
        node_records, hub_records, outlet_records = list(transport_nodes), list(hubs), list(outlets)
        with self._connect() as connection:
            old_hub_ids = [row[0] for row in connection.execute("SELECT id FROM hubs WHERE source=?", (source,))]
            # A curated seed hub is a bootstrap, not a fact. Where an incoming
            # hub describes the same building - same normalized name, within
            # 400 m - retire the seed copy, or the two reach the user as
            # competing recommendations for one mall.
            incoming = {
                normalize_text(hub["name"]): (hub["latitude"], hub["longitude"])
                for hub in hub_records
            }
            for row in connection.execute(
                "SELECT id, name, latitude, longitude FROM hubs WHERE source<>?", (source,)
            ):
                match = incoming.get(normalize_text(row[1]))
                if match is not None and _seed_distance_km(row[2], row[3], match) <= 0.4:
                    old_hub_ids.append(row[0])
            if old_hub_ids:
                placeholders = ",".join("?" for _ in old_hub_ids)
                connection.execute(f"DELETE FROM outlets WHERE hub_id IN ({placeholders})", old_hub_ids)
                connection.execute(f"DELETE FROM hubs WHERE id IN ({placeholders})", old_hub_ids)
            connection.execute("DELETE FROM transport_nodes WHERE source=?", (source,))
            connection.executemany(
                """
                INSERT INTO transport_nodes(id, name, latitude, longitude, node_type,
                    source, source_id, last_verified_at)
                VALUES (:id, :name, :latitude, :longitude, :node_type, :source,
                    :source_id, :last_verified_at)
                """,
                node_records,
            )
            hub_id_by_source: dict[str, int] = {}
            for hub in hub_records:
                hub = {**hub, "address": hub.get("address")}
                cursor = connection.execute(
                    """
                    INSERT INTO hubs(name, latitude, longitude, semantic_type,
                        transport_area_id, consolidation_group_id, source, source_id,
                        last_verified_at, opening_hours, closure_status,
                        transport_node_distance_m, address)
                    VALUES (:name, :latitude, :longitude, :semantic_type,
                        :transport_area_id, :consolidation_group_id, :source,
                        :source_id, :last_verified_at, :opening_hours,
                        :closure_status, :transport_node_distance_m, :address)
                    """, hub,
                )
                hub_id_by_source[hub["source_id"]] = int(cursor.lastrowid)
            brand_ids = dict(connection.execute("SELECT slug, id FROM brands"))
            for outlet in outlet_records:
                data = dict(outlet)
                for field in ("original_name", "alt_names", "cuisine", "shop", "amenity", "search_metadata"):
                    data.setdefault(field, None)
                data["hub_id"] = hub_id_by_source[data.pop("hub_source_id")]
                data["brand_id"] = brand_ids.get(data.pop("brand_slug"))
                categories = tuple(data.pop("categories"))
                data["category"] = categories[0]
                cursor = connection.execute(
                    """
                    INSERT INTO outlets(hub_id, name, category, brand_id, source,
                        source_id, last_verified_at, opening_hours, closure_status,
                        original_name, alt_names, cuisine, shop, amenity, search_metadata)
                    VALUES (:hub_id, :name, :category, :brand_id, :source,
                        :source_id, :last_verified_at, :opening_hours, :closure_status,
                        :original_name, :alt_names, :cuisine, :shop, :amenity, :search_metadata)
                    """, data,
                )
                outlet_id = int(cursor.lastrowid)
                connection.executemany(
                    "INSERT INTO outlet_categories(outlet_id, category_slug) VALUES (?, ?)",
                    ((outlet_id, category) for category in categories),
                )
            self._rebuild_search_index(connection)

    @staticmethod
    def _rebuild_search_index(connection: sqlite3.Connection) -> None:
        connection.execute("DELETE FROM outlet_search")
        connection.execute(
            """
            INSERT INTO outlet_search(outlet_id, name, brand, aliases, categories,
                cuisine, shop, amenity, hub, address, metadata)
            SELECT o.id, COALESCE(o.original_name, o.name), COALESCE(b.canonical_name, ''),
                   COALESCE(GROUP_CONCAT(DISTINCT ba.alias_normalized), ''),
                   COALESCE(GROUP_CONCAT(DISTINCT oc.category_slug), ''),
                   COALESCE(o.cuisine, ''), COALESCE(o.shop, ''), COALESCE(o.amenity, ''),
                   h.name, COALESCE(h.address, ''),
                   COALESCE(o.alt_names, '') || ' ' || COALESCE(o.search_metadata, '')
            FROM outlets o JOIN hubs h ON h.id=o.hub_id
            LEFT JOIN brands b ON b.id=o.brand_id
            LEFT JOIN brand_aliases ba ON ba.brand_id=b.id
            LEFT JOIN outlet_categories oc ON oc.outlet_id=o.id
            GROUP BY o.id
            """
        )


def _approx_distance_m(first: Coordinate, second: Coordinate) -> float:
    latitude_scale = 110_570.0
    longitude_scale = 111_320.0 * cos(radians((first.latitude + second.latitude) / 2))
    return sqrt(
        ((first.latitude - second.latitude) * latitude_scale) ** 2
        + ((first.longitude - second.longitude) * longitude_scale) ** 2
    )
