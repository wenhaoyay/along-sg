"""Brand logos from Wikidata and Commons - V0.8.3, idea 3 part two.

Idea 3 asked for pictures of the stalls. OpenStreetMap has 20 across 21,280
elements, and every provider that does hold photographs of Singapore shopfronts
either charges or forbids storing what it returns - so photographs are not what
this data supports. Logos are: 601 `brand:wikidata` ids cover 4,077 outlets,
free and keyless.

The payloads below are shaped like Wikidata's own EntityData responses. The
awkward cases are the point - a deprecated claim, a "novalue" snak, a redirect
answering under a different id, and a file format a browser cannot draw.
"""

from __future__ import annotations

import pytest

from app.brand_logos import (
    USER_AGENT,
    commons_file_url,
    entity_label,
    logo_file_name,
    parse_entity_payload,
)


def entity(claims: dict, label: str | None = "7-Eleven") -> dict:
    body: dict = {"claims": claims}
    if label is not None:
        body["labels"] = {"en": {"language": "en", "value": label}}
    return body


def claim(value, prop_type: str = "value", rank: str = "normal") -> dict:
    snak: dict = {"snaktype": prop_type}
    if prop_type == "value":
        snak["datavalue"] = {"value": value, "type": "string"}
    return {"mainsnak": snak, "rank": rank}


def logo_row(qid: str, file_name: str, url: str) -> dict:
    return {
        "wikidata_id": qid,
        "brand_label": qid,
        "file_name": file_name,
        "url": url,
    }


def test_a_commons_url_is_derived_from_the_file_name() -> None:
    """The path is the first one and two hex digits of the MD5 of the
    underscored name. Published rule, and the reason no second request is
    needed per logo."""
    assert commons_file_url("7-Eleven logo 2021.svg") == (
        "https://upload.wikimedia.org/wikipedia/commons/e/e0/7-Eleven_logo_2021.svg"
    )


def test_the_derived_url_percent_encodes_without_touching_the_hash() -> None:
    """The MD5 is of the raw underscored name; only the last path segment is
    escaped. Hashing the escaped form would point at nothing."""
    url = commons_file_url("Caffè Nero logo.svg")
    assert url.startswith("https://upload.wikimedia.org/wikipedia/commons/")
    assert "%" in url.rsplit("/", 1)[-1]


def test_the_user_agent_carries_a_contact_url() -> None:
    """Not cosmetic. Wikimedia answers 403 to a terse User-Agent and 200 to the
    same request with a contact URL - measured on both."""
    assert "http" in USER_AGENT


def test_the_logo_claim_is_read_from_p154() -> None:
    assert logo_file_name(entity({"P154": [claim("7-Eleven logo.svg")]})) == "7-Eleven logo.svg"


def test_p8972_is_used_only_when_there_is_no_p154() -> None:
    """The icon variant is often a monogram, which identifies less than the
    logo proper."""
    both = entity({"P154": [claim("full.svg")], "P8972": [claim("icon.svg")]})
    assert logo_file_name(both) == "full.svg"
    assert logo_file_name(entity({"P8972": [claim("icon.svg")]})) == "icon.svg"


def test_a_deprecated_claim_is_not_the_logo() -> None:
    """Wikidata keeps superseded values in place and marks them, so taking the
    first would serve a logo the brand has retired."""
    payload = entity({"P154": [claim("old.svg", rank="deprecated"), claim("new.svg")]})
    assert logo_file_name(payload) == "new.svg"


def test_a_claim_with_no_value_is_skipped() -> None:
    """A "novalue" snak is Wikidata asserting the brand has no logo. It carries
    no datavalue at all, and reading one would raise."""
    payload = entity({"P154": [claim(None, prop_type="novalue"), claim("real.svg")]})
    assert logo_file_name(payload) == "real.svg"


@pytest.mark.parametrize("file_name", ["scan.tif", "artwork.xcf", "brand.pdf", "notes.txt"])
def test_a_format_a_browser_cannot_draw_is_refused(file_name: str) -> None:
    """Commons holds TIFF, XCF and PDF. An <img> pointing at one of those is a
    broken image, which is worse than the glyph it would have displaced."""
    assert logo_file_name(entity({"P154": [claim(file_name)]})) is None


@pytest.mark.parametrize("file_name", ["a.svg", "b.PNG", "c.Jpeg", "d.webp", "e.gif"])
def test_renderable_formats_are_accepted_whatever_the_case(file_name: str) -> None:
    assert logo_file_name(entity({"P154": [claim(file_name)]})) == file_name


def test_an_entity_with_no_logo_is_an_ordinary_answer() -> None:
    """Most brands have no logo claim. That is coverage, not failure."""
    assert logo_file_name(entity({})) is None
    assert logo_file_name({}) is None
    assert logo_file_name({"claims": "nonsense"}) is None


def test_the_english_label_is_taken_when_present() -> None:
    assert entity_label(entity({}, label="Ya Kun Kaya Toast")) == "Ya Kun Kaya Toast"
    assert entity_label(entity({}, label=None)) is None
    assert entity_label({}) is None


def test_a_full_payload_becomes_a_storable_row() -> None:
    payload = {"entities": {"Q259340": entity({"P154": [claim("7-Eleven logo 2021.svg")]})}}
    row = parse_entity_payload(payload, "Q259340")
    assert row == {
        "wikidata_id": "Q259340",
        "brand_label": "7-Eleven",
        "file_name": "7-Eleven logo 2021.svg",
        "url": "https://upload.wikimedia.org/wikipedia/commons/e/e0/7-Eleven_logo_2021.svg",
    }


