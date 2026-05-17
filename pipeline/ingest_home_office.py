"""Ingest Home Office stop and search and arrests at police force level.

Source: Home Office, Police powers and procedures: stop and search, arrests
and mental health detentions, England and Wales, year ending 31 March 2025,
published 6 November 2025. Open data tables, retrieved from gov.uk. See
docs/data-sources.md.

Outputs, appended to data/processed/context_indicators.json (spec 4.5):

  stop_search_rate  police force area, overall and by ethnicity. A PRISM-R
                    derived rate: searches of children aged 10 to 17 over the
                    Census 2021 child population (10 to 17) for the force
                    area. rate_per_1000 is canonical, the Home Office and ONS
                    convention; rate_per_100 is derived. value carries the
                    search count.
  arrest_count      police force area, overall and by ethnicity. A count, not
                    a rate, per the same reasoning as lac_count: see
                    docs/methods.md.

context_indicators.json is co-written with pipeline/ingest_dfe.py. This script
owns stop_search_rate and arrest_count and preserves the exclusion and
looked-after records; the two scripts are order-independent.

Geography: the Home Office publishes by police force area. The 43 territorial
forces map to the 42 pf- geographies; the Metropolitan Police and City of
London Police both fold into pf-london, matching geo_crosswalk.json. British
Transport Police has no resident-population base and no local authority, so it
is excluded; this is a documented gap.

Ethnicity: both datasets are rolled up to the YJB 5 groups from self-defined
ethnicity. Stop and search also publishes a combined officer/self-defined
column, but it collapses Mixed and Other, so self-defined is used for both
datasets for a consistent five-group split. Searches and arrests with a 'not
stated' self-defined ethnicity are counted in the overall figure but cannot be
assigned to a group; the national not-stated counts are recorded in the meta
block.

The pipeline also extends data/processed/rri.json with national stop_search
and arrest decision points; that is done by pipeline/compute_rri.py, which
reads the by-ethnicity records written here.
"""

from __future__ import annotations

import json
import sys
import xml.sax
import zipfile
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PROCESSED_DIR = REPO_ROOT / "data" / "processed"
RAW_HO = REPO_ROOT / "data" / "raw" / "home-office"

SS_ODS = RAW_HO / "stop-search-open-data-tables-mar21-mar25.ods"
ARR_ODS = RAW_HO / "arrests-open-data-tables-mar25.ods"

CONTEXT_OUT = PROCESSED_DIR / "context_indicators.json"
POPULATIONS = PROCESSED_DIR / "populations.json"
GEO_CROSSWALK = PROCESSED_DIR / "geo_crosswalk.json"
GEOGRAPHIES = PROCESSED_DIR / "geographies.json"

YJB_GROUPS = ["Asian", "Black", "Mixed", "Other", "White"]

# Latest published year: year ending 31 March 2025.
LATEST_FY = "2024/25"
YEAR = 2025
REFERENCE_PERIOD = "year ending 31 March 2025"

SS_AGE_BAND = "10-17"
ARR_AGE_BAND = "10 - 17 years"

# Indicator codes owned by this script; see write_context_indicators.
OWNED_INDICATORS = {"stop_search_rate", "arrest_count"}

CONTEXT_SCHEMA_NOTE = (
    "One record per geo_id, year, indicator and breakdown, per spec section "
    "4.5. Exclusion rates carry rate_per_100 (canonical), source_rate and "
    "source_rate_base. stop_search_rate carries rate_per_1000 (canonical) and "
    "rate_per_100 (derived). lac_count and arrest_count carry value, a count. "
    "imd_score carries value as a child income deprivation proportion, with "
    "jurisdiction, measure and source_release; the English and Welsh measures "
    "are parallel scales and are not cross-comparable."
)
CONTEXT_GENERATED_BY = (
    "pipeline/ingest_dfe.py, pipeline/ingest_home_office.py and "
    "pipeline/ingest_imd.py"
)

# Self-defined ethnicity group to YJB 5. "Not Stated" / "Not stated" are
# non-response; "N/A - vehicle search" carries no person.
SS_ETHNICITY_MAP = {
    "White": "White",
    "Black or Black British": "Black",
    "Asian or Asian British": "Asian",
    "Mixed": "Mixed",
    "Other Ethnic Group": "Other",
}
SS_NOT_STATED = "Not Stated"

