"""Names a person can read - V0.8.2, idea 3 part one.

Idea 3 asked for pictures instead of bare names. Measuring the dataset first
found something worse than bare: 3,140 of 9,641 hubs - 32.6% - displayed a raw
OpenStreetMap element id, because the collision handler reached for the one
value guaranteed to be unique and guaranteed to mean nothing:

    7-Eleven - node/10030129567
    Bakeries node/10201802661

Two separate defects produced that. A name that collided got the element id
appended, and a place OSM never named got a category slug with the id after it.
Singapore has three hundred 7-Elevens, so the collision branch was the common
path rather than the exceptional one.

These tests pin the replacement: disambiguate by somewhere a traveller can
picture, and keep the element id for the database.
"""

from __future__ import annotations

import pytest

from app.poi_ingestion import _clean_qualifier, _landmark, _qualifiers, _unique_name
from app.poi_taxonomy import unnamed_label

RAIL = {"n1": ("Aljunied", "station")}
BUS = {"n2": ("Opposite Haw Par Villa Station", "bus_stop")}


def test_a_first_use_of_a_name_is_left_alone() -> None:
    used: set[str] = set()
    assert _unique_name("Ya Kun Kaya Toast", "node/1", used) == "Ya Kun Kaya Toast"


def test_a_collision_is_settled_by_place_not_by_element_id() -> None:
    """The defect this file exists for. Two 7-Elevens are an ordinary fact
    about Singapore, and the second one is not called node/10030129567."""
    used = {"7-Eleven"}
    assert _unique_name("7-Eleven", "node/2", used, ("Hongkong Street",)) == (
        "7-Eleven (Hongkong Street)"
    )


def test_qualifiers_are_tried_in_turn_before_anything_is_numbered() -> None:
    used = {"7-Eleven", "7-Eleven (Hongkong Street)"}
    assert _unique_name("7-Eleven", "node/3", used, ("Hongkong Street", "Clarke Quay")) == (
        "7-Eleven (Clarke Quay)"
    )


def test_two_of_the_same_shop_on_one_street_are_numbered() -> None:
    """What a person does when the street no longer separates them, and still
    not an element id."""
    used = {"Restaurant", "Restaurant (Pasir Panjang)"}
    assert _unique_name("Restaurant", "node/4", used, ("Pasir Panjang",)) == (
        "Restaurant (Pasir Panjang) 2"
    )


def test_the_element_id_survives_only_where_nothing_else_could_work() -> None:
    """Kept as a genuine last resort rather than deleted: a name has to be
    unique, and silently colliding would be worse than an ugly one."""
    used = {"Kiosk"} | {f"Kiosk {index}" for index in range(2, 100)}
    assert _unique_name("Kiosk", "node/5", used) == "Kiosk · node/5"


def test_a_place_osm_never_named_gets_a_noun_not_a_slug() -> None:
    assert unnamed_label("bakeries") == "Bakery"
    assert unnamed_label("banking") == "ATM or bank"
    assert unnamed_label("parcel") == "Parcel point"
    assert unnamed_label("pet_supplies") == "Pet shop"


def test_an_unknown_category_falls_back_to_the_heading_not_the_slug() -> None:
    """A category added without a noun should read awkwardly, never print
    "pet_supplies" at somebody."""
    assert unnamed_label("groceries") == "Supermarket"
    assert "_" not in unnamed_label("nonexistent_category")


def test_a_bus_stop_is_named_by_its_landmark_not_its_preposition() -> None:
    assert _landmark("Opposite Haw Par Villa Station") == "Haw Par Villa Station"
    assert _landmark("Before Tai Hoe Hotel") == "Tai Hoe Hotel"
    assert _landmark("Aft Blk 210") == "Blk 210"
    assert _landmark("Bugis Junction") == "Bugis Junction"


def test_a_stop_whose_whole_name_is_a_preposition_keeps_it() -> None:
    """Stripping to nothing would be worse than leaving it alone."""
    assert _landmark("Opposite") == "Opposite"


