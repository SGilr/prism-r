"""Emit one CSV per published chart, with provenance columns.

Every chart on the site has a CSV alongside it. The files are generated here
rather than in the browser so that they are versioned artefacts: checksummed
in manifest.json, byte-reproducible, and citable by URL without running any
JavaScript. The explorer's map view and summary panel are exported in the
browser instead, because they depend on the visitor's filter selection; both
paths use the same columns and the same preamble convention.

Each file carries a commented header naming the tool, the extract basis and
the licence, then the data columns, then source, reference_period and
disclosure_status per row. A suppressed cell exports with an empty value and
its disclosure status. It is never a zero and never a figure: writing a
suppressed value into a download would defeat the suppression that the
pipeline applied upstream, which is the defect recorded in the corrections
section of docs/methods.md.

Outputs go to data/processed/csv/.
"""

from __future__ import annotations

import csv
import io
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
from pipeline.build import PROVENANCE  # noqa: E402
PROCESSED_DIR = REPO_ROOT / "data" / "processed"
OUTPUT_DIR = PROCESSED_DIR / "csv"

SITE_URL = "https://prism-r.howpreventionworks.com"
YJB_GROUPS = ["White", "Black", "Asian", "Mixed", "Other"]

PREAMBLE_TAIL = [
    "PRISM-R, an open tool for analysis of remand disproportionality in",
    "the youth justice system of England and Wales. Oxon Advisory.",
    SITE_URL,
    "Contains public sector information licensed under the Open Government",
    "Licence v3.0. Source and reference period are given per row.",
    "A blank value with a disclosure_status of suppressed or",
    "source_suppressed is a cell withheld under disclosure control; it is",
    "not a zero and must not be treated as one.",
]


def _provenance(filename: str) -> tuple[str, str]:
    """Source description and reference period for a processed output.

    Read from build.py's PROVENANCE, the record the manifest is written
    from, rather than from manifest.json itself. The manifest is written
    after every step has run, so a step that reads it cannot work in a
    from-scratch build: it only ever succeeded because a previous build had
    left a manifest behind, or because the committed one was in the clone.
    """
    sources = PROVENANCE.get(filename) or []
    if not sources:
        return "", ""
    return sources[0]["description"], sources[0]["reference_period"]


def _load(name: str) -> dict:
    return json.loads((PROCESSED_DIR / name).read_text(encoding="utf-8"))


def _status(record: dict) -> str:
    """The disclosure status to publish.

    suppressed: True is authoritative: a record that carries it is withheld
    whatever its disclosure_status field says, so that an inconsistency
    between the two fields can never resolve in favour of publishing.
    """
    if record.get("suppressed") is True:
        status = record.get("disclosure_status")
        return status if status == "source_suppressed" else "suppressed"
    return record.get("disclosure_status") or "released"


def _value(record: dict, field: str = "value"):
    """The value to publish: blank where the cell is withheld."""
    if _status(record) in ("suppressed", "source_suppressed"):
        return ""
    value = record.get(field)
    return "" if value is None else value


def write_csv(name: str, title: str, note: str, columns: list[str],
              rows: list[dict]) -> tuple[str, int]:
    """Write one export. Returns the filename and its row count."""
    buffer = io.StringIO(newline="")
    for line in [title, *PREAMBLE_TAIL] if note is None else [
            title, note, *PREAMBLE_TAIL]:
        buffer.write(f"# {line}\r\n")
    writer = csv.DictWriter(buffer, fieldnames=columns, extrasaction="ignore",
                            lineterminator="\r\n")
    writer.writeheader()
    writer.writerows(rows)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / name).write_text(buffer.getvalue(), encoding="utf-8")
    return name, len(rows)


# --------------------------------------------------------------------------
# The national charts
# --------------------------------------------------------------------------
def export_cascade() -> tuple[str, int]:
    """The road-to-remand cascade: RRI by decision point and ethnicity."""
    records = _load("rri.json")["records"]
    rows = [{
        "decision_point": r["decision_point"],
        "ethnicity": r["ethnicity"],
        "rri": r["rri"],
        "ci_lower": r["ci_lower"],
        "ci_upper": r["ci_upper"],
        "ci_method": r["ci_method"],
        "significance_flag": r["significance_flag"],
        "events": r["events"],
        "total": r["total"],
        "pooled": r["pooled"],
        "year": r["year"],
        "geo_id": r["geo_id"],
        "source": r["source_publication"],
        "reference_period": r["period_basis"],
        "disclosure_status": _status(r),
    } for r in records]
    rows.sort(key=lambda r: (r["decision_point"], r["ethnicity"]))
    return write_csv(
        "road-to-remand-cascade.csv",
        "PRISM-R: the road to remand, Relative Rate Index by decision point",
        "An RRI of 1.00 is parity with White children. The reference group is "
        "White children at the same decision point.",
        ["decision_point", "ethnicity", "rri", "ci_lower", "ci_upper",
         "ci_method", "significance_flag", "events", "total", "pooled",
         "year", "geo_id", "source", "reference_period", "disclosure_status"],
        rows)


