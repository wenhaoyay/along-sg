"""Build Along's normalized Singapore rail gazetteer from official LTA files.

Raw LTA downloads are intentionally not committed. This deterministic builder accepts
the Train Station shapefile and the Train Station Codes workbook downloaded from LTA
DataMall and emits the small provider-neutral JSON used at runtime.
"""
from __future__ import annotations

import argparse
import json
import math
import re
from datetime import date
from pathlib import Path

import shapefile
import xlrd


LAT_ORIGIN = math.radians(1.366666)
LON_ORIGIN = math.radians(103.833333)
FALSE_NORTHING = 38744.572
FALSE_EASTING = 28001.642
SCALE_FACTOR = 1.0
A = 6378137.0
F = 1 / 298.257223563


def svy21_to_wgs84(northing: float, easting: float) -> tuple[float, float]:
    """Convert EPSG:3414 SVY21 coordinates to WGS84 without runtime GIS deps."""
    b = A * (1 - F)
    e2 = (2 * F) - (F * F)
    e4, e6 = e2 * e2, e2 * e2 * e2
    a0 = 1 - e2 / 4 - 3 * e4 / 64 - 5 * e6 / 256
    a2 = 3 / 8 * (e2 + e4 / 4 + 15 * e6 / 128)
    a4 = 15 / 256 * (e4 + 3 * e6 / 4)
    a6 = 35 * e6 / 3072
    m0 = A * (a0 * LAT_ORIGIN - a2 * math.sin(2 * LAT_ORIGIN) + a4 * math.sin(4 * LAT_ORIGIN) - a6 * math.sin(6 * LAT_ORIGIN))
    m = m0 + (northing - FALSE_NORTHING) / SCALE_FACTOR
    mu = m / (A * a0)
    e1 = (1 - math.sqrt(1 - e2)) / (1 + math.sqrt(1 - e2))
    j1 = 3 * e1 / 2 - 27 * e1**3 / 32
    j2 = 21 * e1**2 / 16 - 55 * e1**4 / 32
    j3 = 151 * e1**3 / 96
    j4 = 1097 * e1**4 / 512
    fp = mu + j1 * math.sin(2 * mu) + j2 * math.sin(4 * mu) + j3 * math.sin(6 * mu) + j4 * math.sin(8 * mu)
    sin_fp, cos_fp = math.sin(fp), math.cos(fp)
    ep2 = (A * A - b * b) / (b * b)
    c1 = ep2 * cos_fp * cos_fp
    t1 = math.tan(fp) ** 2
    r1 = A * (1 - e2) / (1 - e2 * sin_fp * sin_fp) ** 1.5
    n1 = A / math.sqrt(1 - e2 * sin_fp * sin_fp)
    d = (easting - FALSE_EASTING) / (n1 * SCALE_FACTOR)
    lat = fp - (n1 * math.tan(fp) / r1) * (
        d**2 / 2 - (5 + 3 * t1 + 10 * c1 - 4 * c1**2 - 9 * ep2) * d**4 / 24
        + (61 + 90 * t1 + 298 * c1 + 45 * t1**2 - 252 * ep2 - 3 * c1**2) * d**6 / 720
    )
    lon = LON_ORIGIN + (
        d - (1 + 2 * t1 + c1) * d**3 / 6
        + (5 - 2 * c1 + 28 * t1 - 3 * c1**2 + 8 * ep2 + 24 * t1**2) * d**5 / 120
    ) / cos_fp
    return math.degrees(lat), math.degrees(lon)