# The arrests classification changed in 2019/20; from then the Asian and Other
# labels are prefixed "2019/20 onwards -". Only the latest year is ingested,
# so the post-2019/20 labels are the operative ones; the older labels are
# mapped too for resilience.
ARR_ETHNICITY_MAP = {
    "White": "White",
    "Black or Black British": "Black",
    "Mixed": "Mixed",
    "2019/20 onwards - Asian or Asian British": "Asian",
    "Asian or Asian British": "Asian",
    "2019/20 onwards - Other Ethnic Group": "Other",
    "2019/20 onwards - Other Ethnic group": "Other",
    "Chinese/other": "Other",
}
ARR_NOT_STATED = "Not stated"

STOP_SEARCH_NOTE = (
    "PRISM-R derived rate. Numerator: stop and searches of children aged 10 "
    "to 17 recorded in the year ending 31 March 2025, by self-defined "
    "ethnicity. Denominator: ONS Census 2021 population aged 10 to 17 for the "
    "ethnic group in the police force area, from populations.json. "
    "rate_per_1000 is canonical, the Home Office and ONS convention; "
    "rate_per_100 is derived. Searches recorded with a 'not stated' "
    "self-defined ethnicity are counted in the overall rate but cannot be "
    "assigned to an ethnic group. British Transport Police is excluded; it "
    "has no resident-population base."
)
ARREST_NOTE = (
    "Arrests of children aged 10 to 17 recorded in the year ending 31 March "
    "2025, by self-defined ethnicity. Carried as a count, not a rate, for "
    "consistency with lac_count: see docs/methods.md. Arrests recorded with "
    "a 'not stated' self-defined ethnicity are counted in the overall figure "
    "but cannot be assigned to an ethnic group."
)
HOME_OFFICE_COVERAGE_NOTE = (
    "Home Office stop and search and arrests are published by police force "
    "area. The Metropolitan Police and City of London Police both fold into "
    "pf-london. British Transport Police is excluded as it has no "
    "resident-population base. The two ethnicity-unavailable LAs in "
    "populations.json (Isles of Scilly, City of London) contribute no "
    "ethnic-group denominator to their force areas (Devon and Cornwall, "
    "pf-london); the effect is negligible given their small child "
    "populations."
)

SS_SOURCE = "Home Office, Police powers and procedures: stop and search open data tables"
ARR_SOURCE = "Home Office, Police powers and procedures: arrests open data tables"


# --------------------------------------------------------------------------
# Streaming ODS reader
# --------------------------------------------------------------------------
# The Home Office open data files are large (20 to 30 MB ODS, 0.5 million plus
# rows). The odf engine loads the whole workbook into memory and is far too
# slow here, so a streaming SAX reader extracts a single named table.
_NS_TABLE = "urn:oasis:names:tc:opendocument:xmlns:table:1.0"


class _TableHandler(xml.sax.ContentHandler):
    """Collect the rows of one named table from an ODS content.xml."""

    def __init__(self, target: str) -> None:
        self.target = target
        self.rows: list[list[str]] = []
        self._in_target = False
        self._in_row = False
        self._in_cell = False
        self._row: list[str] = []
        self._text: list[str] = []
        self._cell_repeat = 1
        self._done = False

    def startElement(self, name, attrs) -> None:  # noqa: N802
        if self._done:
            return
        if name == "table:table":
            tname = attrs.get((_NS_TABLE, "name")) or attrs.get("table:name")
            self._in_target = tname == self.target
        elif self._in_target and name == "table:table-row":
            self._in_row = True
            self._row = []
        elif self._in_row and name in ("table:table-cell", "table:covered-table-cell"):
            self._in_cell = True
            self._text = []
            self._cell_repeat = int(attrs.get("table:number-columns-repeated") or 1)

    def characters(self, content) -> None:
        if self._in_cell:
            self._text.append(content)

    def endElement(self, name) -> None:  # noqa: N802
        if self._done:
            return
        if name in ("table:table-cell", "table:covered-table-cell") and self._in_cell:
            value = "".join(self._text)
            self._row.extend([value] * min(self._cell_repeat, 1024))
            self._in_cell = False
        elif name == "table:table-row" and self._in_row:
            while self._row and self._row[-1] == "":
                self._row.pop()
            if self._row:
                self.rows.append(self._row)
            self._in_row = False
        elif name == "table:table" and self._in_target:
            self._done = True


