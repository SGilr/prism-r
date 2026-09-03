"""Compute the White Paper remand target tracker.

Reads custody_monthly.json, custody_episode_length.json (both from the YCS
monthly report) and remand_outcomes.json (YJS), and writes
data/processed/target_tracker.json: the evidence base against which the
Youth Justice White Paper's commitment to a 25% reduction in custodial
remand for children is tracked. See docs/target-metric.md for the metric
definition and its caveats.

Blocks, carried as flat records with a block field:

  stock_monthly       the monthly remand stock (whole youth secure estate,
                      age_basis all_ages_youth_estate) and its trailing
                      12-month rolling average, April 2015 onwards. The
                      rolling series starts at March 2016, the first month
                      with a full window, so the pre-commitment trend is
                      visible.
  flow_annual         remands to youth detention accommodation (episodes,
                      YJS chapter 6), by year ending March.
  duration_median_nights  median remand nights by binary ethnicity, from
                      YCS table 3.4, episodes ending, years ending March
                      2019 to 2026 (2026 provisional).
  whole_custody_ethnicity_monthly  ethnic composition of the whole custody
                      population per month. This is the whole custody
                      population, not the remand population: the YCS does
                      not publish remand by ethnicity monthly.

The meta block carries the baseline (mean of the twelve monthly remand
values April 2024 to March 2025), the 75% target, the pre-commitment trend
(percentage change in the rolling average from March 2025 to May 2026, the
last finalised month), and the February 2026 and 18 May 2026 markers.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

PROCESSED_DIR = REPO_ROOT / "data" / "processed"

CUSTODY_MONTHLY = PROCESSED_DIR / "custody_monthly.json"
EPISODE_LENGTH = PROCESSED_DIR / "custody_episode_length.json"
REMAND_OUTCOMES = PROCESSED_DIR / "remand_outcomes.json"
OUTPUT = PROCESSED_DIR / "target_tracker.json"

TARGET_FRACTION = 0.75
BASELINE_MONTHS = [f"2024-{m:02d}" for m in range(4, 13)] + [
    "2025-01", "2025-02", "2025-03"]
ROLLING_WINDOW = 12
TREND_FROM = "2025-03"   # the rolling month the baseline is anchored to
TREND_TO = "2026-05"     # the last finalised month in the June 2026 edition

FLOW_BASELINE_YEAR = 2025  # year ending March 2025
FLOW_BASELINE = 988        # YJS 2024-25, remands to YDA; validated below

MARKERS = [
    {
        "date": "2026-02",
        "label": "figure cited to the Justice Committee, 18 May 2026",
        "estate_total": 412,
        "remand": 149,
        "remand_share": 0.362,
        "note": (
            'the "about 185" figure cited in Hansard applied the annual 44% '
            "remand share to the estate total rather than the published "
            "February 2026 remand figure"
        ),
    },
    {
        "date": "2026-05-18",
        "label": "Youth Justice White Paper published",
    },
]


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------
# Blocks
# --------------------------------------------------------------------------
def stock_block() -> tuple[list[dict], dict]:
    """Monthly remand stock with rolling average, plus the summary numbers."""
    monthly = _load(CUSTODY_MONTHLY)["records"]
    remand = {r["month"]: r for r in monthly
              if r["measure"] == "legal_basis" and r["category"] == "remand"}
    months = sorted(remand)

    rolling: dict[str, float | None] = {}
    for i, month in enumerate(months):
        window = months[i - ROLLING_WINDOW + 1: i + 1]
        if len(window) == ROLLING_WINDOW:
            rolling[month] = round(
                sum(remand[m]["count"] for m in window) / ROLLING_WINDOW, 2)
        else:
            rolling[month] = None

    records = [
        {
            "block": "stock_monthly",
            "month": month,
            "remand": remand[month]["count"],
            "rolling_avg_12m": rolling[month],
            "age_basis": remand[month]["age_basis"],
            "provisional": remand[month]["provisional"],
        }
        for month in months
    ]

    missing = [m for m in BASELINE_MONTHS if m not in remand]
    if missing:
        raise ValueError(f"baseline months missing from custody_monthly: {missing}")
    baseline = round(
        sum(remand[m]["count"] for m in BASELINE_MONTHS) / len(BASELINE_MONTHS), 2)
    if rolling[TREND_FROM] != baseline:
        raise ValueError(
            f"rolling average at {TREND_FROM} ({rolling[TREND_FROM]}) should "
            f"equal the baseline ({baseline})")
    trend = round(
        (rolling[TREND_TO] - rolling[TREND_FROM]) / rolling[TREND_FROM] * 100, 2)

    latest = months[-1]
    summary = {
        "baseline": baseline,
        "baseline_period": "the twelve months April 2024 to March 2025",
        "target": round(baseline * TARGET_FRACTION, 2),
        "target_fraction": TARGET_FRACTION,
        "rolling_window_months": ROLLING_WINDOW,
        "pre_commitment_trend": trend,
        "pre_commitment_trend_period": (
            f"rolling average, {TREND_FROM} to {TREND_TO}"),
        "latest_month": latest,
        "latest_rolling_avg": rolling[latest],
        "latest_provisional": remand[latest]["provisional"],
        "change_from_baseline_pct": round(
            (rolling[latest] - baseline) / baseline * 100, 2),
    }
    return records, summary


def flow_block() -> list[dict]:
    """Annual remands to youth detention accommodation, from YJS."""
    outcomes = _load(REMAND_OUTCOMES)["records"]
    by_year: dict[int, int] = {}
    for r in outcomes:
        if r.get("remand_type") == "ydp" and r.get("breakdown") == "total":
            by_year[r["year"]] = r["count"]
    if by_year.get(FLOW_BASELINE_YEAR) != FLOW_BASELINE:
        raise ValueError(
            f"YDA episodes YE March {FLOW_BASELINE_YEAR} "
            f"({by_year.get(FLOW_BASELINE_YEAR)}) != expected {FLOW_BASELINE}")
    return [
        {
            "block": "flow_annual",
            "year_ending_march": year,
            "yda_remand_episodes": count,
            "source": "YJS Youth Justice Statistics, chapter 6",
        }
        for year, count in sorted(by_year.items())
    ]


def duration_block() -> list[dict]:
    """Median remand nights by binary ethnicity, years ending March."""
    length = _load(EPISODE_LENGTH)["records"]
    latest_year = max(r["year_ending_march"] for r in length)
    return [
        {
            "block": "duration_median_nights",
            "year_ending_march": r["year_ending_march"],
            "ethnicity_group": r["ethnicity_group"],
            "median_nights": r["value"],
            "ethnicity_basis": "binary",
            "measure": "episodes_ending",
            "provisional": r["year_ending_march"] == latest_year,
        }
        for r in sorted(length, key=lambda x: (x["year_ending_march"],
                                               x["ethnicity_group"]))
        if r["indicator"] == "median_nights" and r["legal_basis"] == "remand"
    ]


def ethnicity_block() -> list[dict]:
    """Whole-custody ethnic composition per month, as shares of the total.

    This step runs after the build's disclosure-control stage, so
    custody_monthly.json arrives already suppressed and the flags on it are
    read rather than recomputed. A cell the stage withheld loses its share as
    well as its count here: a share against a published total would let the
    count be recovered, which is disclosure rule 2b.
    """
    monthly = _load(CUSTODY_MONTHLY)["records"]
    by_month: dict[str, list[dict]] = {}
    totals: dict[str, int] = {}
    for r in monthly:
        if r["measure"] == "ethnicity":
            by_month.setdefault(r["month"], []).append(r)
        elif r["measure"] == "total" and r["category"] == "all_ages":
            totals[r["month"]] = r["count"]

    records = []
    for month, rows in sorted(by_month.items()):
        # The published all-ages estate total is the share denominator. It is
        # a large figure that suppression never touches, so it is safe as a
        # denominator and stable across builds.
        total = totals.get(month)
        for r in sorted(rows, key=lambda x: x["category"]):
            hidden = (r.get("suppressed") is True
                      or r.get("disclosure_status") in
                      ("suppressed", "source_suppressed")
                      or r["count"] is None)
            share = (round(r["count"] / total, 4)
                     if not hidden and total else None)
            records.append({
                "block": "whole_custody_ethnicity_monthly",
                "month": month,
                "category": r["category"],
                "count": None if hidden else r["count"],
                "share": share,
                "suppressed": hidden,
                "scope": "whole_custody",
                "provisional": r["provisional"],
            })
    return records


# --------------------------------------------------------------------------
# Output
# --------------------------------------------------------------------------
def main() -> int:
    stock, summary = stock_block()
    records = stock + flow_block() + duration_block() + ethnicity_block()

    payload = {
        "meta": {
            "dataset": "target_tracker",
            "generated_by": "pipeline/compute_target.py",
            "definition": "docs/target-metric.md",
            "stock": summary,
            "flow": {
                "baseline": FLOW_BASELINE,
                "baseline_year_ending_march": FLOW_BASELINE_YEAR,
                "target": round(FLOW_BASELINE * TARGET_FRACTION),
                "target_fraction": TARGET_FRACTION,
            },
            "markers": MARKERS,
            "schema_note": (
                "Flat records with a block field: stock_monthly (whole youth "
                "secure estate remand stock and trailing 12-month rolling "
                "average), flow_annual (YJS remands to YDA), "
                "duration_median_nights (YCS table 3.4, binary ethnicity, "
                "episodes ending) and whole_custody_ethnicity_monthly (the "
                "whole custody population, not the remand population; the "
                "YCS does not publish remand by ethnicity monthly; cells "
                "below the disclosure threshold lose both count and share, "
                "so shares in affected months sum to less than one). The "
                "latest month and the latest episodes-ending year are "
                "provisional. See docs/target-metric.md for definitions."
            ),
            "counts": {"records": len(records)},
        },
        "records": records,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")

    print(f"target_tracker.json  {len(records)} records")
    print(f"  stock baseline {summary['baseline']}  target {summary['target']}")
    print(f"  latest rolling ({summary['latest_month']}, provisional "
          f"{summary['latest_provisional']}): {summary['latest_rolling_avg']}  "
          f"({summary['change_from_baseline_pct']:+.1f}% vs baseline)")
    print(f"  pre-commitment trend {TREND_FROM} to {TREND_TO}: "
          f"{summary['pre_commitment_trend']:+.1f}%")
    print(f"  flow baseline {FLOW_BASELINE}, target "
          f"{payload['meta']['flow']['target']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
