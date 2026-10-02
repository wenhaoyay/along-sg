"""Singapore's rail network, built from the LTA gazetteer, for offline routing.

Mock mode used to name a line by hashing the trip distance, so Punggol could
board the "NS line" - a fact any Singaporean reader sees is wrong in a second.
This graph is built from the station codes themselves: a code is a line and
an ordinal (NE17), consecutive ordinals on a line are neighbours, and the codes
one station carries are its interchanges. The few links the numbering does not
express (the Circle Line's Marina Bay spur, the Changi Airport branch, the LRT
loops) are listed explicitly. Timings are estimates; the network is real.
"""

from __future__ import annotations

import heapq
import json
import math
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from app.domain import Coordinate

GAZETTEER_PATH = Path(__file__).resolve().parents[2] / "data" / "singapore-transit-gazetteer.json"

# prefix -> (long name as OneMap writes it, agency, is LRT)
LINES: dict[str, tuple[str, str, bool]] = {
    "NS": ("NORTH SOUTH LINE", "SMRT Corporation", False),
    "EW": ("EAST WEST LINE", "SMRT Corporation", False),
    "CG": ("EAST WEST LINE", "SMRT Corporation", False),
    "NE": ("NORTH EAST LINE", "SBS Transit", False),
    "CC": ("CIRCLE LINE", "SMRT Corporation", False),
    "CE": ("CIRCLE LINE", "SMRT Corporation", False),
    "DT": ("DOWNTOWN LINE", "SBS Transit", False),
    "TE": ("THOMSON-EAST COAST LINE", "SMRT Corporation", False),
    "BP": ("BUKIT PANJANG LRT", "SMRT Corporation", True),
    "SE": ("SENGKANG LRT", "SBS Transit", True),
    "SW": ("SENGKANG LRT", "SBS Transit", True),
    "PE": ("PUNGGOL LRT", "SBS Transit", True),
    "PW": ("PUNGGOL LRT", "SBS Transit", True),
    "STC": ("SENGKANG LRT", "SBS Transit", True),
    "PTC": ("PUNGGOL LRT", "SBS Transit", True),
}
# The service a traveller boards: the Marina Bay spur is the Circle Line,
# whatever its codes say.
SERVICE = {"CE": "CC"}

# Links station numbering does not express.
EXTRA_LINKS = (
    ("CC4", "CE1"), ("CE1", "CE2"),       # Promenade - Bayfront - Marina Bay
    ("CG1", "CG2"),                       # Expo - Changi Airport
    ("BP13", "BP6"),                      # Bukit Panjang LRT loop closes
    ("STC", "SE1"), ("SE5", "STC"),       # Sengkang East loop
    ("STC", "SW1"), ("SW8", "STC"),       # Sengkang West loop
    ("PTC", "PE1"), ("PE7", "PTC"),       # Punggol East loop
    ("PTC", "PW1"), ("PW7", "PTC"),       # Punggol West loop
)
HUBS = {"STC", "PTC"}
# Track that belongs to a branch service though one end carries another code.
BRANCH_RIDES = {frozenset(("EW4", "CG1")): "CG"}

MRT_KMH, LRT_KMH = 40.0, 25.0
STOP_DWELL_MIN = 0.5
TRANSFER_MIN = 4.0
FIRST_WAIT_MIN = 3.0


@dataclass(frozen=True)
class Station:
    code: str
    name: str
    coordinate: Coordinate

    @property
    def prefix(self) -> str:
        return re.match(r"[A-Z]+", self.code).group()

    @property
    def service(self) -> str:
        return SERVICE.get(self.prefix, self.prefix)


@dataclass(frozen=True)
class Ride:
    """One train boarded and ridden without changing: what a timeline shows."""

    service: str
    stations: tuple[Station, ...]
    minutes: float

    @property
    def stop_count(self) -> int:
        return len(self.stations) - 1


def haversine_km(first: Coordinate, second: Coordinate) -> float:
    lat1, lat2 = math.radians(first.latitude), math.radians(second.latitude)
    dlat, dlon = lat2 - lat1, math.radians(second.longitude - first.longitude)
    value = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 6371.0 * 2 * math.atan2(math.sqrt(value), math.sqrt(1 - value))


def _ordinal(code: str) -> int | None:
    match = re.fullmatch(r"[A-Z]+(\d+)", code)
    return int(match.group(1)) if match else None


