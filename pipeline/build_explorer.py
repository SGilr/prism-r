"""Build the geographic explorer data layer.

The explorer shows the road to remand: the conditions that precede a remand
decision. Remand itself is England and Wales only, because the YJB does not
publish it below national level. See docs/methods.md.

Indicators sit at different geographies, and each is served at the level its
publisher releases it, never filled down or averaged up:

  utla  suspension_rate, permanent_exclusion_rate (England, by ethnicity;
        Wales overall only), lac_count. 175 upper-tier authorities: the
        education and children's services authorities.
  lad   imd_score, child_population. 318 lower-tier authorities.
  pfa   stop_search_rate, arrest_count. 42 police force areas.
  rgn   suspension_rate, permanent_exclusion_rate from the DfE's own
        published regional rows, plus child_population summed from
        authorities. 10 regions.

Rates are recomputed from counts at the level displayed wherever the counts
are published; they are never averaged from a lower level's rates. Two
indicators have no published counts and are therefore shown only at the level
their publisher releases: imd_score (an index score) and the Welsh exclusion
rates (per 1,000 with no pupil denominator). Both are flagged
aggregatable: false in the output.

Outputs, all under data/processed/explorer/:

  index.json      every geography with its name, level, parents (region,
                  youth justice service, police force), child population by
                  ethnicity and IMD/WIMD decile within its own nation, plus
                  the indicator catalogue and national comparators. Loaded
                  on first paint.
  {level}.json    the indicator records for one level, loaded on demand.

Every record carries the national value for the same indicator, year and
ethnicity, so the front end never needs a second lookup to show comparison,
and the national comparator's scope (England, or England and Wales) is named
because the DfE publishes England only.

Disclosure: records are read from context_indicators.json after the build's
suppression stage, so suppressed cells arrive with a null value and
disclosure_status source_suppressed or suppressed; this script never
recomputes a rate from a suppressed count.
"""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PROCESSED_DIR = REPO_ROOT / "data" / "processed"
OUTPUT_DIR = PROCESSED_DIR / "explorer"

CONTEXT = PROCESSED_DIR / "context_indicators.json"
POPULATIONS = PROCESSED_DIR / "populations.json"
CROSSWALK = PROCESSED_DIR / "geo_crosswalk.json"
GEOGRAPHIES = PROCESSED_DIR / "geographies.json"

YJB_GROUPS = ["Asian", "Black", "Mixed", "Other", "White"]
NATIONAL_ENGLAND = "nat-england"

# Which level serves each indicator, and how the front end should describe it.
INDICATORS = {
    "suspension_rate": {
        "label": "Suspension rate",
        "level": "utla",
        "unit": "per 100 pupils",
        "value_field": "rate_per_100",
        "aggregatable": True,
        "level_note": "Shown at upper-tier authority level: exclusions are "
                      "published by the responsible education authority, not "
                      "by district.",
        "methods_anchor": "context-indicators",
    },
    "permanent_exclusion_rate": {
        "label": "Permanent exclusion rate",
        "level": "utla",
        "unit": "per 100 pupils",
        "value_field": "rate_per_100",
        "aggregatable": True,
        "level_note": "Shown at upper-tier authority level: exclusions are "
                      "published by the responsible education authority, not "
                      "by district.",
        "methods_anchor": "context-indicators",
    },
    "lac_count": {
        "label": "Children looked after",
        "level": "utla",
        "unit": "children",
        "value_field": "value",
        "aggregatable": True,
        "level_note": "Shown at upper-tier authority level: children's "
                      "services are an upper-tier responsibility. A count, "
                      "not a rate: no 0 to 17 ethnic denominator is published.",
        "methods_anchor": "children-looked-after-counts-rather-than-rates",
    },
    "imd_score": {
        "label": "Child income deprivation",
        "level": "lad",
        "unit": "proportion of children aged 0 to 15",
        "value_field": "value",
        "aggregatable": False,
        "level_note": "Shown at local authority district level, where the "
                      "indices are published. English IDACI and Welsh WIMD "
                      "are parallel scales and are never compared across the "
                      "border.",
        "methods_anchor": "deprivation-child-income-parallel-english-and-welsh-scales",
    },
    "stop_search_rate": {
        "label": "Stop and search rate",
        "level": "pfa",
        "unit": "per 1,000 children aged 10 to 17",
        "value_field": "rate_per_1000",
        "aggregatable": True,
        "level_note": "Shown at police force area level: the Home Office "
                      "publishes stop and search by force, not by local "
                      "authority.",
        "methods_anchor": "stop-and-search-and-arrests",
    },
    "arrest_count": {
        "label": "Arrests of children",
        "level": "pfa",
        "unit": "arrests",
        "value_field": "value",
        "aggregatable": True,
        "level_note": "Shown at police force area level: the Home Office "
                      "publishes arrests by force, not by local authority.",
        "methods_anchor": "stop-and-search-and-arrests",
    },
    "child_population": {
        "label": "Child population aged 10 to 17",
        "level": "lad",
        "unit": "children",
        "value_field": "value",
        "aggregatable": True,
        "level_note": "ONS Census 2021, the denominator behind the rates on "
                      "this page.",
        "methods_anchor": "denominator-basis",
    },
}

