from __future__ import annotations

import math
from difflib import SequenceMatcher
from datetime import datetime, timedelta

from app.domain import Coordinate, GeocodeMatch, RouteLeg, RouteResult
from app.providers.base import MapProvider


MOCK_PLACES = (
    GeocodeMatch("Punggol MRT", Coordinate(1.4052, 103.9024), "828868"),
    GeocodeMatch("Orchard MRT", Coordinate(1.3043, 103.8322), "238878"),
    GeocodeMatch("Jurong East MRT", Coordinate(1.3331, 103.7422), "609731"),
    GeocodeMatch("Tampines MRT", Coordinate(1.3533, 103.9451), "529538"),
    GeocodeMatch("Serangoon MRT", Coordinate(1.3507, 103.8488), "556083"),
    GeocodeMatch("Bugis MRT", Coordinate(1.3008, 103.8559), "188024"),
    GeocodeMatch("VivoCity", Coordinate(1.2643, 103.8223), "098585"),
    GeocodeMatch("Toa Payoh MRT", Coordinate(1.3326, 103.8476), "319191"),
    GeocodeMatch("Choa Chu Kang MRT Station", Coordinate(1.3854, 103.7443), "689810", "10 Choa Chu Kang Avenue 4", "station"),
    GeocodeMatch("Choa Chu Kang Bus Interchange", Coordinate(1.3858, 103.7442), "689812", "Choa Chu Kang Loop", "station"),
    GeocodeMatch("Fajar LRT Station", Coordinate(1.3845, 103.7708), "677728", "Fajar Road", "station"),
    GeocodeMatch("Boon Lay MRT Station", Coordinate(1.3386, 103.7061), "649846", "301 Boon Lay Way", "station"),
    GeocodeMatch("National University of Singapore", Coordinate(1.2966, 103.7764), "119077", "21 Lower Kent Ridge Road", "place"),
    GeocodeMatch("Jurong Point", Coordinate(1.3397, 103.7068), "648886", "1 Jurong West Central 2", "mall"),
)


# (short name, long name, is_rail, agency)
_MOCK_LINES = (
    ("NE", "NORTH EAST LINE", True, "SBS Transit"),
    ("NS", "NORTH SOUTH LINE", True, "SMRT Corporation"),
    ("CC", "CIRCLE LINE", True, "SMRT Corporation"),
    ("DT", "DOWNTOWN LINE", True, "SBS Transit"),
    ("95", "SBST BUS 95", False, "SBS Transit"),
    ("196", "SBST BUS 196", False, "SBS Transit"),
)


def haversine_km(first: Coordinate, second: Coordinate) -> float:
    radius_km = 6371.0
    lat1, lat2 = math.radians(first.latitude), math.radians(second.latitude)
    delta_lat = math.radians(second.latitude - first.latitude)
    delta_lon = math.radians(second.longitude - first.longitude)
    value = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lon / 2) ** 2
    )
    return radius_km * 2 * math.atan2(math.sqrt(value), math.sqrt(1 - value))


class MockOneMapProvider(MapProvider):
    @property
    def supports_departure_time_routing(self) -> bool:
        return True

    async def geocode(self, query: str, limit: int = 5) -> list[GeocodeMatch]:
        needle = query.strip().casefold()
        exact = [place for place in MOCK_PLACES if needle == place.label.casefold()]
        partial = [place for place in MOCK_PLACES if needle in place.label.casefold() and place not in exact]
        if exact or partial:
            return (exact + partial)[:limit]
        compact = "".join(character for character in needle if character.isalnum())
        ranked = sorted(
            ((SequenceMatcher(None, compact, "".join(c for c in place.label.casefold() if c.isalnum())).ratio(), place)
             for place in MOCK_PLACES),
            key=lambda item: item[0], reverse=True,
        )
        return [place for score, place in ranked if score >= 0.48][:limit]

    async def route_public_transport(
        self,
        start: Coordinate,
        end: Coordinate,
        departure: datetime | None = None,
    ) -> RouteResult:
        distance_km = haversine_km(start, end)
        walking_distance_m = min(900.0, 220.0 + distance_km * 42.0)
        walking_minutes = walking_distance_m / 78.0
        transfers = 0 if distance_km < 7.0 else (1 if distance_km < 18.0 else 2)
        transit_minutes = distance_km / 26.0 * 60.0 + 3.0 + transfers * 2.5
        duration = walking_minutes + transit_minutes
        # Deterministic but plausible service identity, so the journey timeline
        # can be developed and tested without live OneMap credentials. Derived
        # from the distance so a given journey always names the same service.
        line = _MOCK_LINES[int(distance_km * 10) % len(_MOCK_LINES)]
        is_rail = line[2]
        # Deterministic stop identifiers of the right shape for the mode: a bus
        # stop is a five-digit LTA BusStopCode, a station is a line code plus an
        # ordinal. Without these the live-arrivals path cannot be exercised
        # offline at all - and getting the shapes right is the point, since the
        # client decides whether to ask DataMall by testing for five digits.
        seed = int(distance_km * 1000)
        board_code = f"{line[0]}{seed % 30 + 1}" if is_rail else f"{seed % 90000 + 10000:05d}"
        alight_code = (
            f"{line[0]}{seed % 30 + 4}" if is_rail else f"{(seed * 7) % 90000 + 10000:05d}"
        )
        walk_minutes = walking_minutes / 2
        board_at = departure + timedelta(minutes=walk_minutes) if departure else None
        alight_at = (
            board_at + timedelta(minutes=transit_minutes) if board_at is not None else None
        )
        legs = (
            RouteLeg(
                "WALK", walk_minutes, walking_distance_m / 2, "Origin", "Stop",
                departure_time=departure, arrival_time=board_at,
                to_stop_code=board_code,
            ),
            RouteLeg(
                "SUBWAY" if is_rail else "BUS",
                transit_minutes, distance_km * 1000, "Stop", "Stop",
                route_short_name=line[0], route_long_name=line[1], agency=line[3],
                stop_count=max(1, round(distance_km / 1.4)),
                departure_time=board_at, arrival_time=alight_at,
                from_stop_code=board_code, to_stop_code=alight_code,
            ),
            RouteLeg(
                "WALK", walk_minutes, walking_distance_m / 2, "Stop", "Destination",
                departure_time=alight_at,
                arrival_time=(
                    alight_at + timedelta(minutes=walk_minutes)
                    if alight_at is not None
                    else None
                ),
                from_stop_code=alight_code,
            ),
        )
        return RouteResult(
            duration_minutes=round(duration, 2),
            walking_minutes=round(walking_minutes, 2),
            walking_distance_m=round(walking_distance_m, 1),
            transfers=transfers,
            legs=legs,
            provider="onemap-mock",
            raw_metadata={"distance_km": round(distance_km, 3)},
            departure_time=departure,
            arrival_time=departure + timedelta(minutes=duration) if departure else None,
            time_dependent=True,
        )
