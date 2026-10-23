"""Fetch the small datasets merged into the OSM catalogue at ingest.

* Post offices - ``amenity=post_office`` is not in the main Overpass capture,
  so a second, bounded query fetches just those. The main capture file is
  never rewritten by this script.
* Retail pharmacies - the Health Sciences Authority's register on
  data.gov.sg, which lists more pharmacies than OSM maps and carries their
  coordinates, so no geocoding is needed.

Both files are written to ``backend/data`` with their source, licence and
capture time recorded in the file itself. Run it by hand; ingestion only ever
reads the saved files.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.poi_ingestion import (  # noqa: E402
    HSA_PHARMACY_FILE,
    OSM_ATTRIBUTION,
    OSM_LICENSE_URL,
    OVERPASS_FALLBACK_URLS,
    POST_OFFICE_FILE,
)

USER_AGENT = "AlongSG/1.0 (Singapore errand planner; supplementary data capture)"
POST_OFFICE_QUERY = """
[out:json][timeout:120];
area["ISO3166-1"="SG"][admin_level=2]->.sg;
(
  nwr(area.sg)[amenity=post_office];
);
out center tags;
""".strip()

HSA_DATASET_ID = "d_bb92615f43de22933e4479558b1f6c36"
HSA_METADATA_URL = f"https://api-production.data.gov.sg/v2/public/api/datasets/{HSA_DATASET_ID}/metadata"
HSA_DOWNLOAD_URL = f"https://api-open.data.gov.sg/v1/public/api/datasets/{HSA_DATASET_ID}/poll-download"
HSA_DATASET_PAGE = f"https://data.gov.sg/datasets/{HSA_DATASET_ID}/view"
SODL_URL = "https://data.gov.sg/open-data-licence"

# Chains as the register spells them, mapped to the brand the catalogue uses.
# (pattern, shop sign, brand)
HSA_BRANDS = (
    (re.compile(r"^watson'?s\b", re.IGNORECASE), "Watsons", "Watsons"),
    (re.compile(r"^guardian\b", re.IGNORECASE), "Guardian", "Guardian"),
    (re.compile(r"^unity\b", re.IGNORECASE), "Unity Pharmacy", "Unity"),
)


def fetch_post_offices(client: httpx.Client) -> dict[str, Any]:
    last_error: Exception | None = None
    for url in OVERPASS_FALLBACK_URLS:
        try:
            response = client.post(
                url, content=POST_OFFICE_QUERY.encode("utf-8"),
                headers={"Content-Type": "text/plain; charset=utf-8"},
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as error:
            last_error = error
            continue
        payload["capture_metadata"] = {
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "source": "OpenStreetMap via Overpass API",
            "scope": "Singapore only, amenity=post_office",
            "attribution": OSM_ATTRIBUTION,
            "license": "ODbL 1.0",
            "license_url": OSM_LICENSE_URL,
            "query": POST_OFFICE_QUERY,
            "endpoint": url,
        }
        return payload
    raise RuntimeError("Every Overpass endpoint refused the post office query") from last_error


def _clean_pharmacy_name(raw: str) -> tuple[str, str | None, str | None]:
    """(display name, brand, branch) from a register entry.

    "Watson's Personal Care Stores Pte Ltd (Bugis Junction)" is a Watsons at
    Bugis Junction; the company name is the licensee, not the shop sign.
    """
    text = " ".join(raw.split())
    branch_match = re.search(r"\(([^)]*)\)\s*$", text)
    branch = branch_match.group(1).strip() if branch_match else None
    base = text[: branch_match.start()].strip() if branch_match else text
    for pattern, sign, brand in HSA_BRANDS:
        if pattern.search(base):
            return sign, brand, branch
    base = re.sub(r"\b(?:pte\.?\s*ltd\.?|private limited|ltd\.?)\s*$", "", base, flags=re.IGNORECASE).strip(" ,.-")
    # The register shouts some names ("SMITH PHARMACY"); a shop sign does not.
    if base.isupper():
        base = _title(base) or base
    return base, None, branch


def _title(value: str | None) -> str | None:
    if not value:
        return None
    return " ".join(word.capitalize() if word.isupper() and len(word) > 2 else word for word in value.split())


def fetch_hsa_pharmacies(client: httpx.Client) -> dict[str, Any]:
    metadata = client.get(HSA_METADATA_URL).json()["data"]
    time.sleep(2)  # data.gov.sg allows only a few calls per 10 seconds
    download = None
    for _attempt in range(5):
        body = client.get(HSA_DOWNLOAD_URL).json()
        download = (body.get("data") or {}).get("url")
        if download:
            break
        time.sleep(3)
    if not download:
        raise RuntimeError("data.gov.sg did not return a download URL for the HSA register")
    geojson = client.get(download).json()
    fetched_at = datetime.now(timezone.utc)
    pharmacies = []
    for feature in geojson.get("features", []):
        properties = feature.get("properties") or {}
        geometry = feature.get("geometry") or {}
        coordinates = geometry.get("coordinates") or ()
        if geometry.get("type") != "Point" or len(coordinates) < 2:
            continue
        name, brand, branch = _clean_pharmacy_name(str(properties.get("PHARMACY_NAME") or ""))
        if not name:
            continue
        unit = " ".join(filter(None, (
            str(properties.get("LEVEL_NO") or "").strip(),
            str(properties.get("UNIT_NO") or "").strip(),
        )))
        pharmacies.append({
            "id": str(properties.get("INC_CRC") or properties.get("OBJECTID_1")),
            "name": name,
            "brand": brand,
            "branch": branch,
            "registered_name": properties.get("PHARMACY_NAME"),
            "house_number": str(properties.get("HOUSE_BLK_NO") or "").strip() or None,
            "street": _title(properties.get("ROAD_NAME")),
            "unit": unit or None,
            "postal_code": str(properties.get("POSTAL_CODE") or "").strip() or None,
            "latitude": round(float(coordinates[1]), 7),
            "longitude": round(float(coordinates[0]), 7),
            "updated": properties.get("FMEL_UPD_D"),
        })
    pharmacies.sort(key=lambda item: item["id"])
    accessed = fetched_at.strftime("%d %B %Y").lstrip("0")
    return {
        "metadata": {
            "dataset": metadata.get("name"),
            "dataset_id": HSA_DATASET_ID,
            "publisher": metadata.get("managedBy"),
            "source_url": HSA_DATASET_PAGE,
            "last_updated": metadata.get("lastUpdatedAt"),
            "fetched_at": fetched_at.isoformat(),
            "license": "Singapore Open Data Licence version 1.0",
            "license_url": SODL_URL,
            "attribution": (
                f"Contains information from {metadata.get('name')} accessed on {accessed} "
                "from data.gov.sg which is made available under the terms of the "
                "Singapore Open Data Licence version 1.0"
            ),
            "coordinates": "WGS84, as published in the dataset; nothing is geocoded",
            "record_count": len(pharmacies),
        },
        "pharmacies": pharmacies,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data-dir", type=Path, default=BACKEND_ROOT / "data")
    parser.add_argument("--skip-post-offices", action="store_true")
    parser.add_argument("--skip-pharmacies", action="store_true")
    args = parser.parse_args()
    with httpx.Client(timeout=httpx.Timeout(150.0), headers={"User-Agent": USER_AGENT}) as client:
        if not args.skip_post_offices:
            payload = fetch_post_offices(client)
            (args.data_dir / POST_OFFICE_FILE).write_text(
                json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8"
            )
            print(f"post offices: {len(payload['elements'])}")
        if not args.skip_pharmacies:
            register = fetch_hsa_pharmacies(client)
            (args.data_dir / HSA_PHARMACY_FILE).write_text(
                json.dumps(register, ensure_ascii=False, indent=1), encoding="utf-8"
            )
            print(f"pharmacies: {register['metadata']['record_count']}")


if __name__ == "__main__":
    main()