def read_ods_table(path: Path, table: str) -> tuple[list[str], list[dict]]:
    """Return (header, records) for one named table of an ODS file.

    Each record is a dict keyed by the header row; short rows are padded with
    empty strings so every field is present.
    """
    handler = _TableHandler(table)
    with zipfile.ZipFile(path) as archive, archive.open("content.xml") as content:
        parser = xml.sax.make_parser()
        parser.setContentHandler(handler)
        parser.parse(content)
    if not handler.rows:
        raise ValueError(f"{path.name}: table {table!r} not found or empty")
    header = handler.rows[0]
    width = len(header)
    records = [
        dict(zip(header, row + [""] * (width - len(row))))
        for row in handler.rows[1:]
        if any(cell.strip() for cell in row)
    ]
    return header, records


# --------------------------------------------------------------------------
# Police force area to geo_id
# --------------------------------------------------------------------------
def _normalise_force(name: str) -> str:
    """Slugify a police force area name to the pf- geo_id stem."""
    text = name.strip().lower().replace("&", "and")
    return "-".join(part for part in text.replace(",", " ").split() if part)


def build_force_lookup() -> dict[str, str]:
    """Map a normalised police force area name to a pf- geo_id.

    Metropolitan Police and City of London Police both map to pf-london.
    British Transport Police maps to None and is dropped by the caller.
    """
    geographies = json.loads(GEOGRAPHIES.read_text(encoding="utf-8"))["records"]
    valid = {r["geo_id"] for r in geographies if r["geo_type"] == "police_force"}
    lookup: dict[str, str] = {}
    for geo_id in valid:
        lookup[geo_id[len("pf-"):]] = geo_id
    # Home Office names that do not slugify straight onto a geo_id.
    lookup["metropolitan-police"] = "pf-london"
    lookup["london-city-of"] = "pf-london"
    lookup["city-of-london"] = "pf-london"
    return lookup


def resolve_force(name: str, lookup: dict[str, str]) -> str | None:
    """Resolve a Home Office force name to a pf- geo_id, or None to drop it."""
    slug = _normalise_force(name)
    if slug == "british-transport-police":
        return None
    geo_id = lookup.get(slug)
    if geo_id is None:
        raise ValueError(f"unmapped police force area: {name!r} ({slug})")
    return geo_id


# --------------------------------------------------------------------------
# Population denominator
# --------------------------------------------------------------------------
def force_population_by_ethnicity() -> tuple[dict, dict]:
    """Aggregate the Census child population to police force area.

    Returns ({(geo_id, ethnicity): population}, {geo_id: total population}).
    The 10 to 17 population is summed across age band and sex for every LA in
    a force area, using the LA to police force mapping in geo_crosswalk.json.
    """
    crosswalk = json.loads(GEO_CROSSWALK.read_text(encoding="utf-8"))["records"]
    la_to_force = {r["la_code"]: r["parent_force"] for r in crosswalk}

    populations = json.loads(POPULATIONS.read_text(encoding="utf-8"))["records"]
    by_eth: dict[tuple[str, str], int] = defaultdict(int)
    by_force: dict[str, int] = defaultdict(int)
    for record in populations:
        if record["population"] is None or record["ethnicity"] is None:
            continue
        force = la_to_force.get(record["geo_id"])
        if force is None:
            raise ValueError(f"LA {record['geo_id']} has no police force mapping")
        by_eth[(force, record["ethnicity"])] += record["population"]
        by_force[force] += record["population"]
    return dict(by_eth), dict(by_force)


# --------------------------------------------------------------------------
# Read the Home Office tables
# --------------------------------------------------------------------------
def _to_int(value: str) -> int:
    return int(value.replace(",", "").strip() or 0)