def normalized(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def station_aliases(name: str, codes: list[str], station_type: str) -> list[str]:
    kind = "LRT" if station_type.upper() == "LRT" else "MRT"
    aliases = {name, f"{name} {kind}", f"{name} station", f"{name} {kind} station"}
    for code in codes:
        aliases.update({code, re.sub(r"([A-Z]+)(\d+)", r"\1 \2", code)})
    curated = {
        "Choa Chu Kang": {"Chua Chu Kang", "Chuachukang", "CCK"},
        "HarbourFront": {"Harbour Front"},
        "one-north": {"One North", "Onenorth"},
    }
    aliases.update(curated.get(name, set()))
    return sorted(aliases, key=lambda item: (normalized(item) != normalized(name), item.casefold()))


def build(shapefile_path: Path, workbook_path: Path, output_path: Path) -> dict:
    workbook = xlrd.open_workbook(str(workbook_path))
    sheet = workbook.sheet_by_index(0)
    codes_by_name: dict[str, list[str]] = {}
    lines_by_name: dict[str, set[str]] = {}
    for index in range(1, sheet.nrows):
        code = str(sheet.cell_value(index, 0)).strip()
        name = str(sheet.cell_value(index, 1)).strip()
        line = str(sheet.cell_value(index, 3)).strip()
        if code and name:
            codes_by_name.setdefault(normalized(name), []).append(code)
            if line:
                lines_by_name.setdefault(normalized(name), set()).add(line)

    reader = shapefile.Reader(str(shapefile_path))
    field_names = [field[0] for field in reader.fields[1:]]
    grouped: dict[str, dict] = {}
    for shape_record in reader.iterShapeRecords():
        row = dict(zip(field_names, shape_record.record))
        detail = str(row.get("STN_NAM_DE") or row.get("STN_NAM") or "").strip()
        base_name = re.sub(r"\s+(MRT|LRT)\s+STATION$", "", detail, flags=re.I).title()
        base_name = re.sub(r"\bMrt\b", "MRT", re.sub(r"\bLrt\b", "LRT", base_name))
        station_type = str(row.get("TYP_CD_DES") or "MRT").upper()
        point = shape_record.shape.points[0]
        latitude, longitude = svy21_to_wgs84(point[1], point[0])
        key = normalized(base_name)
        entry = grouped.setdefault(key, {
            "name": base_name, "station_type": station_type,
            "coordinates": [],
        })
        entry["coordinates"].append((latitude, longitude))

    stations: list[dict] = []
    alias_total = 0
    for key, value in grouped.items():
        codes = sorted(set(codes_by_name.get(key, [])))
        official_lines = lines_by_name.get(key, set())
        lrt_prefixes = ("BP", "SE", "SW", "PE", "PW", "STC", "PTC")
        station_type = "MRT" if any(
            not code.startswith(lrt_prefixes) for code in codes
        ) else value["station_type"]
        lat = sum(item[0] for item in value["coordinates"]) / len(value["coordinates"])
        lon = sum(item[1] for item in value["coordinates"]) / len(value["coordinates"])
        aliases = station_aliases(value["name"], codes, station_type)
        if station_type == "MRT" and any("LRT" in line.upper() for line in official_lines):
            aliases = sorted(set(aliases) | {
                f"{value['name']} LRT", f"{value['name']} LRT station"
            })
        alias_total += len(aliases)
        stations.append({
            "id": f"lta-rail-{(codes[0] if codes else key).casefold()}",
            "canonical_name": f"{value['name']} {station_type} Station",
            "base_name": value["name"],
            "entity_type": f"{station_type.casefold()}_station",
            "station_codes": codes,
            "lines": sorted(lines_by_name.get(key, set())),
            "latitude": round(lat, 7), "longitude": round(lon, 7),
            "aliases": aliases,
        })
    stations.sort(key=lambda item: (item["base_name"].casefold(), item["id"]))
    payload = {
        "schema_version": "1.0",
        "generated_on": date.today().isoformat(),
        "source": {
            "publisher": "Land Transport Authority of Singapore",
            "datasets": [
                {"name": "Train Station", "edition": "March 2026", "url": "https://datamall.lta.gov.sg/content/datamall/en/static-data.html"},
                {"name": "Train Station Codes and Chinese Names", "edition": "January 2025", "url": "https://datamall.lta.gov.sg/content/datamall/en/static-data.html"},
            ],
            "licence": "Singapore Open Data Licence",
        },
        "station_count": len(stations), "alias_count": alias_total,
        "stations": stations,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--shapefile", type=Path, required=True)
    parser.add_argument("--workbook", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    payload = build(args.shapefile, args.workbook, args.output)
    print(f"Wrote {payload['station_count']} stations and {payload['alias_count']} aliases")


if __name__ == "__main__":
    main()
