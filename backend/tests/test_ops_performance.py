"""Hot-path caches: hubs by category, and the exact corridor distance."""

from __future__ import annotations

import random
import sqlite3

from app.db import HubRepository
from app.domain import Coordinate
from app.services.candidates import _point_segment_distance_km, distance_to_geometry_km


def test_category_hubs_are_cached_until_the_catalogue_changes(repository: HubRepository) -> None:
    first = repository.find_for_categories(("groceries",))
    assert first
    version = repository.catalogue_version()
    second = repository.find_for_categories(("groceries",))
    assert [hub.id for hub in second] == [hub.id for hub in first]
    # The same frozen objects, from memory, in a list the caller may change.
    assert second[0] is first[0] and second is not first
    second.clear()
    assert repository.find_for_categories(("groceries",))
    assert repository.catalogue_version() == version

    closed = first[0].id
    # Another process (an ingest) writing behind the repository's back.
    with sqlite3.connect(repository.path) as connection:
        connection.execute("UPDATE hubs SET closure_status='closed' WHERE id=?", (closed,))
    assert repository.catalogue_version() != version
    assert closed not in {hub.id for hub in repository.find_for_categories(("groceries",))}


def test_outlet_count_follows_the_catalogue(repository: HubRepository) -> None:
    before = repository.count_outlets(active_only=True)
    with sqlite3.connect(repository.path) as connection:
        connection.execute(
            "UPDATE outlets SET closure_status='closed' WHERE id=(SELECT MIN(id) FROM outlets)"
        )
    assert repository.count_outlets(active_only=True) == before - 1


def test_corridor_distance_is_exactly_the_minimum_over_every_segment() -> None:
    generator = random.Random(11)
    for length in (2, 3, 9, 17, 64, 400):
        latitude, longitude = 1.35, 103.82
        points = []
        for _ in range(length):
            latitude += generator.uniform(-0.004, 0.004)
            longitude += generator.uniform(-0.004, 0.004)
            points.append(Coordinate(latitude, longitude))
        geometry = tuple(points)
        for _ in range(60):
            point = Coordinate(generator.uniform(1.2, 1.47), generator.uniform(103.6, 104.05))
            expected = min(
                _point_segment_distance_km(point, geometry[index], geometry[index + 1])
                for index in range(length - 1)
            )
            assert distance_to_geometry_km(point, geometry) == expected
            # Memoised per geometry, and a list (not indexable by identity) agrees.
            assert distance_to_geometry_km(point, geometry) == expected
            assert distance_to_geometry_km(point, list(geometry)) == expected
    assert distance_to_geometry_km(Coordinate(1.3, 103.8), (Coordinate(1.3, 103.8),)) == float("inf")