def read_stop_search(lookup: dict[str, str]) -> tuple[dict, dict, int]:
    """Read stop and search counts for children aged 10 to 17, latest year.

    Returns ({(geo_id, ethnicity): searches}, {geo_id: overall searches},
    national not-stated searches).
    """
    _, records = read_ods_table(SS_ODS, "open_data")
    by_eth: dict[tuple[str, str], int] = defaultdict(int)
    overall: dict[str, int] = defaultdict(int)
    not_stated = 0
    for row in records:
        if row["financial_year"] != LATEST_FY or row["age_group"] != SS_AGE_BAND:
            continue
        geo_id = resolve_force(row["police_force_area"], lookup)
        if geo_id is None:  # British Transport Police
            continue
        count = _to_int(row["number_of_searches"])
        overall[geo_id] += count
        group = SS_ETHNICITY_MAP.get(row["self_defined_ethnicity_group"])
        if group is not None:
            by_eth[(geo_id, group)] += count
        elif row["self_defined_ethnicity_group"] == SS_NOT_STATED:
            not_stated += count
    return dict(by_eth), dict(overall), not_stated


def read_arrests(lookup: dict[str, str]) -> tuple[dict, dict, int]:
    """Read arrest counts for children aged 10 to 17, latest year.

    Returns ({(geo_id, ethnicity): arrests}, {geo_id: overall arrests},
    national not-stated arrests).
    """
    _, records = read_ods_table(ARR_ODS, "OD_5+1")
    by_eth: dict[tuple[str, str], int] = defaultdict(int)
    overall: dict[str, int] = defaultdict(int)
    not_stated = 0
    for row in records:
        if row["financial_year"] != LATEST_FY or row["age_group"] != ARR_AGE_BAND:
            continue
        geo_id = resolve_force(row["police_force_area"], lookup)
        if geo_id is None:
            continue
        count = _to_int(row["number_of_arrests"])
        overall[geo_id] += count
        group = ARR_ETHNICITY_MAP.get(row["self_defined_ethnicity_group"])
        if group is not None:
            by_eth[(geo_id, group)] += count
        elif row["self_defined_ethnicity_group"] == ARR_NOT_STATED:
            not_stated += count
    return dict(by_eth), dict(overall), not_stated


# --------------------------------------------------------------------------
# Build records
# --------------------------------------------------------------------------
def _record(geo_id, indicator, breakdown, ethnicity, value, rate_per_1000,
            rate_per_100, source, note) -> dict:
    return {
        "geo_id": geo_id,
        "year": YEAR,
        "indicator": indicator,
        "breakdown": breakdown,
        "ethnicity": ethnicity,
        "value": value,
        "rate_per_1000": rate_per_1000,
        "rate_per_100": rate_per_100,
        "source_rate": None,
        "source_rate_base": 1000 if indicator == "stop_search_rate" else None,
        "disclosure_status": "released",
        "source": source,
        "reference_period": REFERENCE_PERIOD,
        "methodology_note": note,
    }


def _rates(count: int, population: int) -> tuple[float | None, float | None]:
    """Per-1,000 (canonical) and per-100 (derived) rates, or None if no base."""
    if not population:
        return None, None
    per_1000 = round(count / population * 1000, 5)
    return per_1000, round(per_1000 / 10, 5)


def build_stop_search_records(by_eth, overall, pop_by_eth, pop_total) -> list[dict]:
    records: list[dict] = []
    for geo_id in sorted(overall):
        count = overall[geo_id]
        per_1000, per_100 = _rates(count, pop_total.get(geo_id, 0))
        records.append(
            _record(geo_id, "stop_search_rate", "overall", None, count,
                    per_1000, per_100, SS_SOURCE, STOP_SEARCH_NOTE)
        )
        for group in YJB_GROUPS:
            count = by_eth.get((geo_id, group), 0)
            per_1000, per_100 = _rates(count, pop_by_eth.get((geo_id, group), 0))
            records.append(
                _record(geo_id, "stop_search_rate", "by_ethnicity", group, count,
                        per_1000, per_100, SS_SOURCE, STOP_SEARCH_NOTE)
            )
    return records


def build_arrest_records(by_eth, overall) -> list[dict]:
    records: list[dict] = []
    for geo_id in sorted(overall):
        records.append(
            _record(geo_id, "arrest_count", "overall", None, overall[geo_id],
                    None, None, ARR_SOURCE, ARREST_NOTE)
        )
        for group in YJB_GROUPS:
            records.append(
                _record(geo_id, "arrest_count", "by_ethnicity", group,
                        by_eth.get((geo_id, group), 0), None, None,
                        ARR_SOURCE, ARREST_NOTE)
            )
    return records


