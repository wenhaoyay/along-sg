"""Place data quality: seed hubs, taxonomy, names and catalogue refresh."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from app.db import HUB_SEED, HubRepository
from app.poi_ingestion import (
    file_fingerprint,
    ingest_payload,
    transform_osm_payload,
)
from app.poi_taxonomy import derived_display_name, infer_categories, is_generic_name


def _hub(name: str, latitude: float, longitude: float, source_id: str) -> dict:
    return {
        "name": name, "latitude": latitude, "longitude": longitude,
        "semantic_type": "mall", "transport_area_id": None,
        "consolidation_group_id": source_id, "source": "openstreetmap",
        "source_id": source_id, "last_verified_at": "2026-09-09T00:00:00+00:00",
        "opening_hours": None, "closure_status": "unknown",
        "transport_node_distance_m": 50.0, "address": None,
    }


def _hub_rows(database: Path) -> list[tuple[str, str]]:
    with sqlite3.connect(database) as connection:
        return connection.execute("SELECT name, source FROM hubs ORDER BY name").fetchall()


def test_nex_seed_sits_on_the_real_mall() -> None:
    nex = next(row for row in HUB_SEED if row[6] == "nex")
    # 23 Serangoon Central. It used to be at 103.8488 - 2.6 km west.
    assert abs(nex[2] - 1.3508) < 0.001 and abs(nex[3] - 103.8723) < 0.001


def test_osm_names_retire_the_seed_hub_for_the_same_building(tmp_path) -> None:
    database = tmp_path / "errands.db"
    repository = HubRepository(database)
    repository.initialize()
    repository.replace_source_data("openstreetmap", [], [
        _hub("NEX", 1.3504, 103.8723, "mall:way/174035941"),
        _hub("Lot One Shoppers' Mall", 1.3852, 103.7450, "mall:way/173131856"),
        _hub("HDB Hub", 1.3320, 103.8485, "mall:way/170403710"),
    ], [])
    names = {name for name, source in _hub_rows(database) if source == "curated"}
    assert not names & {"NEX", "Lot One", "Toa Payoh HDB Hub"}
    # The other nine seeds survive a partial capture.
    assert "ION Orchard" in names


def test_full_catalogue_retires_every_unverified_seed_for_good(tmp_path) -> None:
    database = tmp_path / "errands.db"
    repository = HubRepository(database)
    repository.initialize()
    repository.replace_source_data(
        "openstreetmap", [], [_hub("Somewhere Mall", 1.33, 103.80, "mall:way/1")], [],
        retire_curated_seed=True,
    )
    assert all(source != "curated" for _name, source in _hub_rows(database))
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM outlets WHERE last_verified_at IS NULL"
        ).fetchone()[0] == 0
    # A restart must not bring the invented outlets back.
    HubRepository(database).initialize()
    assert all(source != "curated" for _name, source in _hub_rows(database))
    assert repository.get_meta("curated_seed_retired") == "1"


def test_ingest_records_the_capture_and_fingerprint(tmp_path) -> None:
    repository = HubRepository(tmp_path / "errands.db")
    repository.initialize()
    payload = {
        "capture_metadata": {"captured_at": "2026-09-09T02:41:49+00:00"},
        "elements": [
            {"type": "node", "id": 1, "lat": 1.30, "lon": 103.80,
             "tags": {"amenity": "atm", "brand": "UOB"}},
        ],
    }
    ingest_payload(repository, payload, fingerprint="abc")
    assert repository.get_meta("osm_captured_at") == "2026-09-09T02:41:49+00:00"
    assert repository.get_meta("catalogue_fingerprint") == "abc"


def test_prepare_beta_data_reingests_when_the_capture_changes(tmp_path, monkeypatch) -> None:
    from scripts import prepare_beta_data

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    capture = data_dir / "singapore-osm-pois.json"
    elements = [
        {"type": "node", "id": index, "lat": 1.30 + index / 1000, "lon": 103.80,
         "tags": {"shop": "convenience", "name": f"Shop {index}"}}
        for index in range(40)
    ]
    capture.write_text(json.dumps({
        "capture_metadata": {"captured_at": "2026-01-01T00:00:00+00:00"},
        "elements": elements,
    }), encoding="utf-8")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "beta.db"))

    assert prepare_beta_data.main(data_dir) is True
    # Same files: nothing to do, even though the volume holds > 30 outlets.
    assert prepare_beta_data.main(data_dir) is False

    capture.write_text(json.dumps({
        "capture_metadata": {"captured_at": "2026-02-01T00:00:00+00:00"},
        "elements": elements[:35],
    }), encoding="utf-8")
    assert prepare_beta_data.main(data_dir) is True
    repository = HubRepository(tmp_path / "beta.db")
    assert repository.get_meta("osm_captured_at") == "2026-02-01T00:00:00+00:00"
    assert repository.get_meta("catalogue_fingerprint") == file_fingerprint(capture)


def test_cafe_cuisine_decides_coffee() -> None:
    assert "coffee" in infer_categories({"amenity": "cafe"})
    assert "coffee" in infer_categories({"amenity": "cafe", "cuisine": "coffee_shop"})
    assert "coffee" not in infer_categories({"amenity": "cafe", "name": "LiHO Tea"})
    assert "coffee" not in infer_categories({"amenity": "cafe", "cuisine": "juice"})
    assert "coffee" not in infer_categories({"amenity": "cafe", "cuisine": "ice_cream;bubble_tea"})
    assert "coffee" in infer_categories({"amenity": "cafe", "cuisine": "bubble_tea;coffee_shop"})


def test_brand_seed_no_longer_calls_bubble_tea_or_cheers_coffee(repository) -> None:
    by_slug = {brand["slug"]: brand for brand in repository.brand_catalog()}
    for slug in ("koi-the", "liho-tea", "mr-coconut", "cheers"):
        assert "coffee" not in by_slug[slug]["categories"], slug


def test_medical_supply_is_not_optical_and_atms_and_post_offices_have_categories() -> None:
    assert "optical" not in infer_categories({"shop": "medical_supply"})
    assert infer_categories({"shop": "optician"}) == ("optical",)
    assert infer_categories({"amenity": "atm", "brand": "UOB"}) == ("atm", "banking")
    assert infer_categories({"amenity": "bank", "atm": "yes"}) == ("banking", "atm")
    assert infer_categories({"amenity": "post_office"}) == ("post_office", "parcel")


def test_food_categories_come_from_cuisine() -> None:
    assert "fried_chicken" in infer_categories({"amenity": "fast_food", "cuisine": "chicken"})
    assert "fried_chicken" not in infer_categories({"amenity": "restaurant", "cuisine": "chicken"})
    assert "japanese_food" in infer_categories({"amenity": "restaurant", "cuisine": "ramen"})
    assert "chinese_food" in infer_categories({"amenity": "restaurant", "cuisine": "cantonese"})


def test_display_names_prefer_brand_operator_and_cuisine() -> None:
    assert derived_display_name({"amenity": "atm"}, ("atm",), "UOB") == "UOB ATM"
    assert derived_display_name({"amenity": "atm", "operator": "Citibank"}, ("atm",)) == "Citibank ATM"
    assert derived_display_name({"amenity": "atm", "name": "POSB ATM"}, ("atm",), "DBS/POSB") == "POSB ATM"
    assert derived_display_name({"amenity": "atm"}, ("atm",)) == "ATM"
    assert derived_display_name({"amenity": "restaurant", "cuisine": "chinese"}, ("restaurants",)) == "Chinese restaurant"
    assert derived_display_name({"amenity": "food_court"}, ("restaurants",)) == "Food court"
    assert derived_display_name({"amenity": "restaurant"}, ("restaurants",)) == "Restaurant"
    assert derived_display_name({"amenity": "restaurant", "name": "Restaurant", "cuisine": "thai"}, ("restaurants",)) == "Thai restaurant"
    assert is_generic_name("Shopping mall") and not is_generic_name("Bugis Junction")


def test_unnamed_atms_ingest_as_brand_atms() -> None:
    payload = {"elements": [
        {"type": "node", "id": 1, "lat": 1.30, "lon": 103.80,
         "tags": {"amenity": "atm", "brand": "UOB", "operator": "UOB"}},
        {"type": "node", "id": 2, "lat": 1.31, "lon": 103.80,
         "tags": {"amenity": "atm", "brand": "OCBC Bank"}},
    ]}
    _nodes, _hubs, outlets, _report = transform_osm_payload(payload)
    assert sorted(item["name"] for item in outlets) == ["OCBC ATM", "UOB ATM"]
    assert {item["brand_slug"] for item in outlets} == {"uob", "ocbc"}


def _node(identifier: int, latitude: float, longitude: float, **tags: str) -> dict:
    return {"type": "node", "id": identifier, "lat": latitude, "lon": longitude, "tags": tags}


def test_one_place_mapped_twice_becomes_one_hub() -> None:
    payload = {"elements": [
        _node(1, 1.3029, 103.8640, amenity="restaurant", name="Golden Mile Food Centre"),
        _node(2, 1.3032, 103.8639, amenity="food_court", name="Golden Mile Food Centre", cuisine="local"),
        # Same name, 2 km away: a different place.
        _node(3, 1.3200, 103.8640, amenity="restaurant", name="Golden Mile Food Centre"),
        # A chain is never merged by name.
        _node(4, 1.3000, 103.8000, shop="convenience", brand="7-Eleven", name="7-Eleven"),
        _node(5, 1.3010, 103.8000, shop="convenience", brand="7-Eleven", name="7-Eleven"),
    ]}
    _nodes, hubs, outlets, report = transform_osm_payload(payload)
    assert report.merged_hubs == 1
    golden = [hub for hub in hubs if hub["name"].startswith("Golden Mile")]
    assert len(golden) == 2
    assert len([hub for hub in hubs if hub["name"].startswith("7-Eleven")]) == 2


def test_names_that_differ_only_in_case_are_told_apart() -> None:
    payload = {"elements": [
        _node(1, 1.30, 103.80, amenity="cafe", name="Each A Cup", cuisine="bubble_tea", **{"addr:street": "Bedok North Road"}),
        _node(2, 1.40, 103.80, amenity="cafe", name="Each a cup", cuisine="bubble_tea", **{"addr:street": "Woodlands Drive"}),
    ]}
    _nodes, hubs, _outlets, _report = transform_osm_payload(payload)
    names = sorted(hub["name"] for hub in hubs)
    assert len({name.casefold() for name in names}) == 2
    assert any("(" in name for name in names)


def test_chinese_names_are_not_one_name() -> None:
    payload = {"elements": [
        _node(1, 1.3000, 103.8000, amenity="restaurant", name="喜迎客"),
        _node(2, 1.3001, 103.8001, amenity="restaurant", name="真味"),
    ]}
    _nodes, hubs, outlets, report = transform_osm_payload(payload)
    assert report.deduplicated_pois == 0 and report.merged_hubs == 0
    assert len(outlets) == 2 and len(hubs) == 2


def test_generic_hubs_are_flagged_and_carry_a_street(tmp_path) -> None:
    payload = {"elements": [
        {"type": "way", "id": 10, "bounds": {"minlat": 1.3055, "maxlat": 1.3061, "minlon": 103.8328, "maxlon": 103.8334},
         "tags": {"shop": "mall", "addr:street": "Scotts Road"}},
        _node(2, 1.35, 103.90, amenity="food_court", **{"addr:street": "Bedok North Street 1"}),
        _node(3, 1.36, 103.90, amenity="restaurant", name="Kok Sen"),
    ]}
    _nodes, hubs, _outlets, _report = transform_osm_payload(payload)
    by_name = {hub["name"]: hub for hub in hubs}
    assert by_name["Shopping mall (Scotts Road)"]["name_is_generic"] == 1
    assert by_name["Food court (Bedok North Street 1)"]["name_is_generic"] == 1
    assert by_name["Kok Sen"]["name_is_generic"] == 0

    repository = HubRepository(tmp_path / "errands.db")
    repository.initialize()
    ingest_payload(repository, payload)
    with sqlite3.connect(tmp_path / "errands.db") as connection:
        flagged = {row[0] for row in connection.execute("SELECT name FROM hubs WHERE name_is_generic=1")}
    assert flagged == {"Shopping mall (Scotts Road)", "Food court (Bedok North Street 1)"}


def test_post_offices_and_registered_pharmacies_merge_into_the_capture() -> None:
    from app.poi_ingestion import HSA_SOURCE, merge_supplements

    capture = {"elements": [
        _node(1, 1.3000, 103.8000, amenity="pharmacy", name="Guardian"),
    ]}
    post_offices = {"elements": [
        _node(2, 1.3240, 103.9300, amenity="post_office", name="Bedok Central Post Office", operator="Singapore Post"),
        _node(1, 1.3000, 103.8000, amenity="pharmacy", name="Guardian"),  # already present
    ]}
    register = {"metadata": {"last_updated": "2025-11-08T10:12:28+08:00"}, "pharmacies": [
        # 20 m from the mapped Guardian: the same shop.
        {"id": "A", "name": "Guardian", "brand": "Guardian", "latitude": 1.30015, "longitude": 103.80005},
        {"id": "B", "name": "Smith Pharmacy", "latitude": 1.3500, "longitude": 103.8500,
         "street": "Serangoon Central", "postal_code": "556083"},
    ]}
    merged, added = merge_supplements(capture, post_offices, register)
    assert added == {"post_offices": 1, "hsa_pharmacies": 1, "hsa_pharmacies_already_mapped": 1}

    _nodes, hubs, outlets, _report = transform_osm_payload(merged)
    by_name = {item["name"]: item for item in outlets}
    assert by_name["Bedok Central Post Office"]["categories"] == ("post_office", "parcel")
    smith = by_name["Smith Pharmacy"]
    assert smith["source"] == HSA_SOURCE
    assert smith["last_verified_at"] == "2025-11-08T10:12:28+08:00"
    assert any(hub["source"] == HSA_SOURCE for hub in hubs)


def test_a_brand_named_post_office_reads_as_a_post_office() -> None:
    tags = {"amenity": "post_office", "name": "Singapore Post", "operator": "Singapore Post"}
    assert derived_display_name(tags, ("post_office",), "SingPost") == "SingPost post office"


def test_reingest_replaces_supplementary_rows(tmp_path) -> None:
    from app.poi_ingestion import merge_supplements

    register = {"metadata": {}, "pharmacies": [
        {"id": "B", "name": "Smith Pharmacy", "latitude": 1.35, "longitude": 103.85},
    ]}
    payload, _added = merge_supplements({"elements": []}, None, register)
    repository = HubRepository(tmp_path / "errands.db")
    repository.initialize()
    ingest_payload(repository, payload)
    ingest_payload(repository, payload)  # must not collide with the first run
    with sqlite3.connect(tmp_path / "errands.db") as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM outlets WHERE name='Smith Pharmacy'"
        ).fetchone()[0] == 1


def test_bundled_supplements_carry_source_and_licence() -> None:
    data = Path(__file__).resolve().parents[1] / "data"
    register = json.loads((data / "singapore-hsa-pharmacies.json").read_text(encoding="utf-8"))
    assert "Singapore Open Data Licence" in register["metadata"]["license"]
    assert register["metadata"]["dataset_id"] == "d_bb92615f43de22933e4479558b1f6c36"
    assert register["pharmacies"] and all(
        1.1 < item["latitude"] < 1.5 and 103.5 < item["longitude"] < 104.1
        for item in register["pharmacies"]
    )
    post_offices = json.loads((data / "singapore-osm-post-offices.json").read_text(encoding="utf-8"))
    assert post_offices["capture_metadata"]["license"] == "ODbL 1.0"
    assert all(item["tags"]["amenity"] == "post_office" for item in post_offices["elements"])


def test_every_category_has_a_dwell_time_and_an_env_override(monkeypatch) -> None:
    from dataclasses import fields

    from app.config import DwellTimes, Settings
    from app.poi_taxonomy import CATEGORIES

    names = {item.name for item in fields(DwellTimes)}
    leaves = {
        item.slug for item in CATEGORIES
        if not any(child.parent_slug == item.slug for child in CATEGORIES)
    }
    assert leaves <= names, leaves - names

    defaults = DwellTimes()
    assert defaults.atm < defaults.convenience < defaults.groceries
    assert defaults.post_office > defaults.parcel

    # A developer's local .env may pin older allowances; this test is about
    # the defaults and the override mechanism, not about that file.
    import os

    for name in [key for key in os.environ if key.startswith("DWELL_")]:
        monkeypatch.delenv(name)
    monkeypatch.setenv("DWELL_ATM_MINUTES", "3")
    monkeypatch.setenv("DWELL_HAIRCUTS_MINUTES", "40")
    monkeypatch.setenv("DWELL_GROCERIES_MINUTES", "25")
    settings = Settings.from_env()
    assert settings.dwell_times.atm == 3
    assert settings.dwell_times.haircuts == 40
    assert settings.dwell_times.groceries == 25
    assert settings.dwell_times.pharmacy == defaults.pharmacy


def _resolve(repository: HubRepository, query: str):
    import asyncio

    from app.providers.mock import MockOneMapProvider
    from app.services.discovery import LocationResolver

    return asyncio.run(LocationResolver(repository, MockOneMapProvider()).resolve(query, 3))


def test_landmarks_outrank_shops_that_mention_them(tmp_path) -> None:
    repository = HubRepository(tmp_path / "errands.db")
    repository.initialize()
    # The shops that used to answer these queries.
    repository.replace_source_data("openstreetmap", [], [
        {**_hub("7-Eleven (Sentosa)", 1.2562, 103.8211, "poi:node/1"), "semantic_type": "station_area"},
        {**_hub("ATM (Changi Road)", 1.3186, 103.9092, "poi:node/2"), "semantic_type": "standalone"},
    ], [])
    sentosa = _resolve(repository, "Sentosa")
    assert [item.display_name for item in sentosa] == ["Sentosa"]
    assert sentosa[0].entity_type == "area"
    changi = _resolve(repository, "Changi")[0]
    assert changi.display_name == "Changi Airport"
    assert abs(changi.coordinate.latitude - 1.359) < 0.01 and changi.coordinate.longitude > 103.98
    assert _resolve(repository, "Changi T4")[0].display_name == "Changi Airport Terminal 4"
    assert _resolve(repository, "sentossa")[0].display_name == "Sentosa"
    nex = _resolve(repository, "NEX")[0]
    assert abs(nex.coordinate.longitude - 103.8723) < 0.001
    # An exact station name still wins: HarbourFront is the MRT station.
    assert _resolve(repository, "HarbourFront")[0].entity_type == "mrt_station"


def test_landmark_gazetteer_is_inside_singapore_and_unambiguous() -> None:
    from app.landmarks import LandmarkGazetteer, _compact

    gazetteer = LandmarkGazetteer.load()
    assert len(gazetteer.entries) >= 40
    for entry in gazetteer.entries:
        assert 1.2 < entry["latitude"] < 1.48 and 103.6 < entry["longitude"] < 104.05, entry["id"]
        assert entry["coordinate_source"] in {"osm", "curated"}
    for key, items in gazetteer.index.items():
        assert len({entry["id"] for entry, _alias in items}) == 1, key
    assert _compact("Changi T1") == "changit1"
