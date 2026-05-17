"""Ingest context indicators: school exclusions and children looked after.

Outputs data/processed/context_indicators.json (spec section 4.5) and writes
data/processed/ethnicity_crosswalk.json with two documented mappings, the ONS
Census rollup and the DfE school-census rollup.

Indicators:
  permanent_exclusion_rate  England (DfE, academic year 2023/24) LA x ethnicity;
                            Wales (StatsWales, 2023/24) LA overall and
                            all-Wales by ethnicity.
  suspension_rate           As above. Welsh "fixed-term exclusions" are the
                            equivalent of English "suspensions".
  lac_count                 England (year ending March 2025) and Wales
                            (year ending March 2024), LA x ethnicity, a count.

Rate harmonisation: English DfE rates are per 100 pupils; Welsh rates are per
1,000. Every rate record carries rate_per_100 (canonical, used everywhere),
source_rate (the original value) and source_rate_base (100 or 1000).

Welsh exclusions are published by local authority and by ethnicity in two
separate tables with no cross-tabulation, so the Welsh by_ethnicity rows are
all-Wales only. This LA x ethnicity gap is documented, see docs/methods.md.

Looked-after children is a count, not a rate: a true rate by ethnicity needs
a 0 to 17 child population by ethnic group, which is not in scope for v1
(populations.json covers ages 10 to 17). See docs/methods.md.

Coverage is disclosure-aware: source-suppressed cells (DfE 'c', StatsWales
'Confidential', Welsh '[c]'/'[z]') carry a null value, never a modelled one.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
PROCESSED_DIR = REPO_ROOT / "data" / "processed"
RAW_DFE = REPO_ROOT / "data" / "raw" / "dfe"
RAW_WALES = REPO_ROOT / "data" / "raw" / "statswales"

EXCLUSIONS_CSV = RAW_DFE / "exclusions_2023-24" / "data" / "exc_characteristics.csv"
CLA_CSV = RAW_DFE / "cla_2025" / "data" / "la_cla_on_31_march_by_characteristics.csv"
WELSH_CLA_JSON = RAW_WALES / "welsh_cla_by_la_ethnicity.json"
WELSH_EXCL_ODS = RAW_WALES / "welsh_exclusions_2023-24.ods"
GEO_CROSSWALK = PROCESSED_DIR / "geo_crosswalk.json"

CONTEXT_OUT = PROCESSED_DIR / "context_indicators.json"
ETHNICITY_CROSSWALK_OUT = PROCESSED_DIR / "ethnicity_crosswalk.json"

YJB_GROUPS = ["Asian", "Black", "Mixed", "Other", "White"]
WALES_GEO_ID = "rgn-wales"  # all-Wales region, per geographies.json

DFE_EXCL_ETHNICITY = {
    "White": "White",
    "Asian / Asian British": "Asian",
    "Black / African / Caribbean / Black British": "Black",
    "Mixed / Multiple ethnic groups": "Mixed",
    "Any other ethnic group": "Other",
}
DFE_CLA_ETHNICITY = {
    "White": "White",
    "Asian or Asian British": "Asian",
    "Black, African, Caribbean or Black British": "Black",
    "Mixed or Multiple ethnic groups": "Mixed",
    "Other ethnic group": "Other",
}
WELSH_CLA_ETHNICITY = {
    "White": "White",
    "Asian or Asian British": "Asian",
    "Black, African, Caribbean or Black British": "Black",
    "Mixed ethnic groups": "Mixed",
    "Other ethnic group": "Other",
}
# Welsh exclusions Broad Ethnicity to YJB 5. Wales reports Chinese as a Broad
# category separate from Asian. The ONS and YJB schemes place Chinese within
# Asian, but the Welsh exclusion table is a rate table with no usable pupil
# denominator, so the two cannot be exactly recombined. The Welsh "Asian"
# rate is used directly; Chinese, a small group, is not folded in. See the
# methodology note and docs/methods.md.
WELSH_EXCL_BROAD = {
    "White": "White",
    "Black": "Black",
    "Mixed": "Mixed",
    "Asian": "Asian",
    "Any other ethnic group": "Other",
}

WELSH_CLA_NOTE = (
    "Welsh source: counts rounded to the nearest 5; cells below 5 suppressed "
    "by the Welsh Government and carried here as source_suppressed."
)
WELSH_EXCL_LA_NOTE = (
    "Welsh source: rate harmonised to per-100 pupils as rate_per_100; "
    "source_rate is the original Welsh value, per 1,000 pupils. Welsh "
    "'fixed-term exclusions' are the equivalent of English 'suspensions'. "
    "Welsh exclusions are not published as a local-authority by ethnicity "
    "cross-tabulation; this row is local authority level, all ethnicities."
)
WELSH_EXCL_ETH_NOTE = (
    "Welsh source: rate harmonised to per-100 pupils as rate_per_100; "
    "source_rate is per 1,000 pupils. Welsh 'fixed-term exclusions' equate to "
    "English 'suspensions'. Welsh exclusions by ethnicity are published at "
    "all-Wales level only, not by local authority. The Asian rate is the "
    "Welsh 'Asian' category; Wales reports Chinese separately and, with no "
    "pupil denominator in the rate table, it cannot be exactly recombined "
    "into Asian, so Chinese (a small group) is not included here."
)

DFE_OTHER_NOTE = (
    "The DfE detailed (Ethnicity Minor) classification has no subdivision of "
    "the Major category 'Any other ethnic group'; PRISM-R's Other group is "
    "taken from that Major category, which is what the pipeline ingests."
)
DFE_ETHNICITY_CROSSWALK = [
    ("English / Welsh / Scottish / Northern Irish / British", "White", ""),
    ("Irish", "White", ""),
    ("Gypsy / Roma", "White", ""),
    ("Traveller of Irish heritage", "White", ""),
    ("Any other White background", "White", ""),
    ("Indian", "Asian", ""),
    ("Pakistani", "Asian", ""),
    ("Bangladeshi", "Asian", ""),
    ("Chinese", "Asian", ""),
    ("Any other Asian background", "Asian", ""),
    ("African", "Black", ""),
    ("Caribbean", "Black", ""),
    ("Any other Black / African / Caribbean background", "Black", ""),
    ("White and Asian", "Mixed", ""),
    ("White and Black African", "Mixed", ""),
    ("White and Black Caribbean", "Mixed", ""),
    ("Any other Mixed / Multiple ethnic background", "Mixed", ""),
]
ONS_ETHNICITY_CROSSWALK = [
    ("Asian, Asian British or Asian Welsh: Bangladeshi", "Asian", ""),
    ("Asian, Asian British or Asian Welsh: Chinese", "Asian", ""),
    ("Asian, Asian British or Asian Welsh: Indian", "Asian", ""),
    ("Asian, Asian British or Asian Welsh: Pakistani", "Asian", ""),
    ("Asian, Asian British or Asian Welsh: Other Asian", "Asian", ""),
    ("Black, Black British, Black Welsh, Caribbean or African: African", "Black", ""),
    ("Black, Black British, Black Welsh, Caribbean or African: Caribbean", "Black", ""),
    ("Black, Black British, Black Welsh, Caribbean or African: Other Black", "Black", ""),
    ("Mixed or Multiple ethnic groups: White and Asian", "Mixed", ""),
    ("Mixed or Multiple ethnic groups: White and Black African", "Mixed", ""),
    ("Mixed or Multiple ethnic groups: White and Black Caribbean", "Mixed", ""),
    ("Mixed or Multiple ethnic groups: Other Mixed or Multiple ethnic groups", "Mixed", ""),
    ("White: English, Welsh, Scottish, Northern Irish or British", "White", ""),
    ("White: Irish", "White", ""),
    ("White: Gypsy or Irish Traveller", "White", ""),
    ("White: Roma", "White", ""),
    ("White: Other White", "White", ""),
    (
        "Other ethnic group: Arab", "Other",
        "ONS places Arab within the high-level 'Other ethnic group' in its "
        "standard ethnic_group_tb_6a rollup. PRISM-R follows that ONS rollup.",
    ),
    ("Other ethnic group: Any other ethnic group", "Other", ""),
]


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
SUPPRESSION_MARKERS = {"", "c", "x", "z", "[c]", "[z]", "[x]", "confidential", ":", "-", ".."}


def _number(value: object):
    """Return (number, is_suppressed). Source suppression markers yield None."""
    text = "" if value is None else str(value).strip()
    if text.lower() in SUPPRESSION_MARKERS:
        return None, True
    try:
        return float(text), False
    except ValueError:
        return None, True


def _record(geo_id, year, indicator, breakdown, ethnicity, *, value=None,
            rate_per_100=None, source_rate=None, source_rate_base=None,
            suppressed=False, source, reference_period, methodology_note=None) -> dict:
    return {
        "geo_id": geo_id,
        "year": year,
        "indicator": indicator,
        "breakdown": breakdown,
        "ethnicity": ethnicity,
        "value": value,
        "rate_per_100": rate_per_100,
        "source_rate": source_rate,
        "source_rate_base": source_rate_base,
        "disclosure_status": "source_suppressed" if suppressed else "released",
        "source": source,
        "reference_period": reference_period,
        "methodology_note": methodology_note,
    }


# StatsWales tables vary the form of one authority name.
WELSH_LA_ALIASES = {"The Vale of Glamorgan": "Vale of Glamorgan"}


def _welsh_la_codes() -> dict[str, str]:
    geo = json.loads(GEO_CROSSWALK.read_text(encoding="utf-8"))
    return {r["la_name"]: r["la_code"] for r in geo["records"] if r["la_code"].startswith("W06")}


def _welsh_code(la_name: str, la_codes: dict[str, str]) -> str | None:
    return la_codes.get(WELSH_LA_ALIASES.get(la_name, la_name))


# --------------------------------------------------------------------------
# England: DfE exclusions (rate per 100, LA x ethnicity)
# --------------------------------------------------------------------------
def read_dfe_exclusions() -> list[dict]:
    frame = pd.read_csv(EXCLUSIONS_CSV, dtype=str)
    frame = frame[
        (frame["geographic_level"] == "Local authority")
        & (frame["time_period"] == "202324")
        & (frame["education_phase"] == "Total")
    ]
    source = "DfE, Suspensions and permanent exclusions in England"
    period = "academic year 2023/24"
    records = []
    for row in frame.itertuples(index=False):
        if row.characteristic_group == "Total" and row.characteristic == "Total":
            breakdown, ethnicity = "overall", None
        elif row.characteristic_group == "Ethnicity Major" and row.characteristic in DFE_EXCL_ETHNICITY:
            breakdown, ethnicity = "by_ethnicity", DFE_EXCL_ETHNICITY[row.characteristic]
        else:
            continue
        for indicator, raw in (
            ("permanent_exclusion_rate", row.perm_excl_rate),
            ("suspension_rate", row.susp_rate),
        ):
            rate, suppressed = _number(raw)
            records.append(
                _record(
                    row.new_la_code, 2024, indicator, breakdown, ethnicity,
                    rate_per_100=rate, source_rate=rate, source_rate_base=100,
                    suppressed=suppressed, source=source, reference_period=period,
                )
            )
    return records


# --------------------------------------------------------------------------
# Wales: StatsWales exclusions (rate per 1,000, harmonised to per 100)
# --------------------------------------------------------------------------
def read_welsh_exclusions() -> list[dict]:
    records = []
    source = "StatsWales, Permanent and fixed-term exclusions from schools"
    period = "academic year 2023/24"

    # Table 2: by local authority, all ethnicities (the overall breakdown).
    la_codes = _welsh_la_codes()
    table2 = pd.read_excel(WELSH_EXCL_ODS, sheet_name="02_Local_authority", engine="odf", header=3)
    year_col = table2.columns[-1]
    rates = table2[table2["Measure"] == "Rate of exclusions"]
    selectors = {
        "permanent_exclusion_rate": ("Permanent", "Permanent"),
        "suspension_rate": ("Fixed-Term", "Total"),
    }
    for indicator, (category, exc_period) in selectors.items():
        block = rates[(rates["Exclusion Category"] == category) & (rates["Exclusion Period"] == exc_period)]
        for row in block.itertuples(index=False):
            code = _welsh_code(getattr(row, "_4"), la_codes)  # 'Local Authority' column
            if code is None:
                continue
            source_rate, suppressed = _number(row[table2.columns.get_loc(year_col)])
            records.append(
                _record(
                    code, 2024, indicator, "overall", None,
                    rate_per_100=None if suppressed else round(source_rate / 10, 5),
                    source_rate=source_rate, source_rate_base=1000,
                    suppressed=suppressed, source=source, reference_period=period,
                    methodology_note=WELSH_EXCL_LA_NOTE,
                )
            )

    # Table 7: by ethnicity, all-Wales only. Asian combines Welsh Asian and
    # Chinese, recombined exactly from the published counts and rates.
    table7 = pd.read_excel(WELSH_EXCL_ODS, sheet_name="07_Ethnicity", engine="odf", header=3)
    ycol = table7.columns[-1]
    for indicator, category in (("permanent_exclusion_rate", "Permanent"),
                                ("suspension_rate", "Fixed-Term")):
        block = table7[
            (table7["Exclusion Category"] == category)
            & (table7["Detailed Ethnicity"] == "Total")
        ]
        per_broad = {}  # broad label -> (rate, exclusions count)
        for row in block.itertuples(index=False):
            broad = getattr(row, "_3")  # 'Broad Ethnicity'
            if broad not in WELSH_EXCL_BROAD:
                continue
            measure = row[0]
            val, supp = _number(row[table7.columns.get_loc(ycol)])
            per_broad.setdefault(broad, {})[measure] = (val, supp)
        for yjb in YJB_GROUPS:
            broads = [b for b, g in WELSH_EXCL_BROAD.items() if g == yjb]
            parts = [(b, per_broad.get(b, {})) for b in broads]
            rate, suppressed = _combine_welsh_ethnicity(parts)
            records.append(
                _record(
                    WALES_GEO_ID, 2024, indicator, "by_ethnicity", yjb,
                    rate_per_100=None if suppressed else round(rate / 10, 5),
                    source_rate=None if suppressed else round(rate, 5),
                    source_rate_base=1000, suppressed=suppressed,
                    source=source, reference_period=period,
                    methodology_note=WELSH_EXCL_ETH_NOTE,
                )
            )
    return records


def _combine_welsh_ethnicity(parts: list[tuple[str, dict]]):
    """Combine one or more Welsh Broad-ethnicity groups into a single rate per
    1,000. For a single group the rate is taken directly; for several (Asian
    plus Chinese) the pupil denominators are recovered from rate and count and
    summed, an exact recombination, not a model."""
    if len(parts) == 1:
        measures = parts[0][1]
        rate, supp = measures.get("Rate of exclusions", (None, True))
        return rate, supp
    total_excl, total_pupils = 0.0, 0.0
    for _, measures in parts:
        rate, r_supp = measures.get("Rate of exclusions", (None, True))
        excl, e_supp = measures.get("Number of exclusions", (None, True))
        if r_supp or e_supp or rate in (None, 0):
            return None, True
        total_excl += excl
        total_pupils += 1000.0 * excl / rate
    if total_pupils == 0:
        return None, True
    return 1000.0 * total_excl / total_pupils, False


# --------------------------------------------------------------------------
# England: DfE children looked after (count)
# --------------------------------------------------------------------------
def read_dfe_cla() -> list[dict]:
    frame = pd.read_csv(CLA_CSV, dtype=str)
    frame = frame[
        (frame["geographic_level"] == "Local authority")
        & (frame["time_period"] == "2025")
        & (frame["characteristic"] == "Ethnicity")
    ]
    source = "DfE, Children looked after in England including adoptions"
    period = "year ending 31 March 2025"
    records = []
    for row in frame.itertuples(index=False):
        if row.breakdown == "Total":
            breakdown, ethnicity = "overall", None
        elif row.breakdown in DFE_CLA_ETHNICITY:
            breakdown, ethnicity = "by_ethnicity", DFE_CLA_ETHNICITY[row.breakdown]
        else:
            continue
        value, suppressed = _number(row.children_count)
        records.append(
            _record(
                row.new_la_code, 2025, "lac_count", breakdown, ethnicity,
                value=None if suppressed else int(value), suppressed=suppressed,
                source=source, reference_period=period,
            )
        )
    return records


# --------------------------------------------------------------------------
# Wales: StatsWales children looked after (count)
# --------------------------------------------------------------------------
def read_welsh_cla() -> list[dict]:
    la_codes = _welsh_la_codes()
    rows = json.loads(WELSH_CLA_JSON.read_text(encoding="utf-8"))
    source = "StatsWales, Children looked after on 31 March by ethnicity"
    period = "year ending 31 March 2024"
    records = []
    for row in rows:
        if row.get("Year") != "2023-24":
            continue
        code = _welsh_code(row.get("Local Authority"), la_codes)
        if code is None:
            continue
        description = row.get("Data description")
        if description == "Total looked after children":
            breakdown, ethnicity = "overall", None
        elif description in WELSH_CLA_ETHNICITY:
            breakdown, ethnicity = "by_ethnicity", WELSH_CLA_ETHNICITY[description]
        else:
            continue
        value, suppressed = _number(row.get("Data values"))
        records.append(
            _record(
                code, 2024, "lac_count", breakdown, ethnicity,
                value=None if suppressed else int(value), suppressed=suppressed,
                source=source, reference_period=period, methodology_note=WELSH_CLA_NOTE,
            )
        )
    return records


# --------------------------------------------------------------------------
# Output
# --------------------------------------------------------------------------
def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")


def write_ethnicity_crosswalk() -> None:
    _write_json(
        ETHNICITY_CROSSWALK_OUT,
        {
            "meta": {
                "dataset": "ethnicity_crosswalk",
                "generated_by": "pipeline/ingest_dfe.py",
                "schema_note": (
                    "Two documented mappings of source ethnic-group "
                    "classifications to the 5 YJB high-level groups. Each is "
                    "the source's own standard rollup; PRISM-R adopts it "
                    "rather than inventing groupings."
                ),
            },
            "mappings": {
                "ons_census_2021": {
                    "source": "ONS Census 2021 ethnic group (ethnic_group_tb_20b)",
                    "note": "Identical to the ONS high-level categorisation ethnic_group_tb_6a.",
                    "records": [
                        {"source_category": s, "target_category": t, "note": n}
                        for s, t, n in ONS_ETHNICITY_CROSSWALK
                    ],
                },
                "dfe_school_census": {
                    "source": "DfE school census ethnicity (Ethnicity Minor, detailed)",
                    "note": DFE_OTHER_NOTE,
                    "records": [
                        {"source_category": s, "target_category": t, "note": n}
                        for s, t, n in DFE_ETHNICITY_CROSSWALK
                    ],
                },
            },
        },
    )


def build_context_indicators() -> list[dict]:
    records = (
        read_dfe_exclusions()
        + read_welsh_exclusions()
        + read_dfe_cla()
        + read_welsh_cla()
    )
    records.sort(
        key=lambda r: (r["indicator"], r["geo_id"], r["breakdown"], r["ethnicity"] or "")
    )
    return records


# Indicator codes owned by this script. context_indicators.json is co-written
# with pipeline/ingest_home_office.py, which owns stop_search_rate and
# arrest_count. Each writer preserves the other's records and coverage note,
# so the two scripts are order-independent and each is idempotent on its own.
OWNED_INDICATORS = {"permanent_exclusion_rate", "suspension_rate", "lac_count"}

CONTEXT_SCHEMA_NOTE = (
    "One record per geo_id, year, indicator and breakdown, per spec section "
    "4.5. Exclusion rates carry rate_per_100 (canonical), source_rate and "
    "source_rate_base. stop_search_rate carries rate_per_1000 (canonical) and "
    "rate_per_100 (derived). lac_count and arrest_count carry value, a count, "
    "not a rate."
)
CONTEXT_GENERATED_BY = (
    "pipeline/ingest_dfe.py and pipeline/ingest_home_office.py"
)
DFE_COVERAGE_NOTE = (
    "DfE exclusions and looked-after data are at upper-tier local authority "
    "level (around 153 to 155 authorities), not the 318 districts in "
    f"populations.json. Welsh exclusions by ethnicity are all-Wales only "
    f"(geo_id {WALES_GEO_ID}); no Welsh LA-by-ethnicity exclusions "
    "cross-tabulation is published."
)


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


def write_context_indicators(records: list[dict]) -> None:
    foreign: list[dict] = []
    coverage: dict = {}
    if CONTEXT_OUT.exists():
        payload = json.loads(CONTEXT_OUT.read_text(encoding="utf-8"))
        foreign = [
            r for r in payload.get("records", [])
            if r["indicator"] not in OWNED_INDICATORS
        ]
        coverage = dict(payload.get("meta", {}).get("coverage_notes", {}))
    combined = sorted(
        records + foreign,
        key=lambda r: (r["indicator"], r["geo_id"], r["breakdown"], r["ethnicity"] or ""),
    )
    coverage["dfe_and_wales"] = DFE_COVERAGE_NOTE
    _write_json(
        CONTEXT_OUT,
        {
            "meta": {
                "dataset": "context_indicators",
                "generated_by": CONTEXT_GENERATED_BY,
                "schema_note": CONTEXT_SCHEMA_NOTE,
                "indicators": indicator_counts(combined),
                "coverage_notes": coverage,
            },
            "records": combined,
        },
    )


def main() -> int:
    write_ethnicity_crosswalk()
    records = build_context_indicators()
    write_context_indicators(records)

    print(f"context_indicators.json  {len(records)} records")
    for ind in sorted({r["indicator"] for r in records}):
        sub = [r for r in records if r["indicator"] == ind]
        las = len({r["geo_id"] for r in sub})
        supp = sum(1 for r in sub if r["disclosure_status"] == "source_suppressed")
        print(f"  {ind:26s} {len(sub):5d} records, {las:3d} geographies, {supp} source-suppressed")

    print("\nWelsh exclusion sample (LA overall):")
    w = next(r for r in records if r["geo_id"].startswith("W06")
             and r["indicator"] == "suspension_rate" and r["rate_per_100"] is not None)
    print(f"  {w}")
    print("\nAll-Wales by-ethnicity exclusion rows:")
    for r in records:
        if r["geo_id"] == WALES_GEO_ID:
            print(f"  {r['indicator']:24s} {r['ethnicity']:6s} "
                  f"rate_per_100={r['rate_per_100']}  source_rate={r['source_rate']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