def export_remand_outcomes() -> tuple[str, int]:
    """Remand counts by ethnicity, age band, sex and remand type."""
    records = _load("remand_outcomes.json")["records"]
    source, period = _provenance("remand_outcomes.json")
    rows = [{
        "geo_id": r["geo_id"],
        "year": r["year"],
        "breakdown": r["breakdown"],
        "remand_type": r["remand_type"],
        "ethnicity": r["ethnicity"],
        "age_band": r["age_band"],
        "sex": r["sex"],
        "offence_band": r["offence_band"],
        "count": _value(r, "count"),
        "source": source,
        "reference_period": period,
        "disclosure_status": _status(r),
    } for r in records]
    rows.sort(key=lambda r: (r["breakdown"], str(r["remand_type"]),
                             str(r["ethnicity"]), str(r["age_band"]),
                             str(r["sex"]), str(r["offence_band"])))
    return write_csv(
        "remand-outcomes.csv",
        "PRISM-R: use of remand for children, England and Wales",
        "Remand is published at England and Wales level only; the Youth "
        "Justice Board does not publish it below national level.",
        ["geo_id", "year", "breakdown", "remand_type", "ethnicity",
         "age_band", "sex", "offence_band", "count", "source",
         "reference_period", "disclosure_status"],
        rows)


def export_target_tracker() -> tuple[str, int]:
    """The 25 per cent remand commitment tracker, by block."""
    records = _load("target_tracker.json")["records"]
    meta = _load("target_tracker.json")["meta"]
    rows = []
    for r in records:
        rows.append({
            "block": r.get("block"),
            "month": r.get("month"),
            "remand": _value(r, "remand"),
            "rolling_avg_12m": r.get("rolling_avg_12m")
                if _status(r) not in ("suppressed", "source_suppressed") else "",
            "provisional": r.get("provisional"),
            "age_basis": r.get("age_basis") or meta.get("age_basis"),
            "source": meta.get("source", "MoJ Youth Custody Service, monthly "
                                         "youth custody report"),
            "reference_period": meta.get("reference_period", ""),
            "disclosure_status": _status(r),
        })
    rows.sort(key=lambda r: (str(r["block"]), str(r["month"])))
    return write_csv(
        "remand-target-tracker.csv",
        "PRISM-R: tracking the 25 per cent reduction in child remand",
        "A stock measure: the monthly remand population, and its 12-month "
        "rolling average, against the baseline and the target. See "
        "docs/target-metric.md for the definitions.",
        ["block", "month", "remand", "rolling_avg_12m", "provisional",
         "age_basis", "source", "reference_period", "disclosure_status"],
        rows)


def export_remand_duration() -> tuple[str, int]:
    """Nights on remand by band and ethnic group."""
    records = _load("custody_episode_length.json")["records"]
    rows = [{
        "indicator": r["indicator"],
        "legal_basis": r["legal_basis"],
        "nights_band": r["nights_band"],
        "ethnicity_group": r["ethnicity_group"],
        "ethnicity_basis": r["ethnicity_basis"],
        "year_ending_march": r["year_ending_march"],
        "value": _value(r),
        "source": "MoJ Youth Custody Service, monthly youth custody report",
        "reference_period": f"year ending March {r['year_ending_march']}",
        "disclosure_status": _status(r),
    } for r in records]
    rows.sort(key=lambda r: (r["indicator"], str(r["legal_basis"]),
                             str(r["nights_band"]), str(r["ethnicity_group"])))
    return write_csv(
        "remand-duration.csv",
        "PRISM-R: time spent on remand, by nights band and ethnic group",
        "Episodes ending in the year, not the standing population.",
        ["indicator", "legal_basis", "nights_band", "ethnicity_group",
         "ethnicity_basis", "year_ending_march", "value", "source",
         "reference_period", "disclosure_status"],
        rows)