LEVELS = {
    "rgn": {"label": "Region", "plural": "regions",
            "boundary": "boundaries/rgn.topo.json"},
    "utla": {"label": "Upper-tier authority", "plural": "upper-tier authorities",
             "boundary": "boundaries/utla.topo.json"},
    "lad": {"label": "Local authority district",
            "plural": "local authority districts",
            "boundary": "boundaries/lad.topo.json"},
    "pfa": {"label": "Police force area", "plural": "police force areas",
            "boundary": "boundaries/pfa.topo.json"},
}


def _compact(record: dict) -> dict:
    """Drop null fields: at this record count the nulls cost real bytes."""
    return {k: v for k, v in record.items() if v is not None}


def _source_key(sources: dict, record: dict) -> str:
    """Register a provenance triple once and return its short key.

    Source, reference period and methodology note repeat across thousands of
    records; holding them once and referencing them keeps each level's
    payload small enough to load on a mobile connection.
    """
    triple = (record["source"], record["reference_period"],
              record.get("methodology_note"))
    for key, value in sources.items():
        if value == triple:
            return key
    key = f"s{len(sources) + 1}"
    sources[key] = triple
    return key


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _level_of(geo_id: str, upper_tier: set[str], lower_tier: set[str],
              wanted: str | None = None) -> str | None:
    """The level a geo_id belongs to, for an indicator served at `wanted`.

    Unitary, metropolitan, London and Welsh authorities are genuinely both
    lower and upper tier, so a bare code is ambiguous: the indicator's own
    level decides which it is. Without `wanted`, upper tier wins, which is
    what the geography index uses.
    """
    if geo_id.startswith("pf-"):
        return "pfa"
    if geo_id.startswith("rgn-"):
        return "rgn"
    if geo_id == NATIONAL_ENGLAND:
        return "nation"
    if wanted == "lad" and geo_id in lower_tier:
        return "lad"
    if wanted == "utla" and geo_id in upper_tier:
        return "utla"
    if geo_id in upper_tier:
        return "utla"
    if geo_id in lower_tier:
        return "lad"
    return None


