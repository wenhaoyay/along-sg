from __future__ import annotations

import math
from difflib import SequenceMatcher
from datetime import datetime, timedelta

from app.domain import Coordinate, GeocodeMatch, RouteLeg, RouteResult
from app.providers.base import MapProvider
from app.providers.rail_network import (
    FIRST_WAIT_MIN, LINES, TRANSFER_MIN, encode_polyline, load_rail_network,
)


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
        """A plausible route over the real rail network.

        Lines, stations, interchanges and stop counts are Singapore's own (see
        rail_network); only the minutes are estimates. Getting to and from a
        station is a walk, or a feeder bus when the walk would be long - and
        that bus is never given a service number, because an invented "Bus 95"
        is exactly the kind of confident wrong fact mock mode must not show.
        """
        network = load_rail_network()
        direct_km = haversine_km(start, end)
        if direct_km <= WALK_ONLY_KM:
            return self._walk_only(start, end, direct_km, departure)
        boards = {s.code: (s, d) for s, d in network.nearest(start)}
        alights = {s.code: (s, d) for s, d in network.nearest(end)}
        found = None
        if boards and alights:
            found = network.shortest(
                {code: _access(d)[0] + FIRST_WAIT_MIN for code, (_, d) in boards.items()},
                {code: _access(d)[0] for code, (_, d) in alights.items()},
            )
        rides = network.rides(found[1]) if found else []
        if not rides:
            return self._walk_only(start, end, direct_km, departure)
        first_station, last_station = rides[0].stations[0], rides[-1].stations[-1]
        access_km = max(PLATFORM_WALK_KM, haversine_km(start, first_station.coordinate))
        egress_km = max(PLATFORM_WALK_KM, haversine_km(last_station.coordinate, end))

        legs: list[RouteLeg] = []
        clock = departure
        transfers = len(rides) - 1

        def advance(minutes: float):
            nonlocal clock
            begin = clock
            clock = clock + timedelta(minutes=minutes) if clock else None
            return begin, clock

        def path_leg(mode, minutes, metres, origin, dest, points, **extra):
            begin, finish = advance(minutes)
            legs.append(RouteLeg(
                mode, round(minutes, 2), round(metres, 1), origin, dest,
                departure_time=begin, arrival_time=finish,
                geometry=encode_polyline(points), geometry_format="encoded_polyline",
                **extra,
            ))

        minutes, bus = _access(access_km)
        if bus:
            transfers += 1
            path_leg("BUS", minutes, access_km * 1300, "Origin", first_station.name,
                     [start, first_station.coordinate], route_long_name=FEEDER_BUS, agency=None)
        else:
            path_leg("WALK", minutes, access_km * 1000 * WALK_DETOUR, "Origin", first_station.name,
                     [start, first_station.coordinate], to_stop_code=first_station.code)
        for index, ride in enumerate(rides):
            wait = FIRST_WAIT_MIN if index == 0 else TRANSFER_MIN
            advance(wait)
            long_name, agency, _ = LINES.get(ride.stations[0].prefix, (ride.service, None, False))
            path_leg(
                "SUBWAY", ride.minutes,
                sum(haversine_km(a.coordinate, b.coordinate) for a, b in zip(ride.stations, ride.stations[1:])) * 1000,
                ride.stations[0].name, ride.stations[-1].name,
                [station.coordinate for station in ride.stations],
                route_short_name=ride.service, route_long_name=long_name, agency=agency,
                stop_count=ride.stop_count,
                from_stop_code=ride.stations[0].code, to_stop_code=ride.stations[-1].code,
            )
        minutes, bus = _access(egress_km)
        if bus:
            transfers += 1
            advance(FIRST_WAIT_MIN)
            path_leg("BUS", minutes, egress_km * 1300, last_station.name, "Destination",
                     [last_station.coordinate, end], route_long_name=FEEDER_BUS, agency=None)
        else:
            path_leg("WALK", minutes, egress_km * 1000 * WALK_DETOUR, last_station.name, "Destination",
                     [last_station.coordinate, end], from_stop_code=last_station.code)

        walking = [leg for leg in legs if leg.mode == "WALK"]
        duration = (clock - departure).total_seconds() / 60 if departure else (
            sum(leg.duration_minutes for leg in legs) + FIRST_WAIT_MIN + TRANSFER_MIN * (len(rides) - 1)
        )
        return RouteResult(
            duration_minutes=round(duration, 2),
            walking_minutes=round(sum(leg.duration_minutes for leg in walking), 2),
            walking_distance_m=round(sum(leg.distance_m for leg in walking), 1),
            transfers=transfers,
            legs=tuple(legs),
            provider="onemap-mock",
            raw_metadata={"distance_km": round(direct_km, 3), "rail_path": found[1]},
            departure_time=departure,
            arrival_time=clock,
            time_dependent=True,
        )

    def _walk_only(self, start, end, distance_km, departure) -> RouteResult:
        metres = max(distance_km * 1000 * WALK_DETOUR, 1.0)
        minutes = metres / WALK_M_PER_MIN
        arrival = departure + timedelta(minutes=minutes) if departure else None
        leg = RouteLeg(
            "WALK", round(minutes, 2), round(metres, 1), "Origin", "Destination",
            departure_time=departure, arrival_time=arrival,
            geometry=encode_polyline([start, end]), geometry_format="encoded_polyline",
        )
        return RouteResult(
            duration_minutes=round(minutes, 2), walking_minutes=round(minutes, 2),
            walking_distance_m=round(metres, 1), transfers=0, legs=(leg,),
            provider="onemap-mock", raw_metadata={"distance_km": round(distance_km, 3)},
            departure_time=departure, arrival_time=arrival, time_dependent=True,
        )


WALK_M_PER_MIN = 78.0
WALK_DETOUR = 1.25          # streets are not straight lines
WALK_ONLY_KM = 1.0
PLATFORM_WALK_KM = 0.12
MAX_WALK_KM = 1.1           # beyond this a feeder bus is the realistic access
BUS_KMH = 18.0
FEEDER_BUS = "Feeder bus (sample routing)"


def _access(distance_km: float) -> tuple[float, bool]:
    """Minutes to cover a station access leg, and whether it is a bus. Even a
    trip that starts on the station's doorstep walks to the platform."""
    distance_km = max(distance_km, PLATFORM_WALK_KM)
    if distance_km <= MAX_WALK_KM:
        return distance_km * 1000 * WALK_DETOUR / WALK_M_PER_MIN, False
    return 4.0 + distance_km * 1.3 / BUS_KMH * 60, True
