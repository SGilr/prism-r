"""Build TopoJSON boundary layers for the geographic explorer.

Source: ONS Open Geography portal, December 2023 boundaries at BUC
(ultra-generalised clipped) resolution, retrieved as GeoJSON from the ONS
ArcGIS feature service. BUC is the coarsest ONS publishes and is intended
for exactly this use: a small-scale national web map.

Four layers, written to data/processed/boundaries/:

  lad.topo.json    318 lower-tier local authorities (England and Wales).
                   Carries imd_score and child population locally; the
                   exclusion and looked-after indicators are county-level
                   for the 164 shire districts, so the explorer marks them
                   unavailable at this level rather than showing the
                   county's value as if it were local.
  utla.topo.json   175 upper-tier authorities: the geography DfE publishes
                   exclusions and looked-after children at, and the level
                   youth justice services operate at.
  pfa.topo.json    42 police force areas, matching geographies.json, with
                   the Metropolitan and City of London forces dissolved
                   into pf-london.
  rgn.topo.json    10 regions: the 9 English regions plus Wales, the latter
                   dissolved from the 22 Welsh unitary authorities because
                   ONS publishes English regions only.

Every layer is verified to join to data/processed/geo_crosswalk.json (or
geographies.json for forces and regions) by code, with no orphan on either
side; the build fails if any appears. Geometry is simplified and quantised
to keep each payload small enough to load on a mobile connection.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd
import topojson as tp
from shapely.geometry import MultiPolygon

REPO_ROOT = Path(__file__).resolve().parent.parent
RAW_BOUNDARIES = REPO_ROOT / "data" / "raw" / "geo" / "boundaries-2023"
PROCESSED_DIR = REPO_ROOT / "data" / "processed"
OUTPUT_DIR = PROCESSED_DIR / "boundaries"

GEO_CROSSWALK = PROCESSED_DIR / "geo_crosswalk.json"
GEOGRAPHIES = PROCESSED_DIR / "geographies.json"

SOURCE = ("ONS Open Geography portal, December 2023 boundaries, "
          "ultra-generalised clipped (BUC)")
SOURCE_URL = "https://geoportal.statistics.gov.uk/"
RETRIEVAL_DATE = "2026-09-03"

# Simplification in degrees, then quantisation. BUC is already coarse; these
# values remove sub-pixel detail at national map scale without visibly
# changing any boundary.
SIMPLIFY = 0.0012
QUANTISE = 1e5
# Polygon parts below this area (square degrees, roughly 25 hectares) collapse
# to a degenerate sliver at BUC resolution and are dropped before simplifying;
# each geography always keeps its largest part, so no authority disappears
# (the Isles of Scilly are entirely small islands).
MIN_PART_AREA = 3e-6

# ONS police force area names that do not slugify onto a pf- geo_id.
FORCE_ALIASES = {
    "Metropolitan Police": "pf-london",
    "London, City of": "pf-london",
    "Devon & Cornwall": "pf-devon-and-cornwall",
    "Dyfed-Powys": "pf-dyfed-powys",
}
REGION_ALIASES = {"East of England": "rgn-eastern"}


def _slug(prefix: str, name: str) -> str:
    text = name.strip().lower().replace("&", "and")
    return prefix + "-".join(p for p in text.replace(",", " ").split() if p)


def _read(layer: str) -> gpd.GeoDataFrame:
    frame = gpd.read_file(RAW_BOUNDARIES / f"{layer}_2023_BUC.geojson")
    return frame.to_crs(4326)


def _drop_slivers(geometry):
    """Drop sub-pixel polygon parts, always keeping the largest one."""
    if geometry.geom_type == "Polygon":
        return geometry
    parts = sorted(geometry.geoms, key=lambda g: g.area, reverse=True)
    kept = [parts[0]] + [g for g in parts[1:] if g.area >= MIN_PART_AREA]
    return kept[0] if len(kept) == 1 else MultiPolygon(kept)


def _write_topology(frame: gpd.GeoDataFrame, name: str, note: str) -> dict:
    """Simplify, quantise and write one layer; return its manifest entry."""
    frame = frame.copy()
    frame["geometry"] = frame["geometry"].apply(_drop_slivers)
    topology = tp.Topology(
        frame[["geo_id", "geo_name", "geometry"]],
        prequantize=QUANTISE,
        toposimplify=SIMPLIFY,
        shared_coords=False,
        prevent_oversimplify=True,
    )
    payload = json.loads(topology.to_json())
    payload["prism_r"] = {
        "layer": name,
        "features": len(frame),
        "source": SOURCE,
        "source_url": SOURCE_URL,
        "retrieval_date": RETRIEVAL_DATE,
        "simplify_degrees": SIMPLIFY,
        "note": note,
    }
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTPUT_DIR / f"{name}.topo.json"
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"),
                  sort_keys=True)
        handle.write("\n")
    return {"layer": name, "features": len(frame), "kb": path.stat().st_size / 1024}


def _check_join(name: str, boundary_ids: set[str], expected: set[str]) -> list[str]:
    issues = []
    missing = sorted(expected - boundary_ids)
    orphan = sorted(boundary_ids - expected)
    if missing:
        issues.append(f"{name}: {len(missing)} expected geographies without a "
                      f"boundary: {missing[:6]}")
    if orphan:
        issues.append(f"{name}: {len(orphan)} boundaries with no data "
                      f"geography: {orphan[:6]}")
    return issues


def main() -> int:
    crosswalk = json.loads(GEO_CROSSWALK.read_text(encoding="utf-8"))["records"]
    geographies = json.loads(GEOGRAPHIES.read_text(encoding="utf-8"))["records"]
    expected_lad = {r["la_code"] for r in crosswalk}
    expected_utla = {r["utla_code"] for r in crosswalk}
    expected_pfa = {r["geo_id"] for r in geographies if r["geo_type"] == "police_force"}
    expected_rgn = {r["geo_id"] for r in geographies if r["geo_type"] == "region"}

    issues: list[str] = []
    results: list[dict] = []

    # --- Lower-tier local authorities -------------------------------------
    lad = _read("LAD")
    lad = lad[lad["LAD23CD"].str.startswith(("E", "W"))].copy()
    lad["geo_id"] = lad["LAD23CD"]
    lad["geo_name"] = lad["LAD23NM"]
    issues += _check_join("lad", set(lad["geo_id"]), expected_lad)
    results.append(_write_topology(
        lad, "lad",
        "318 lower-tier local authorities, England and Wales, December 2023"))

    # --- Upper-tier authorities -------------------------------------------
    utla = _read("CTYUA")
    utla = utla[utla["CTYUA23CD"].str.startswith(("E", "W"))].copy()
    utla["geo_id"] = utla["CTYUA23CD"]
    utla["geo_name"] = utla["CTYUA23NM"]
    issues += _check_join("utla", set(utla["geo_id"]), expected_utla)
    results.append(_write_topology(
        utla, "utla",
        "175 upper-tier authorities, the level DfE publishes exclusions and "
        "looked-after children at"))

    # --- Police force areas, London dissolved ------------------------------
    pfa = _read("PFA")
    pfa["geo_id"] = [FORCE_ALIASES.get(n, _slug("pf-", n)) for n in pfa["PFA23NM"]]
    pfa = pfa.dissolve(by="geo_id", as_index=False)
    force_names = {r["geo_id"]: r["geo_name"] for r in geographies
                   if r["geo_type"] == "police_force"}
    pfa["geo_name"] = pfa["geo_id"].map(force_names)
    issues += _check_join("pfa", set(pfa["geo_id"]), expected_pfa)
    results.append(_write_topology(
        pfa, "pfa",
        "42 police force areas; the Metropolitan and City of London forces "
        "are dissolved into pf-london, matching the YJB's 42-force geography"))

    # --- Regions: 9 English plus Wales dissolved from Welsh authorities ----
    rgn = _read("RGN")
    rgn["geo_id"] = [REGION_ALIASES.get(n, _slug("rgn-", n)) for n in rgn["RGN23NM"]]
    rgn["geo_name"] = rgn["RGN23NM"]
    wales = lad[lad["geo_id"].str.startswith("W")].dissolve().reset_index(drop=True)
    wales["geo_id"] = "rgn-wales"
    wales["geo_name"] = "Wales"
    regions = gpd.GeoDataFrame(
        pd.concat([rgn[["geo_id", "geo_name", "geometry"]],
                   wales[["geo_id", "geo_name", "geometry"]]], ignore_index=True),
        crs=4326)
    issues += _check_join("rgn", set(regions["geo_id"]), expected_rgn)
    results.append(_write_topology(
        regions, "rgn",
        "10 regions: the 9 English regions from ONS, plus Wales dissolved "
        "from its 22 unitary authorities because ONS publishes English "
        "regions only"))

    for result in results:
        print(f"  {result['layer']:6s} {result['features']:4d} features  "
              f"{result['kb']:7.1f} KB")
    if issues:
        print()
        for issue in issues:
            print(f"JOIN FAILURE: {issue}", file=sys.stderr)
        return 1
    print("\njoin verified: every layer matches its data geography exactly, "
          "no orphans either way")
    return 0


if __name__ == "__main__":
    sys.exit(main())