class RailNetwork:
    def __init__(self, stations: list[Station], interchanges: list[tuple[str, ...]]):
        self.stations = {station.code: station for station in stations}
        self.edges: dict[str, list[tuple[str, float, bool]]] = {code: [] for code in self.stations}
        by_prefix: dict[str, list[Station]] = {}
        for station in stations:
            if _ordinal(station.code) is not None:
                by_prefix.setdefault(station.prefix, []).append(station)
        for prefix, members in by_prefix.items():
            members.sort(key=lambda station: _ordinal(station.code))
            for first, second in zip(members, members[1:]):
                self._ride(first.code, second.code)
        for first, second in EXTRA_LINKS:
            if first in self.stations and second in self.stations:
                self._ride(first, second)
        # The Changi Airport branch is a shuttle out of Tanah Merah: a ride of
        # its own, so everyone changes there (see BRANCH_RIDES).
        if "EW4" in self.stations and "CG1" in self.stations:
            self._ride("EW4", "CG1")
        for codes in interchanges:
            present = [code for code in codes if code in self.stations]
            for index, first in enumerate(present):
                for second in present[index + 1:]:
                    self._link(first, second, TRANSFER_MIN, True)

    def _ride(self, first: str, second: str) -> None:
        a, b = self.stations[first], self.stations[second]
        speed = LRT_KMH if LINES.get(a.prefix, ("", "", False))[2] else MRT_KMH
        minutes = haversine_km(a.coordinate, b.coordinate) * 1.15 / speed * 60 + STOP_DWELL_MIN
        self._link(first, second, minutes, False)

    def _link(self, first: str, second: str, minutes: float, transfer: bool) -> None:
        self.edges[first].append((second, minutes, transfer))
        self.edges[second].append((first, minutes, transfer))

    def nearest(self, point: Coordinate, limit: int = 4, within_km: float = 3.0) -> list[tuple[Station, float]]:
        ranked = sorted(
            ((station, haversine_km(point, station.coordinate)) for station in self.stations.values()),
            key=lambda item: item[1],
        )
        seen: set[str] = set()
        result: list[tuple[Station, float]] = []
        for station, distance in ranked:
            if distance > within_km:
                break
            if station.name in seen:
                continue
            seen.add(station.name)
            result.append((station, distance))
            if len(result) == limit:
                break
        return result

    def shortest(
        self,
        sources: dict[str, float],
        targets: dict[str, float],
    ) -> tuple[float, list[str]] | None:
        """Dijkstra from several boarding stations (each with its access cost)
        to several alighting stations (each with its egress cost)."""
        best: dict[str, float] = {}
        previous: dict[str, str] = {}
        heap = [(cost, code) for code, cost in sources.items()]
        heapq.heapify(heap)
        for cost, code in heap:
            best[code] = cost
        winner: tuple[float, str] | None = None
        while heap:
            cost, code = heapq.heappop(heap)
            if cost > best.get(code, math.inf):
                continue
            if winner is not None and cost >= winner[0]:
                break
            if code in targets:
                total = cost + targets[code]
                if winner is None or total < winner[0]:
                    winner = (total, code)
            for neighbour, minutes, _ in self.edges[code]:
                candidate = cost + minutes
                if candidate < best.get(neighbour, math.inf):
                    best[neighbour] = candidate
                    previous[neighbour] = code
                    heapq.heappush(heap, (candidate, neighbour))
        if winner is None:
            return None
        path = [winner[1]]
        while path[-1] in previous:
            path.append(previous[path[-1]])
        path.reverse()
        return winner[0], path

    def rides(self, path: list[str]) -> list[Ride]:
        """Split a station path into the trains a traveller actually boards.
        Walking between the codes of one interchange is not a ride."""
        rides: list[Ride] = []
        current: list[Station] = []
        service: str | None = None
        minutes = 0.0

        def close() -> None:
            if len(current) > 1:
                rides.append(Ride(service or current[0].service, tuple(current), minutes))

        for first, second in zip(path, path[1:]):
            a, b = self.stations[first], self.stations[second]
            edge = next(edge for edge in self.edges[first] if edge[0] == second)
            if edge[2]:  # walking between the codes of one interchange
                close()
                current, service, minutes = [], None, 0.0
                continue
            # A town-centre hub (STC, PTC) belongs to both of its loops, so it
            # never decides the service; leaving it onto the other loop does.
            b_service = BRANCH_RIDES.get(frozenset((first, second))) or (
                None if b.prefix in HUBS else b.service
            )
            if service is not None and b_service is not None and b_service != service:
                close()
                current, service, minutes = [], None, 0.0
            if not current:
                current = [a]
            current.append(b)
            service = service or b_service or (None if a.prefix in HUBS else a.service)
            minutes += edge[1]
        close()
        return rides


@lru_cache(maxsize=1)
def load_rail_network(path: Path = GAZETTEER_PATH) -> RailNetwork:
    payload = json.loads(path.read_text(encoding="utf-8"))
    stations: list[Station] = []
    interchanges: list[tuple[str, ...]] = []
    for entry in payload["stations"]:
        point = Coordinate(entry["latitude"], entry["longitude"])
        codes = tuple(entry["station_codes"])
        name = entry["canonical_name"]
        stations.extend(Station(code, name, point) for code in codes)
        if len(codes) > 1:
            interchanges.append(codes)
    return RailNetwork(stations, interchanges)


def encode_polyline(points: list[Coordinate], precision: int = 5) -> str:
    factor = 10**precision
    output: list[str] = []
    last_lat = last_lon = 0
    for point in points:
        lat, lon = round(point.latitude * factor), round(point.longitude * factor)
        for delta in (lat - last_lat, lon - last_lon):
            value = ~(delta << 1) if delta < 0 else delta << 1
            while value >= 0x20:
                output.append(chr((0x20 | (value & 0x1F)) + 63))
                value >>= 5
            output.append(chr(value + 63))
        last_lat, last_lon = lat, lon
    return "".join(output)
