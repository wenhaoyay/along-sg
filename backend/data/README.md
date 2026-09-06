# Singapore POI data

The development build uses a Singapore-only OpenStreetMap capture obtained through the
public Overpass API. The capture metadata records the capture time, endpoint, query,
geographic scope, attribution and licence URL.

Data © OpenStreetMap contributors. OpenStreetMap data is available under the Open Data
Commons Open Database License (ODbL) 1.0:
https://www.openstreetmap.org/copyright

The large raw POI capture and generated SQLite database are intentionally excluded from
this public portfolio repository. They are development data rather than source code.

The repository layer includes a small curated seed catalog so the data model, taxonomy,
brand normalization and candidate logic remain inspectable without committing the full
snapshot.

In the full development workspace, the OSM capture is transformed into hubs/outlets and
indexed with SQLite FTS5. Omitted opening hours mean unknown; they are never inferred.
Freshness timestamps represent source capture time rather than a guarantee that an
individual business was field-checked on that date.

Any redistributed OSM-derived database should preserve OpenStreetMap attribution and
comply with the ODbL share-alike requirements.