def test_a_redirect_answering_under_another_id_is_followed() -> None:
    """A merged Wikidata item answers under its target. Keying strictly on the
    requested id would drop the brand for no reason."""
    payload = {"entities": {"Q999": entity({"P154": [claim("moved.svg")]})}}
    row = parse_entity_payload(payload, "Q123")
    assert row is not None
    # Stored under the id the outlets actually carry, or the join finds nothing.
    assert row["wikidata_id"] == "Q123"
    assert row["file_name"] == "moved.svg"


def test_an_ambiguous_multi_entity_body_is_refused() -> None:
    """Two entities and no match is not a redirect, and guessing which one is
    the brand would attach the wrong logo to real shops."""
    payload = {
        "entities": {
            "Q1": entity({"P154": [claim("one.svg")]}),
            "Q2": entity({"P154": [claim("two.svg")]}),
        }
    }
    assert parse_entity_payload(payload, "Q3") is None


def test_a_body_with_no_logo_yields_nothing_rather_than_a_blank_row() -> None:
    assert parse_entity_payload({"entities": {"Q1": entity({})}}, "Q1") is None
    assert parse_entity_payload({}, "Q1") is None
    assert parse_entity_payload({"entities": None}, "Q1") is None


def test_logos_merge_rather_than_replace(tmp_path) -> None:
    """A partial fetch must not replace the whole logo table."""
    from app.db import HubRepository

    repository = HubRepository(tmp_path / "logos.db")
    repository.initialize()
    assert (
        repository.upsert_brand_logos(
            [logo_row("Q1", "a.svg", "u1")],
            "2026-09-10T00:00:00+08:00",
        )
        == 1
    )
    repository.upsert_brand_logos(
        [logo_row("Q2", "b.svg", "u2")],
        "2026-09-10T00:00:00+08:00",
    )
    assert repository.brand_logo_urls() == {"Q1": "u1", "Q2": "u2"}
    # A re-fetch updates in place rather than duplicating.
    repository.upsert_brand_logos(
        [logo_row("Q1", "c.svg", "u3")],
        "2026-09-11T00:00:00+08:00",
    )
    assert repository.brand_logo_urls() == {"Q1": "u3", "Q2": "u2"}
    assert repository.brand_logo_count() == 2


def test_successful_refresh_updates_an_existing_logo(tmp_path) -> None:
    from app.db import HubRepository
    from scripts.ingest_brand_logos import reconcile_capture

    repository = HubRepository(tmp_path / "updated.db")
    repository.initialize()
    repository.upsert_brand_logos([logo_row("Q1", "old.svg", "old")])
    captured = {"Q1": {"entities": {"Q1": entity({"P154": [claim("new.svg")]})}}}

    written, deleted, usable = reconcile_capture(repository, captured, "now")

    assert (written, deleted, usable) == (1, 0, 1)
    assert repository.brand_logo_urls()["Q1"] == commons_file_url("new.svg")


def test_successful_response_without_a_logo_removes_the_stale_row(tmp_path) -> None:
    from app.db import HubRepository
    from scripts.ingest_brand_logos import reconcile_capture

    repository = HubRepository(tmp_path / "removed.db")
    repository.initialize()
    repository.upsert_brand_logos([logo_row("Q1", "old.svg", "old")])
    captured = {"Q1": {"entities": {"Q1": entity({})}}}

    written, deleted, usable = reconcile_capture(repository, captured, "now")

    assert (written, deleted, usable) == (0, 1, 0)
    assert repository.brand_logo_urls() == {}


def test_failed_fetch_preserves_the_existing_logo(tmp_path) -> None:
    """Failed QIDs are absent from fetch_all's successful capture mapping, so
    reconciliation cannot mistake a network failure for a no-logo response."""
    from app.db import HubRepository
    from scripts.ingest_brand_logos import reconcile_capture

    repository = HubRepository(tmp_path / "failed.db")
    repository.initialize()
    repository.upsert_brand_logos([logo_row("Q1", "old.svg", "old")])

    written, deleted, usable = reconcile_capture(repository, {}, "now")

    assert (written, deleted, usable) == (0, 0, 0)
    assert repository.brand_logo_urls() == {"Q1": "old"}


def test_an_empty_fetch_writes_nothing_and_does_not_raise(tmp_path) -> None:
    from app.db import HubRepository

    repository = HubRepository(tmp_path / "empty.db")
    repository.initialize()
    assert repository.upsert_brand_logos([]) == 0
    assert repository.brand_logo_urls() == {}


def test_an_outlet_without_a_brand_gets_no_logo_and_that_is_not_an_error() -> None:
    from app.poi_ingestion import _wikidata_id

    assert _wikidata_id({}) is None
    assert _wikidata_id({"brand:wikidata": "not-an-id"}) is None
    assert _wikidata_id({"brand:wikidata": "Q0"}) is None, "Q0 is not a real entity"
    assert _wikidata_id({"brand:wikidata": "Q259340"}) == "Q259340"


def test_brand_wikidata_wins_over_weaker_associations() -> None:
    from app.poi_ingestion import _wikidata_id

    assert _wikidata_id(
        {"brand:wikidata": "Q2", "operator:wikidata": "Q3", "wikidata": "Q4"}
    ) == "Q2"


def test_generic_poi_wikidata_is_not_automatically_a_brand() -> None:
    from app.poi_ingestion import _wikidata_id

    assert _wikidata_id({"name": "Example Shop", "wikidata": "Q4"}) is None


def test_operator_id_does_not_override_a_known_different_consumer_brand() -> None:
    from app.poi_ingestion import _wikidata_id

    assert _wikidata_id(
        {"brand": "7-Eleven", "name": "7-Eleven", "operator:wikidata": "Q999"}
    ) is None