@pytest.mark.parametrize(
    "raw, expected",
    [
        # An address with a unit number bolted on with punctuation.
        ("Irving Place, #08-06;The Commerze@Irving", "Irving Place"),
        # A stop name carrying brackets, which would nest inside the ones the
        # caller is about to add.
        ("T4 Shuttle (Arrival)", "T4 Shuttle"),
        ("Clementi Cross Island Line (EW23, CR17)", "Clementi Cross Island Line"),
        ("  Beach   Road  ", "Beach Road"),
    ],
)
def test_a_qualifier_is_cleaned_before_it_is_shown(raw: str, expected: str) -> None:
    assert _clean_qualifier(raw) == expected


def test_brackets_are_stripped_before_the_comma_split() -> None:
    """Order matters and got this wrong once: splitting first strands the
    opening bracket and produces "Clementi Cross Island Line (EW23"."""
    cleaned = _clean_qualifier("Clementi Cross Island Line (EW23, CR17)")
    assert cleaned is not None
    assert cleaned.count("(") == cleaned.count(")") == 0


@pytest.mark.parametrize("raw", ["", "  ", "x", "-", "/", "A" * 41])
def test_a_qualifier_that_identifies_nothing_is_refused(raw: str) -> None:
    """Too short to locate anything, or too long to read inside brackets."""
    assert _clean_qualifier(raw) is None


def test_the_street_is_preferred_over_the_transport_node() -> None:
    """An address is what somebody standing outside would use."""
    tags = {"addr:street": "Hongkong Street"}
    assert _qualifiers(tags, "n1", RAIL)[0] == "Hongkong Street"


def test_a_station_qualifies_a_place_with_no_address() -> None:
    assert _qualifiers({}, "n1", RAIL) == ("Aljunied",)


def test_a_bus_stop_qualifier_is_reduced_to_its_landmark() -> None:
    assert _qualifiers({}, "n2", BUS) == ("Haw Par Villa Station",)


def test_a_generated_transport_node_name_is_not_a_qualifier() -> None:
    """"Transport node way/123" locates nothing, and putting it in brackets
    would reintroduce the exact defect this change removes."""
    index = {"n3": ("Transport node way/123", "bus_stop")}
    assert _qualifiers({}, "n3", index) == ()


def test_a_stop_named_after_its_own_street_does_not_repeat_itself() -> None:
    """Common in Singapore, and "(Beach Road)" twice reads as a bug."""
    index = {"n4": ("Beach Road", "bus_stop")}
    assert _qualifiers({"addr:street": "Beach Road"}, "n4", index) == ("Beach Road",)


def test_a_hub_with_no_transport_node_still_qualifies_by_street() -> None:
    assert _qualifiers({"addr:street": "Balestier Road"}, None, {}) == ("Balestier Road",)


def test_two_unnamed_shops_of_one_kind_in_one_mall_get_distinct_names() -> None:
    """The schema is UNIQUE on (hub_id, name, category), and that used to hold
    by accident: an unnamed outlet carried its element id, so no two could
    match. Once both became "Bakery" the rebuild failed on the constraint, so
    outlet names are made unique per hub deliberately.
    """
    from app.poi_ingestion import transform_osm_payload

    payload = {
        "capture_metadata": {"captured_at": "2026-09-10T00:00:00+00:00"},
        "elements": [
            {
                "type": "way", "id": 1, "center": {"lat": 1.300, "lon": 103.800},
                "bounds": {
                    "minlat": 1.299, "maxlat": 1.301,
                    "minlon": 103.799, "maxlon": 103.801,
                },
                "tags": {"shop": "mall", "name": "Test Mall"},
            },
            # Two bakeries, neither named, far enough apart to survive dedupe.
            {"type": "node", "id": 2, "lat": 1.2995, "lon": 103.7995,
             "tags": {"shop": "bakery"}},
            {"type": "node", "id": 3, "lat": 1.3008, "lon": 103.8008,
             "tags": {"shop": "bakery"}},
        ],
    }
    _nodes, _hubs, outlets, _report = transform_osm_payload(payload)
    bakeries = [item for item in outlets if item["name"].startswith("Bakery")]
    assert len(bakeries) == 2, "both should survive; dedupe is by element, not by label"
    keys = {(item["hub_source_id"], item["name"], item["categories"][0]) for item in bakeries}
    assert len(keys) == 2, f"names collide within the hub: {[b['name'] for b in bakeries]}"
    assert not any("node/" in item["name"] for item in bakeries)
