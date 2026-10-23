"""Areas and landmarks, for place lookups the shop catalogue cannot answer.

"Sentosa" used to resolve to a 7-Eleven on Sentosa and "Changi" to an ATM,
because the only places the resolver knew by name were shops. The gazetteer
(`data/singapore-landmark-gazetteer.json`) is small and hand-curated; each
entry carries the names people actually type.
"""

from __future__ import annotations

import difflib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from app.discovery_models import DiscoveryConfidence, DiscoverySource, ResolvedLocation
from app.domain import Coordinate

LANDMARK_GAZETTEER_PATH = Path(__file__).resolve().parents[1] / "data" / "singapore-landmark-gazetteer.json"

# A typo has to be this close to a name to count, and the name long enough
# that closeness means something ("NUS" is one letter from "NTU").
FUZZY_MIN_RATIO = 0.88
FUZZY_MIN_LENGTH = 5


def _compact(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


@dataclass
class LandmarkGazetteer:
    entries: list[dict] = field(default_factory=list)
    index: dict[str, list[tuple[dict, str]]] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path | None = None) -> "LandmarkGazetteer":
        source = path or LANDMARK_GAZETTEER_PATH
        if not source.exists():
            return cls()
        payload = json.loads(source.read_text(encoding="utf-8"))
        gazetteer = cls(entries=list(payload.get("landmarks", [])))
        for entry in gazetteer.entries:
            for alias in (entry["canonical_name"], *entry.get("aliases", ())):
                key = _compact(alias)
                if key:
                    gazetteer.index.setdefault(key, []).append((entry, alias))
        return gazetteer

    def _result(self, entry: dict, alias: str, confidence: DiscoveryConfidence) -> ResolvedLocation:
        return ResolvedLocation(
            internal_id=entry["id"], display_name=entry["canonical_name"],
            coordinate=Coordinate(entry["latitude"], entry["longitude"]),
            entity_type=entry["entity_type"], source=DiscoverySource.LOCAL_CATALOG,
            confidence=confidence, subtitle=entry.get("subtitle"), matched_alias=alias,
            aliases=tuple(entry.get("aliases", ())),
        )

    def match(self, query: str, fuzzy: bool = False) -> ResolvedLocation | None:
        """The one landmark a query names, or None.

        Exact means the query is one of its names, ignoring case, spaces and
        punctuation. Fuzzy allows a typo in a longer name ("sentossa"), and
        only when one landmark is clearly the closest.
        """
        key = _compact(query)
        if not key:
            return None
        exact = {entry["id"]: (entry, alias) for entry, alias in self.index.get(key, ())}
        if len(exact) == 1:
            entry, alias = next(iter(exact.values()))
            return self._result(entry, alias, DiscoveryConfidence.EXACT)
        if exact or not fuzzy or len(key) < FUZZY_MIN_LENGTH:
            return None
        scored: dict[str, tuple[float, dict, str]] = {}
        for alias_key, items in self.index.items():
            if len(alias_key) < FUZZY_MIN_LENGTH:
                continue
            ratio = difflib.SequenceMatcher(None, key, alias_key).ratio()
            if ratio < FUZZY_MIN_RATIO:
                continue
            for entry, alias in items:
                if ratio > scored.get(entry["id"], (0.0,))[0]:
                    scored[entry["id"]] = (ratio, entry, alias)
        ranked = sorted(scored.values(), key=lambda item: -item[0])
        if not ranked or (len(ranked) > 1 and ranked[0][0] - ranked[1][0] < 0.05):
            return None
        _ratio, entry, alias = ranked[0]
        return self._result(entry, alias, DiscoveryConfidence.STRONG)