# --------------------------------------------------------------------------
# Output
# --------------------------------------------------------------------------
def indicator_counts(records: list[dict]) -> dict:
    """Per-indicator record, geography and source-suppression counts."""
    return {
        ind: {
            "records": sum(1 for r in records if r["indicator"] == ind),
            "geographies": len({r["geo_id"] for r in records if r["indicator"] == ind}),
            "source_suppressed": sum(
                1 for r in records
                if r["indicator"] == ind and r["disclosure_status"] == "source_suppressed"
            ),
        }
        for ind in sorted({r["indicator"] for r in records})
    }


def write_context_indicators(records: list[dict], not_stated: dict) -> dict:
    """Merge the Home Office records into context_indicators.json.

    Preserves records and coverage notes owned by pipeline/ingest_dfe.py.
    """
    if not CONTEXT_OUT.exists():
        raise FileNotFoundError(
            f"{CONTEXT_OUT} not found; run pipeline/ingest_dfe.py first"
        )
    payload = json.loads(CONTEXT_OUT.read_text(encoding="utf-8"))
    foreign = [r for r in payload["records"] if r["indicator"] not in OWNED_INDICATORS]
    combined = sorted(
        records + foreign,
        key=lambda r: (r["indicator"], r["geo_id"], r["breakdown"], r["ethnicity"] or ""),
    )
    coverage = dict(payload.get("meta", {}).get("coverage_notes", {}))
    coverage["home_office"] = HOME_OFFICE_COVERAGE_NOTE

    counts = indicator_counts(combined)
    counts["stop_search_rate"]["self_defined_not_stated"] = not_stated["stop_search"]
    counts["arrest_count"]["self_defined_not_stated"] = not_stated["arrest"]

    new_payload = {
        "meta": {
            "dataset": "context_indicators",
            "generated_by": CONTEXT_GENERATED_BY,
            "schema_note": CONTEXT_SCHEMA_NOTE,
            "indicators": counts,
            "coverage_notes": coverage,
        },
        "records": combined,
    }
    with CONTEXT_OUT.open("w", encoding="utf-8") as handle:
        json.dump(new_payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    return new_payload


def main() -> int:
    lookup = build_force_lookup()
    pop_by_eth, pop_total = force_population_by_ethnicity()

    ss_by_eth, ss_overall, ss_not_stated = read_stop_search(lookup)
    arr_by_eth, arr_overall, arr_not_stated = read_arrests(lookup)

    records = (
        build_stop_search_records(ss_by_eth, ss_overall, pop_by_eth, pop_total)
        + build_arrest_records(arr_by_eth, arr_overall)
    )
    payload = write_context_indicators(
        records, {"stop_search": ss_not_stated, "arrest": arr_not_stated}
    )

    own = [r for r in payload["records"] if r["indicator"] in OWNED_INDICATORS]
    print(f"context_indicators.json  {len(payload['records'])} records "
          f"({len(own)} from Home Office)")
    for ind in ("stop_search_rate", "arrest_count"):
        sub = [r for r in own if r["indicator"] == ind]
        forces = len({r["geo_id"] for r in sub})
        print(f"  {ind:18s} {len(sub):4d} records, {forces} police force areas")
    print(f"  self-defined not stated: stop and search {ss_not_stated:,}, "
          f"arrests {arr_not_stated:,}")

    print("\nNational stop and search of children 10-17, year ending March 2025:")
    nat_ss = {g: sum(v for (_, e), v in ss_by_eth.items() if e == g) for g in YJB_GROUPS}
    nat_arr = {g: sum(v for (_, e), v in arr_by_eth.items() if e == g) for g in YJB_GROUPS}
    nat_pop = {g: sum(v for (_, e), v in pop_by_eth.items() if e == g) for g in YJB_GROUPS}
    print(f"  {'group':7s} {'searches':>10s} {'arrests':>10s} {'population':>12s} "
          f"{'ss/1000':>9s}")
    for g in YJB_GROUPS:
        rate = nat_ss[g] / nat_pop[g] * 1000 if nat_pop[g] else 0
        print(f"  {g:7s} {nat_ss[g]:>10,} {nat_arr[g]:>10,} {nat_pop[g]:>12,} "
              f"{rate:>9.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