def export_context_indicators() -> tuple[str, int]:
    """Every sub-national context indicator: the choropleth and the Lambeth
    panels both read from this, so one export covers them."""
    records = _load("context_indicators.json")["records"]
    rows = [{
        "geo_id": r["geo_id"],
        "indicator": r["indicator"],
        "year": r["year"],
        "breakdown": r["breakdown"],
        "ethnicity": r["ethnicity"],
        "value": _value(r),
        "numerator": r.get("numerator") if _status(r) == "released" else "",
        "denominator": r.get("denominator"),
        "rate_per_100": r.get("rate_per_100")
            if _status(r) == "released" else "",
        "rate_per_1000": r.get("rate_per_1000")
            if _status(r) == "released" else "",
        "source_rate": r.get("source_rate") if _status(r) == "released" else "",
        "source_rate_base": r.get("source_rate_base"),
        "jurisdiction": r.get("jurisdiction"),
        "source": r["source"],
        "reference_period": r["reference_period"],
        "disclosure_status": _status(r),
    } for r in records]
    rows.sort(key=lambda r: (r["indicator"], r["geo_id"], r["year"],
                             str(r["ethnicity"])))
    return write_csv(
        "context-indicators.csv",
        "PRISM-R: sub-national context indicators, the road to remand",
        "Exclusions, children looked after, stop and search, arrests and "
        "child income deprivation. Each indicator is published at the "
        "geography its publisher releases it for; English IDACI and Welsh "
        "WIMD are parallel scales and are not comparable across the border.",
        ["geo_id", "indicator", "year", "breakdown", "ethnicity", "value",
         "numerator", "denominator", "rate_per_100", "rate_per_1000",
         "source_rate", "source_rate_base", "jurisdiction", "source",
         "reference_period", "disclosure_status"],
        rows)


def export_populations() -> tuple[str, int]:
    """The child population denominator behind every rate."""
    records = _load("populations.json")["records"]
    rows = [{
        "geo_id": r["geo_id"],
        "ethnicity": r["ethnicity"],
        "age": r.get("age"),
        "sex": r.get("sex"),
        "population": _value(r, "population"),
        "source": "ONS Census 2021, dataset RM032",
        "reference_period": "Census day, 21 March 2021",
        "disclosure_status": _status(r),
    } for r in records]
    rows.sort(key=lambda r: (r["geo_id"], str(r["ethnicity"]),
                             str(r["age"]), str(r["sex"])))
    return write_csv(
        "child-population.csv",
        "PRISM-R: child population aged 10 to 17 by ethnic group",
        "The denominator behind the rates published elsewhere in PRISM-R.",
        ["geo_id", "ethnicity", "age", "sex", "population", "source",
         "reference_period", "disclosure_status"],
        rows)


EXPORTS = (
    export_cascade,
    export_remand_outcomes,
    export_target_tracker,
    export_remand_duration,
    export_context_indicators,
    export_populations,
)


def main() -> int:
    results = [export() for export in EXPORTS]
    for name, count in results:
        size_kb = (OUTPUT_DIR / name).stat().st_size / 1024
        print(f"  csv/{name:32s} {count:>6,} rows  {size_kb:7.1f} KB")

    # A suppressed cell must never carry a figure into a download. This is
    # the same rule the pipeline enforces upstream, checked again at the
    # boundary where the data leaves the project.
    leaks = []
    for name, _ in results:
        with (OUTPUT_DIR / name).open(encoding="utf-8") as handle:
            rows = csv.DictReader(
                line for line in handle if not line.startswith("#"))
            for row in rows:
                if row.get("disclosure_status") not in (
                        "suppressed", "source_suppressed"):
                    continue
                for field, value in row.items():
                    if field in ("source", "reference_period",
                                 "disclosure_status", "denominator",
                                 "source_rate_base"):
                        continue
                    if value and _looks_numeric(value) and field in (
                            "value", "count", "population", "remand",
                            "numerator", "rate_per_100", "rate_per_1000",
                            "source_rate", "rolling_avg_12m"):
                        leaks.append(f"{name}: suppressed row carries "
                                     f"{field}={value}")
    if leaks:
        for leak in leaks[:10]:
            print(f"DISCLOSURE FAILURE: {leak}", file=sys.stderr)
        return 1
    print(f"\n{len(results)} exports written; no suppressed cell carries a "
          f"figure")
    return 0


def _looks_numeric(value: str) -> bool:
    try:
        float(value)
        return True
    except ValueError:
        return False


if __name__ == "__main__":
    sys.exit(main())
