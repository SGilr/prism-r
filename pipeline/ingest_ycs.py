"""Ingest the Youth Custody Service monthly youth custody report.

Source: MoJ/YCS, Youth custody data, monthly ODS. The ingested edition is
recorded in SOURCE_FILE below; the latest month in the file is provisional
(the YCS finalises it in the following month's edition), so the newest month
is marked provisional and is overwritten on the next ingest.

Outputs:

  custody_monthly.json         Section 1 stock series, one record per month,
                               measure and category. Measures: total (under_18
                               and all_ages, from Apr 2000), legal_basis
                               (remand, DTO, s91/250, other; from Apr 2015),
                               age (from Apr 2015) and ethnicity (whole
                               custody population, from Apr 2015). The
                               monthly tables are one-dimensional: legal
                               basis does not cross with age, ethnicity or
                               region, so the remand series is the whole
                               youth secure estate, age_basis
                               all_ages_youth_estate. See
                               docs/target-metric.md.
  custody_episodes_ending.json Table 2.2: legal-basis episodes ending by
                               binary ethnicity (ethnic minority groups vs
                               White) and legal basis, years ending March
                               2019 to 2026. ethnicity_basis binary; not
                               mapped onto the YJB five groups.
  custody_episode_length.json  Table 3.4: episode length in nights by binary
                               ethnicity, legal basis and nights band, with
                               medians, years ending March 2019 to 2026.

The YCS suppresses cells of 4 or fewer as [x]; such cells are carried as
null with disclosure_status source_suppressed. PRISM-R's own disclosure
rules are applied afterwards by the build orchestrator.

Validation: every month's legal-basis sum must equal the all-ages total;
the March 2025 under-18 total is cross-checked against YJS 2024-25 Table
7.2 (they share a source series); and the February 2026 all-ages total is
anchored to 412, the figure cited to the Justice Committee on 18 May 2026.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import openpyxl
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
PROCESSED_DIR = REPO_ROOT / "data" / "processed"
RAW_YCS = REPO_ROOT / "data" / "raw" / "ycs"

FETCH_MANIFEST = REPO_ROOT / "data" / "raw" / "fetch_manifest.json"


def _resolve_source() -> tuple[str, str, str]:
    """The current YCS edition: (filename, edition label, publication date).

    Read from the fetch manifest when the fetch layer has run; otherwise the
    newest youth-custody ODS in data/raw/ycs by filename-parsed month. The
    edition label is derived from the filename (for example
    youth-custody-population-june-2026.ods -> June 2026).
    """
    filename = None
    publication_date = ""
    if FETCH_MANIFEST.exists():
        entry = json.loads(FETCH_MANIFEST.read_text(encoding="utf-8"))[
            "sources"].get("ycs", {})
        filename = entry.get("filename")
        publication_date = entry.get("source_publication_date") or ""
    if filename is None:
        candidates = sorted(RAW_YCS.glob("youth-custody*.ods"),
                            key=lambda p: p.stat().st_mtime)
        if not candidates:
            raise FileNotFoundError(f"no youth custody ODS in {RAW_YCS}")
        filename = candidates[-1].name
    stem = filename.rsplit(".", 1)[0]
    month, year = stem.split("-")[-2:]
    edition = f"{month.capitalize()} {year}"
    return filename, edition, publication_date[:10]


SOURCE_FILE, SOURCE_EDITION_RESOLVED, SOURCE_PUBLICATION_RESOLVED = _resolve_source()
SOURCE_ODS = RAW_YCS / SOURCE_FILE
YJS_CH7 = REPO_ROOT / "data" / "raw" / "yjb-2024-25" / "Ch 7 - Children in youth custody.xlsx"

MONTHLY_OUT = PROCESSED_DIR / "custody_monthly.json"
EPISODES_OUT = PROCESSED_DIR / "custody_episodes_ending.json"
LENGTH_OUT = PROCESSED_DIR / "custody_episode_length.json"

SOURCE = "MoJ Youth Custody Service, monthly youth custody report"
SOURCE_EDITION = SOURCE_EDITION_RESOLVED
SOURCE_PUBLICATION_DATE = SOURCE_PUBLICATION_RESOLVED or "2026-08-14"
AGE_BASIS = "all_ages_youth_estate"

# Source-anchored validation constants, verified against the published data.
ANCHOR_UNDER18_MAR_2025 = 402   # YCS 1.1 under-18, equals YJS 2024-25 Table 7.2
ANCHOR_ALL_AGES_FEB_2026 = 412  # cited to the Justice Committee, 18 May 2026

LEGAL_BASIS_COLUMNS = {
    "Remand": "remand",
    "DTO": "dto",
    "Section 91 / 250": "section_91_250",
    "Other [note 4]": "other_sentence",
}
AGE_COLUMNS = {
    "Age 10 to 14 years": "10_to_14",
    "Aged 15": "15",
    "Aged 16": "16",
    "Aged 17": "17",
    "Aged 18 years and Older": "18_and_over",
}
ETHNICITY_COLUMNS = {
    "Asian": "asian",
    "Black": "black",
    "Mixed Ethnicity": "mixed",
    "Other Ethnicity": "other",
    "White (including white minorities)": "white",
    "Not Known": "not_known",
}
NIGHTS_BANDS = {
    "1 to 91 nights": "1_to_91",
    "92 to 182 nights": "92_to_182",
    "183 to 273 nights": "183_to_273",
    "274+ nights": "274_plus",
}
ETHNICITY_GROUPS = {
    "Ethnic minority groups": "ethnic_minority",
    "White (including white minorities)": "white",
}
EPISODE_LEGAL_BASIS = {"Remand": "remand", "DTO": "dto", "Other": "other"}


# --------------------------------------------------------------------------
# Reading helpers
# --------------------------------------------------------------------------
def _cell(value):
    """A source cell: (count or None, source_suppressed). [x] means 4 or fewer."""
    text = str(value).strip()
    if text == "[x]":
        return None, True
    return int(round(float(value))), False


def _monthly_frame(workbook: pd.ExcelFile, sheet: str) -> pd.DataFrame:
    """Read a Section 1 sheet: header on row 2, empty future rows dropped."""
    frame = pd.read_excel(workbook, sheet_name=sheet, header=1)
    frame = frame[pd.notna(frame.iloc[:, 1])].copy()
    frame["Month"] = pd.to_datetime(frame["Month"]).dt.strftime("%Y-%m")
    return frame


# --------------------------------------------------------------------------
# custody_monthly.json
# --------------------------------------------------------------------------
def read_monthly(workbook: pd.ExcelFile) -> tuple[list[dict], str]:
    """Read tables 1.1, 1.2, 1.4 and 1.6 into flat monthly records."""
    totals = _monthly_frame(workbook, "1_1")
    ethnicity = _monthly_frame(workbook, "1_2")
    age = _monthly_frame(workbook, "1_4")
    legal = _monthly_frame(workbook, "1_6")

    latest = max(legal["Month"])

    def record(month, measure, category, count, suppressed=False, scope=None,
               age_basis=AGE_BASIS):
        return {
            "month": month,
            "measure": measure,
            "category": category,
            "count": count,
            "scope": scope,
            "age_basis": age_basis,
            "disclosure_status": "source_suppressed" if suppressed else "released",
            "provisional": month == latest,
            "source_file": SOURCE_FILE,
        }

    records: list[dict] = []
    for row in totals.itertuples(index=False):
        under18, _ = _cell(row[1])
        all_ages, _ = _cell(row[2])
        records.append(record(row.Month, "total", "under_18", under18,
                              age_basis="under_18"))
        records.append(record(row.Month, "total", "all_ages", all_ages))

    for frame, measure, columns, scope in (
        (legal, "legal_basis", LEGAL_BASIS_COLUMNS, None),
        (age, "age", AGE_COLUMNS, None),
        (ethnicity, "ethnicity", ETHNICITY_COLUMNS, "whole_custody"),
    ):
        for _, row in frame.iterrows():
            for source_column, category in columns.items():
                count, suppressed = _cell(row[source_column])
                records.append(record(row["Month"], measure, category, count,
                                      suppressed, scope=scope))

    records.sort(key=lambda r: (r["month"], r["measure"], r["category"]))
    return records, latest


def validate_monthly(records: list[dict]) -> list[str]:
    """Internal consistency and source-anchored checks. Returns findings."""
    findings: list[str] = []
    by_month: dict[str, dict] = {}
    for r in records:
        by_month.setdefault(r["month"], {}).setdefault(r["measure"], {})[
            r["category"]] = r["count"]

    for month, measures in sorted(by_month.items()):
        if "legal_basis" not in measures:
            continue
        basis_sum = sum(v for v in measures["legal_basis"].values() if v is not None)
        all_ages = measures["total"]["all_ages"]
        if basis_sum != all_ages:
            findings.append(
                f"{month}: legal-basis sum {basis_sum} != all-ages total {all_ages}")

    mar25 = by_month.get("2025-03", {}).get("total", {}).get("under_18")
    if mar25 != ANCHOR_UNDER18_MAR_2025:
        findings.append(
            f"March 2025 under-18 total {mar25} != anchor {ANCHOR_UNDER18_MAR_2025}")
    feb26 = by_month.get("2026-02", {}).get("total", {}).get("all_ages")
    if feb26 != ANCHOR_ALL_AGES_FEB_2026:
        findings.append(
            f"February 2026 all-ages total {feb26} != anchor {ANCHOR_ALL_AGES_FEB_2026}")

    # Cross-source: YJS 2024-25 Table 7.2 March 2025 under-18 population.
    if YJS_CH7.exists():
        workbook = openpyxl.load_workbook(YJS_CH7, read_only=True, data_only=True)
        try:
            rows = list(workbook["7.2"].iter_rows(values_only=True))
        finally:
            workbook.close()
        header = next(r for r in rows if r and str(r[0]) == "Financial Year")
        mar_index = [str(v) for v in header].index("Mar")
        yjs_row = next(r for r in rows if r and str(r[0]) == "2024/25")
        yjs_mar25 = int(yjs_row[mar_index])
        if yjs_mar25 != mar25:
            findings.append(
                f"YJS 7.2 March 2025 {yjs_mar25} != YCS under-18 {mar25}")
    else:
        findings.append("YJS Ch 7 raw file missing; cross-source check skipped")
    return findings


# --------------------------------------------------------------------------
# custody_episodes_ending.json (table 2.2)
# --------------------------------------------------------------------------
def _year_columns(header_row) -> dict[int, int]:
    """Map column index -> year ending March, from a 2.x/3.x header row."""
    years = {}
    for i, value in enumerate(header_row):
        text = str(value)
        if text.startswith("Year ending March"):
            years[i] = int(text.rsplit(" ", 1)[1])
    return years


def read_episodes_ending(workbook: pd.ExcelFile) -> list[dict]:
    frame = pd.read_excel(workbook, sheet_name="2_2", header=None)
    years = _year_columns(frame.iloc[1])
    records = []
    for i in range(2, len(frame)):
        label = str(frame.iloc[i, 0])
        if label.startswith("Total") or label == "nan":
            continue
        group_label, _, basis_label = label.partition(" - ")
        group = next(v for k, v in ETHNICITY_GROUPS.items() if k in group_label)
        basis = EPISODE_LEGAL_BASIS[basis_label.strip()]
        for column, year in years.items():
            count, suppressed = _cell(frame.iloc[i, column])
            records.append({
                "year_ending_march": year,
                "ethnicity_group": group,
                "legal_basis": basis,
                "count": count,
                "ethnicity_basis": "binary",
                "disclosure_status": "source_suppressed" if suppressed else "released",
                "source_file": SOURCE_FILE,
            })
    records.sort(key=lambda r: (r["year_ending_march"], r["ethnicity_group"],
                                r["legal_basis"]))
    return records


# --------------------------------------------------------------------------
# custody_episode_length.json (table 3.4)
# --------------------------------------------------------------------------
def read_episode_length(workbook: pd.ExcelFile) -> list[dict]:
    frame = pd.read_excel(workbook, sheet_name="3_4", header=None)
    years = _year_columns(frame.iloc[1])
    records = []
    for i in range(2, len(frame)):
        label = str(frame.iloc[i, 0])
        if label == "nan" or label.startswith("Total"):
            continue
        group = next((v for k, v in ETHNICITY_GROUPS.items() if label.startswith(k)),
                     None)
        if group is None:
            continue
        basis = next((v for k, v in EPISODE_LEGAL_BASIS.items()
                      if f" and {k}" in label.split(" - ")[0] + " "), None)
        if basis is None:
            continue
        suffix = label.rsplit(" - ", 1)[1] if " - " in label else ""
        if suffix in NIGHTS_BANDS:
            indicator, band = "episode_count", NIGHTS_BANDS[suffix]
        elif suffix == "Median number of nights":
            indicator, band = "median_nights", None
        else:
            continue
        for column, year in years.items():
            raw = frame.iloc[i, column]
            if indicator == "median_nights":
                suppressed = str(raw).strip() == "[x]"
                value = None if suppressed else float(raw)
            else:
                value, suppressed = _cell(raw)
            records.append({
                "year_ending_march": year,
                "ethnicity_group": group,
                "legal_basis": basis,
                "indicator": indicator,
                "nights_band": band,
                "value": value,
                "ethnicity_basis": "binary",
                "disclosure_status": "source_suppressed" if suppressed else "released",
                "source_file": SOURCE_FILE,
            })
    records.sort(key=lambda r: (r["year_ending_march"], r["ethnicity_group"],
                                r["legal_basis"], r["indicator"],
                                r["nights_band"] or ""))
    return records


# --------------------------------------------------------------------------
# Output
# --------------------------------------------------------------------------
def _write(path: Path, meta: dict, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump({"meta": meta, "records": records}, handle,
                  ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")


def _base_meta(dataset: str, schema_note: str) -> dict:
    return {
        "dataset": dataset,
        "generated_by": "pipeline/ingest_ycs.py",
        "source": SOURCE,
        "source_edition": SOURCE_EDITION,
        "source_publication_date": SOURCE_PUBLICATION_DATE,
        "schema_note": schema_note,
    }


def main() -> int:
    workbook = pd.ExcelFile(SOURCE_ODS, engine="odf")

    monthly, latest = read_monthly(workbook)
    findings = validate_monthly(monthly)
    if findings:
        for finding in findings:
            print(f"VALIDATION FAILED: {finding}", file=sys.stderr)
        return 1

    episodes = read_episodes_ending(workbook)
    length = read_episode_length(workbook)

    _write(MONTHLY_OUT, {
        **_base_meta("custody_monthly", (
            "One record per month, measure and category. Measures: total "
            "(under_18 and all_ages), legal_basis, age, ethnicity. The YCS "
            "monthly tables are one-dimensional, so legal basis does not "
            "cross with age, ethnicity or region: the remand series is the "
            "whole youth secure estate (age_basis all_ages_youth_estate) and "
            "the ethnicity series is the whole custody population (scope "
            "whole_custody), not the remand population. The latest month is "
            "provisional and is overwritten at the next ingest. See "
            "docs/target-metric.md."
        )),
        "latest_month": latest,
        "counts": {"records": len(monthly)},
    }, monthly)

    _write(EPISODES_OUT, {
        **_base_meta("custody_episodes_ending", (
            "Table 2.2: legal-basis episodes ending by ethnicity and legal "
            "basis, years ending March. ethnicity_basis is binary, ethnic "
            "minority groups against White including white minorities, as "
            "published; not mapped onto the YJB five groups. Episodes with "
            "unknown ethnicity or certain end types are excluded at source, "
            "so cells do not sum to Section 1 totals."
        )),
        "counts": {"records": len(episodes)},
    }, episodes)

    _write(LENGTH_OUT, {
        **_base_meta("custody_episode_length", (
            "Table 3.4: legal-basis episodes ending by ethnicity, legal "
            "basis and nights band, with median nights, years ending March. "
            "ethnicity_basis is binary. indicator is episode_count or "
            "median_nights; nights_band is null for medians. Source cells "
            "of 4 or fewer are suppressed by the YCS as [x] and carried as "
            "null, disclosure_status source_suppressed."
        )),
        "counts": {"records": len(length)},
    }, length)

    months = sorted({r["month"] for r in monthly})
    remand_latest = next(r["count"] for r in monthly
                         if r["month"] == latest and r["measure"] == "legal_basis"
                         and r["category"] == "remand")
    print(f"custody_monthly.json          {len(monthly)} records, "
          f"{months[0]} to {months[-1]} (latest provisional)")
    print(f"  remand stock {latest}: {remand_latest}")
    print(f"custody_episodes_ending.json  {len(episodes)} records")
    print(f"custody_episode_length.json   {len(length)} records")
    print("validation: monthly legal-basis sums, March 2025 and February 2026 "
          "anchors, and the YJS 7.2 cross-check all passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
