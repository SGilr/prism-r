"""Build simplified police force area boundaries for the static choropleth.

Source: ONS Open Geography portal, Police Force Areas (December 2023),
generalised clipped boundaries (BGC), retrieved as GeoJSON from the ONS
ArcGIS feature service. Police force area boundaries are unchanged since;
the December 2023 vintage matches the 42-force geography used across
PRISM-R.

Output: data/processed/force_boundaries.json, one record per pf- geo_id with
simplified polygon rings in lon/lat, small enough to embed in a build-time
SVG. The Metropolitan Police and City of London Police features are merged
into pf-london, matching geo_crosswalk.json. British Transport Police does
not appear in the boundary file; it has no territory.

Simplification: shapely Douglas-Peucker at 0.02 degrees (roughly 2 km),
islands below a small area threshold dropped, coordinates rounded to two
decimal places, which is sub-pixel at the national map scale the output is
drawn at. The output is for a small static national map, not for geographic
analysis.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from shapely.geometry import MultiPolygon, Polygon, shape

REPO_ROOT = Path(__file__).resolve().parent.parent
RAW_GEOJSON = REPO_ROOT / "data" / "raw" / "geo" / "police_force_areas_dec2023_bgc.geojson"
GEOGRAPHIES = REPO_ROOT / "data" / "processed" / "geographies.json"
OUTPUT = REPO_ROOT / "data" / "processed" / "force_boundaries.json"

SIMPLIFY_TOLERANCE = 0.02  # degrees, roughly 2 km; sub-pixel at national scale
MIN_PART_AREA = 0.002      # square degrees; drops rocks, keeps real islands
ROUND_DP = 2

# ONS force names that do not slugify straight onto a pf- geo_id.
NAME_ALIASES = {
    "Metropolitan Police": "pf-london",
    "London, City of": "pf-london",
    "Devon & Cornwall": "pf-devon-and-cornwall",
    "Dyfed-Powys": "pf-dyfed-powys",
}


def _slug(name: str) -> str:
    text = name.strip().lower().replace("&", "and")
    return "pf-" + "-".join(p for p in text.replace(",", " ").split() if p)


def _rings(geometry) -> list[list[list[float]]]:
    """Simplified exterior rings of a (Multi)Polygon, rounded, holes dropped.

    Holes are irrelevant at this scale: no English or Welsh force area is a
    doughnut around another after City of London is merged into pf-london.
    """
    if isinstance(geometry, Polygon):
        parts = [geometry]
    elif isinstance(geometry, MultiPolygon):
        parts = list(geometry.geoms)
    else:
        raise ValueError(f"unexpected geometry type {geometry.geom_type}")
    rings = []
    for part in parts:
        if part.area < MIN_PART_AREA:
            continue
        simplified = part.simplify(SIMPLIFY_TOLERANCE, preserve_topology=True)
        ring = [
            [round(x, ROUND_DP), round(y, ROUND_DP)]
            for x, y in simplified.exterior.coords
        ]
        if len(ring) >= 4:
            rings.append(ring)
    return rings


def build_boundaries() -> list[dict]:
    raw = json.loads(RAW_GEOJSON.read_text(encoding="utf-8"))
    geographies = json.loads(GEOGRAPHIES.read_text(encoding="utf-8"))["records"]
    valid = {r["geo_id"] for r in geographies if r["geo_type"] == "police_force"}
    names = {r["geo_id"]: r["geo_name"] for r in geographies
             if r["geo_type"] == "police_force"}

    # Group features by geo_id; the two London forces merge here.
    grouped: dict[str, list] = {}
    for feature in raw["features"]:
        pfa_name = feature["properties"]["PFA23NM"]
        geo_id = NAME_ALIASES.get(pfa_name, _slug(pfa_name))
        if geo_id not in valid:
            raise ValueError(f"boundary force {pfa_name!r} -> {geo_id!r} "
                             "is not a known police force geography")
        grouped.setdefault(geo_id, []).append(shape(feature["geometry"]))

    missing = valid - set(grouped)
    if missing:
        raise ValueError(f"no boundary for force(s): {sorted(missing)}")

    records = []
    for geo_id in sorted(grouped):
        rings: list = []
        for geometry in grouped[geo_id]:
            rings.extend(_rings(geometry))
        records.append({
            "geo_id": geo_id,
            "geo_name": names[geo_id],
            "rings": rings,
        })
    return records


def write_boundaries(records: list[dict]) -> None:
    payload = {
        "meta": {
            "dataset": "force_boundaries",
            "generated_by": "pipeline/build_force_boundaries.py",
            "source": (
                "ONS Open Geography portal, Police Force Areas (December "
                "2023), generalised clipped boundaries (BGC)"
            ),
            "source_publication_date": "2024",
            "crs": "EPSG:4326, lon/lat",
            "schema_note": (
                "One record per pf- geo_id. rings holds simplified exterior "
                "polygon rings as [lon, lat] pairs, Douglas-Peucker at "
                f"{SIMPLIFY_TOLERANCE} degrees, parts below {MIN_PART_AREA} "
                "square degrees dropped, holes dropped. Metropolitan and City "
                "of London Police are merged into pf-london. For the static "
                "national choropleth only; not for geographic analysis."
            ),
            "counts": {
                "forces": len(records),
                "rings": sum(len(r["rings"]) for r in records),
                "points": sum(len(ring) for r in records for ring in r["rings"]),
            },
        },
        "records": records,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")


def main() -> int:
    records = build_boundaries()
    write_boundaries(records)
    points = sum(len(ring) for r in records for ring in r["rings"])
    size_kb = OUTPUT.stat().st_size / 1024
    print(f"force_boundaries.json  {len(records)} forces, "
          f"{sum(len(r['rings']) for r in records)} rings, {points} points, "
          f"{size_kb:.0f} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