def build() -> tuple[dict, dict[str, list[dict]], list[str]]:
    context = _load(CONTEXT)["records"]
    populations = _load(POPULATIONS)["records"]
    crosswalk = _load(CROSSWALK)["records"]
    geographies = _load(GEOGRAPHIES)["records"]
    issues: list[str] = []

    upper_tier = {r["utla_code"] for r in crosswalk}
    lower_tier = {r["la_code"] for r in crosswalk}
    names = {r["geo_id"]: r["geo_name"] for r in geographies}
    lad_names = {r["la_code"]: r["la_name"] for r in crosswalk}
    utla_names = {r["utla_code"]: r["utla_name"] for r in crosswalk}
    names.update(lad_names)
    names.update(utla_names)

    # --- Geography index -------------------------------------------------
    lad_to_utla = {r["la_code"]: r["utla_code"] for r in crosswalk}
    lad_to_force = {r["la_code"]: r["parent_force"] for r in crosswalk}
    lad_to_yot = {r["la_code"]: (r["parent_yot"], r["parent_yot_name"])
                  for r in crosswalk}

    # Child population by ethnicity, per lower-tier authority, summed to the
    # other levels. These are counts, so they sum exactly.
    pop_lad: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for record in populations:
        if record["population"] is None or record["ethnicity"] is None:
            continue
        pop_lad[record["geo_id"]][record["ethnicity"]] += record["population"]

    dfe_region_of: dict[str, str] = {}
    for record in context:
        if record.get("region_geo_id"):
            dfe_region_of[record["geo_id"]] = record["region_geo_id"]

    pop_by_level: dict[str, dict[str, dict[str, int]]] = {
        "lad": {k: dict(v) for k, v in pop_lad.items()},
        "utla": defaultdict(lambda: defaultdict(int)),
        "pfa": defaultdict(lambda: defaultdict(int)),
        "rgn": defaultdict(lambda: defaultdict(int)),
    }
    region_of_lad = {r["la_code"]: r.get("parent_region") for r in crosswalk}
    for lad, by_eth in pop_lad.items():
        for ethnicity, count in by_eth.items():
            pop_by_level["utla"][lad_to_utla[lad]][ethnicity] += count
            pop_by_level["pfa"][lad_to_force[lad]][ethnicity] += count
            region = region_of_lad.get(lad)
            if region:
                pop_by_level["rgn"][region][ethnicity] += count

    # IMD decile within each nation, from the published lower-tier scores.
    imd = [r for r in context if r["indicator"] == "imd_score"]
    deciles: dict[str, int] = {}
    for jurisdiction in ("England", "Wales"):
        rows = sorted((r for r in imd if r.get("jurisdiction") == jurisdiction),
                      key=lambda r: -r["value"])
        for position, row in enumerate(rows):
            deciles[row["geo_id"]] = int(position * 10 / len(rows)) + 1

    index_geographies = []
    for geo_id, name in sorted(names.items()):
        level = _level_of(geo_id, upper_tier, lower_tier)
        if level is None or level == "nation":
            continue
        entry = {
            "geo_id": geo_id,
            "geo_name": name,
            "level": level,
            "population_by_ethnicity": dict(pop_by_level[level].get(geo_id, {})),
        }
        if level == "lad":
            yot_id, yot_name = lad_to_yot.get(geo_id, (None, None))
            entry.update({
                "parent_utla": lad_to_utla.get(geo_id),
                "parent_utla_name": utla_names.get(lad_to_utla.get(geo_id)),
                "parent_force": lad_to_force.get(geo_id),
                "parent_force_name": names.get(lad_to_force.get(geo_id)),
                "parent_yot": yot_id,
                "parent_yot_name": yot_name,
                "parent_region": region_of_lad.get(geo_id),
                "imd_decile_in_nation": deciles.get(geo_id),
                "nation": "Wales" if geo_id.startswith("W") else "England",
            })
        elif level == "utla":
            members = [r for r in crosswalk if r["utla_code"] == geo_id]
            yots = sorted({(m["parent_yot"], m["parent_yot_name"]) for m in members})
            forces = sorted({(m["parent_force"], names.get(m["parent_force"]))
                             for m in members})
            entry.update({
                "districts": sorted(m["la_code"] for m in members),
                "parent_yot": yots[0][0] if len(yots) == 1 else None,
                "parent_yot_name": yots[0][1] if len(yots) == 1 else
                                   ", ".join(y[1] for y in yots),
                "parent_force": forces[0][0] if len(forces) == 1 else None,
                "parent_force_name": forces[0][1] if len(forces) == 1 else
                                     ", ".join(f[1] for f in forces),
                "parent_region": region_of_lad.get(members[0]["la_code"]),
                "nation": "Wales" if geo_id.startswith("W") else "England",
            })
        index_geographies.append(entry)
        if geo_id in upper_tier and geo_id in lower_tier:
            # A unitary, metropolitan, London or Welsh authority is both
            # tiers; the explorer lists it at each, so a district-level
            # indicator finds it too.
            twin = dict(entry, level="lad",
                        population_by_ethnicity=dict(pop_lad.get(geo_id, {})),
                        imd_decile_in_nation=deciles.get(geo_id))
            index_geographies.append(twin)

    # --- National comparators ---------------------------------------------
    national: dict[str, dict] = {}
    for record in context:
        if record["geo_id"] != NATIONAL_ENGLAND:
            continue
        key = f"{record['indicator']}|{record['year']}|{record['ethnicity'] or 'overall'}"
        national[key] = {"value": record["rate_per_100"], "scope": "England"}
    # Stop and search and arrests: England and Wales, recomputed from the
    # force counts over the Census denominator (the same basis as rri.json).
    ss_counts: dict[tuple, int] = defaultdict(int)
    for record in context:
        if record["indicator"] not in ("stop_search_rate", "arrest_count"):
            continue
        if record["value"] is None:
            continue
        ss_counts[(record["indicator"], record["year"],
                   record["ethnicity"] or "overall")] += record["value"]
    national_pop = defaultdict(int)
    for by_eth in pop_lad.values():
        for ethnicity, count in by_eth.items():
            national_pop[ethnicity] += count
            national_pop["overall"] += count
    for (indicator, year, ethnicity), count in ss_counts.items():
        key = f"{indicator}|{year}|{ethnicity}"
        if indicator == "stop_search_rate":
            denominator = national_pop.get(ethnicity)
            national[key] = {
                "value": round(count / denominator * 1000, 5) if denominator else None,
                "scope": "England and Wales",
            }
        else:
            national[key] = {"value": count, "scope": "England and Wales"}
    # imd_score: no England-and-Wales comparator exists, because IDACI and
    # WIMD are parallel scales that are never compared across the border. The
    # comparator is the mean within the record's own nation, and the scope
    # says which nation it is.
    for jurisdiction in ("England", "Wales"):
        rows = [r for r in imd if r.get("jurisdiction") == jurisdiction
                and r["value"] is not None]
        if rows:
            mean = sum(r["value"] for r in rows) / len(rows)
            national[f"imd_score|{rows[0]['year']}|overall|{jurisdiction}"] = {
                "value": round(mean, 5),
                "scope": f"{jurisdiction} average",
            }

    # lac_count national: the sum of authority counts actually released.
    lac = defaultdict(int)
    for record in context:
        if record["indicator"] == "lac_count" and record["value"] is not None:
            lac[(record["year"], record["ethnicity"] or "overall")] += record["value"]
    for (year, ethnicity), count in lac.items():
        national[f"lac_count|{year}|{ethnicity}"] = {
            "value": count, "scope": "England and Wales, released cells only"}

    # --- Indicator records by level ---------------------------------------
    by_level: dict[str, list[dict]] = defaultdict(list)
    sources: dict[str, tuple] = {}
    for record in context:
        indicator = record["indicator"]
        spec = INDICATORS.get(indicator)
        if spec is None:
            continue
        geo_id = record["geo_id"]
        level = _level_of(geo_id, upper_tier, lower_tier, spec["level"])
        if level in (None, "nation"):
            continue
        if geo_id == "rgn-wales" and indicator in (
                "suspension_rate", "permanent_exclusion_rate"):
            level = "rgn"  # all-Wales by ethnicity, published at that level
        value = record.get(spec["value_field"])
        ethnicity = record["ethnicity"] or "overall"
        key = f"{indicator}|{record['year']}|{ethnicity}"
        if indicator == "imd_score":
            key = f"{key}|{record.get('jurisdiction')}"
        national_entry = national.get(key, {})
        by_level[level].append(_compact({
            "geo_id": geo_id,
            "indicator": indicator,
            "year": record["year"],
            "ethnicity": ethnicity,
            "value": value,
            "numerator": record.get("numerator"),
            "denominator": record.get("denominator"),
            "source_rate": record.get("source_rate"),
            "source_rate_base": record.get("source_rate_base"),
            "disclosure_status": (record["disclosure_status"]
                                  if record["disclosure_status"] != "released"
                                  else None),
            "suppressed": bool(record.get("suppressed")) or None,
            "national_value": national_entry.get("value"),
            # Carried per record only where the scope varies within an
            # indicator, as it does for imd_score: an English authority is
            # compared with the England average, a Welsh one with Wales.
            "national_scope": (national_entry.get("scope")
                               if indicator == "imd_score" else None),
            "source_key": _source_key(sources, record),
            "jurisdiction": record.get("jurisdiction"),
        }))

    # Child population as a first-class indicator at lower-tier level.
    for geo_id, by_eth in sorted(pop_lad.items()):
        total = sum(by_eth.values())
        for ethnicity in YJB_GROUPS + ["overall"]:
            value = total if ethnicity == "overall" else by_eth.get(ethnicity)
            if value is None:
                continue
            by_level["lad"].append(_compact({
                "geo_id": geo_id, "indicator": "child_population", "year": 2021,
                "ethnicity": ethnicity, "value": value,
                "national_value": national_pop.get(ethnicity),
                "source_key": _source_key(sources, {
                    "source": "ONS Census 2021, dataset RM032",
                    "reference_period": "Census day, 21 March 2021",
                    "methodology_note": None}),
            }))

    for records in by_level.values():
        records.sort(key=lambda r: (r["indicator"], r["geo_id"], r["year"],
                                    r["ethnicity"]))

    # Sanity: every indicator's records must sit at its declared level.
    for indicator, spec in INDICATORS.items():
        wrong = {r["geo_id"] for level, records in by_level.items()
                 for r in records
                 if r["indicator"] == indicator and level != spec["level"]
                 and level != "rgn"}
        if wrong:
            issues.append(f"{indicator}: records outside its declared level "
                          f"{spec['level']}: {sorted(wrong)[:4]}")

    source_catalogue = {
        key: {"source": triple[0], "reference_period": triple[1],
              "methodology_note": triple[2]}
        for key, triple in sources.items()
    }
    # value_type, national scope and the default disclosure status are
    # constant per indicator, so they are declared once here rather than
    # repeated on every record. A record carries disclosure_status only when
    # it is not "released".
    for indicator, spec in INDICATORS.items():
        scopes = {n["scope"] for key, n in national.items()
                  if key.startswith(f"{indicator}|")}
        spec["value_type"] = ("rate" if spec["value_field"].startswith("rate")
                              else "count")
        spec["national_scope"] = scopes.pop() if len(scopes) == 1 else (
            "the authority's own nation" if indicator == "imd_score"
            else "England and Wales")
        spec["default_disclosure_status"] = "released"
        # Where every geography has exactly one record, the year is a
        # property of the source rather than a filter: English IDACI 2025 and
        # Welsh WIMD 2019 are one figure each per authority on parallel
        # scales, not a time series, and filtering by year would blank a
        # nation.
        rows = [r for records in by_level.values() for r in records
                if r["indicator"] == indicator]
        years_by_cell = defaultdict(set)
        for row in rows:
            years_by_cell[(row["geo_id"], row["ethnicity"])].add(row["year"])
        distinct_years = {row["year"] for row in rows}
        spec["single_vintage"] = bool(rows) and len(distinct_years) > 1 and all(
            len(years) == 1 for years in years_by_cell.values())

    index = {
        "meta": {
            "dataset": "explorer_index",
            "generated_by": "pipeline/build_explorer.py",
            "schema_note": (
                "The explorer shows the conditions that precede a remand "
                "decision, not remand outcomes: the YJB does not publish "
                "remand below England and Wales level. Each indicator is "
                "served at the level its publisher releases it and is never "
                "filled down to a smaller geography or averaged up from one. "
                "Rates are recomputed from counts at the level displayed "
                "where counts are published; imd_score and the Welsh "
                "exclusion rates have no published counts and are marked "
                "aggregatable false. Every record carries the national value "
                "for its cell, with the scope named, because the DfE "
                "publishes England while the Home Office figures here are "
                "England and Wales."
            ),
            "levels": LEVELS,
            "indicators": INDICATORS,
            "ethnicities": YJB_GROUPS,
            "counts": {
                "geographies": len(index_geographies),
                "records_by_level": {k: len(v) for k, v in sorted(by_level.items())},
            },
        },
        "geographies": index_geographies,
        "national": national,
        "sources": source_catalogue,
    }
    return index, by_level, issues


def main() -> int:
    index, by_level, issues = build()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    def write(name: str, payload: dict) -> float:
        path = OUTPUT_DIR / name
        with path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"),
                      sort_keys=True)
            handle.write("\n")
        return path.stat().st_size / 1024

    sizes = {"index.json": write("index.json", index)}
    for level, records in sorted(by_level.items()):
        sizes[f"{level}.json"] = write(f"{level}.json", {
            "meta": {"dataset": f"explorer_{level}",
                     "generated_by": "pipeline/build_explorer.py",
                     "level": level, "count": len(records)},
            "records": records,
        })

    for name, kb in sizes.items():
        print(f"  explorer/{name:12s} {kb:8.1f} KB")
    print(f"  total {sum(sizes.values()):.0f} KB across {len(sizes)} files, "
          f"largest {max(sizes.values()):.0f} KB")
    if issues:
        for issue in issues:
            print(f"LEVEL FAILURE: {issue}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
