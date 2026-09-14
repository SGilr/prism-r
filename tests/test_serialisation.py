"""Tests for serialisation precision in pipeline/serialise.py.

The verification run of 14 September 2026 failed because interval bounds
computed through exp, lgamma, log and log1p differed between a macOS and a
Linux build in the last few significant digits. The bisection that produces
them is deterministic for a given maths library; cross-platform
reproducibility comes from rounding at serialisation. These tests hold both
halves: that drift-prone values are rounded when written, and that no module
can start computing them without doing so.
"""

import csv
import json
import math
import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from pipeline.serialise import (  # noqa: E402
    DRIFT_PRONE_FUNCTIONS,
    SERIALISED_DECIMALS,
    stable_float,
)

PIPELINE = REPO_ROOT / "pipeline"
PROCESSED = REPO_ROOT / "data" / "processed"

# The largest cross-platform discrepancy the verification run reported.
OBSERVED_DRIFT = 1.2e-12


def _decimals(value: float) -> int:
    text = repr(value)
    if "e" in text or "E" in text:
        return 99
    return len(text.split(".")[1]) if "." in text else 0


# --------------------------------------------------------------------------
# The helper
# --------------------------------------------------------------------------
def test_stable_float_rounds_to_the_declared_precision():
    assert stable_float(0.49813163623934303) == 0.498132
    assert _decimals(stable_float(2.2415324967305845)) <= SERIALISED_DECIMALS


def test_stable_float_passes_none_through():
    assert stable_float(None) is None


def test_stable_float_is_idempotent():
    for value in (0.498132, 1.5, 2.0, 0.123456):
        assert stable_float(value) == value
        assert stable_float(stable_float(value)) == stable_float(value)


def test_drift_of_the_observed_size_is_absorbed():
    """The point of the rounding: two platforms a few units apart in the
    last place serialise to the same value."""
    for value in (0.8735045022244049, 1.5305685179282382, 0.5825055144106729):
        assert stable_float(value + OBSERVED_DRIFT) == stable_float(value)
        assert stable_float(value - OBSERVED_DRIFT) == stable_float(value)


def test_sqrt_is_not_treated_as_drift_prone():
    """IEEE 754 requires sqrt to be correctly rounded, like division, so it
    reproduces bit for bit and must not force rounding on its callers."""
    assert "sqrt" not in DRIFT_PRONE_FUNCTIONS


# --------------------------------------------------------------------------
# The structural guard: new drift-prone maths must be rounded when written
# --------------------------------------------------------------------------
_DRIFT_CALL = re.compile(
    r"\b(?:math|np|numpy)\.(" + "|".join(DRIFT_PRONE_FUNCTIONS) + r")\s*\(")
_WRITES = re.compile(r"json\.dump|write_text\(|\.open\([^)]*[\"']w|csv\.writer|DictWriter")


def _code_lines(source: str) -> list[str]:
    """Source lines with comments stripped; docstrings mentioning the
    functions by name are harmless because they carry no call parentheses
    after a module prefix."""
    return [line.split("#", 1)[0] for line in source.splitlines()]


def test_the_maths_library_is_used_only_in_a_module_that_writes_nothing():
    """exact_ci.py may call drift-prone functions because it is a pure
    library: it returns numbers and writes no file. A module that both
    computes with those functions and writes output would bypass the
    rounding, so it fails here."""
    offenders = []
    for path in sorted(PIPELINE.glob("*.py")):
        code = "\n".join(_code_lines(path.read_text("utf-8")))
        if not _DRIFT_CALL.search(code):
            continue
        if path.name == "exact_ci.py":
            assert not _WRITES.search(code), (
                "exact_ci.py must stay a pure library that writes nothing")
            continue
        offenders.append(path.name)
    assert not offenders, (
        f"{offenders} call functions IEEE 754 does not require to be "
        "correctly rounded. Compute them in a pure library and round what is "
        "written with pipeline.serialise.stable_float, or the build will not "
        "reproduce across platforms.")


def test_every_consumer_of_the_exact_intervals_rounds_what_it_writes():
    """A module importing exact_ci receives drift-prone values and must
    import the serialisation helper. A future consumer inherits the check."""
    offenders = []
    for path in sorted(PIPELINE.glob("*.py")):
        if path.name in ("exact_ci.py", "serialise.py"):
            continue
        source = path.read_text("utf-8")
        if re.search(r"\bpipeline\.exact_ci\b|\bfrom exact_ci\b", source):
            if "stable_float" not in source:
                offenders.append(path.name)
    assert not offenders, (
        f"{offenders} import exact_ci without pipeline.serialise.stable_float")


# --------------------------------------------------------------------------
# The published outputs
# --------------------------------------------------------------------------
@pytest.fixture(scope="module")
def derived_bounds():
    records = json.loads((PROCESSED / "rri.json").read_text("utf-8"))["records"]
    return [(r, field) for r in records for field in ("ci_lower", "ci_upper")
            if r.get(field) is not None]


def test_published_bounds_stop_at_the_serialised_precision(derived_bounds):
    assert derived_bounds, "rri.json should carry interval bounds"
    too_long = [(r["decision_point"], r["ethnicity"], field, r[field])
                for r, field in derived_bounds
                if _decimals(r[field]) > SERIALISED_DECIMALS]
    assert not too_long, too_long


def test_point_estimates_are_not_rounded(derived_bounds):
    """Point estimates use only division, reproduce exactly, and are
    published at full precision. Rounding them would change a published
    figure for no reproducibility gain."""
    records = json.loads((PROCESSED / "rri.json").read_text("utf-8"))["records"]
    derived = [r for r in records if r["provenance"] == "prism_r_derived"
               and r["ethnicity"] != "White"]
    assert any(_decimals(r["rri"]) > SERIALISED_DECIMALS for r in derived)


def test_unrounded_bounds_keep_a_margin_from_rounding_half_way_points():
    """Rounding absorbs drift unless a value sits within the drift of a
    half-way point, where two platforms could round opposite ways.

    The check has to run on the unrounded bounds. A committed bound already
    sits exactly on the six-decimal grid, so its distance from a half-way
    point is always half a unit and would tell us nothing. The unrounded
    values are recomputed from the counts rri.json stores, and must keep a
    hundredfold margin over the observed drift. If this ever fails, the
    verification job is at risk for that value, and the message says why.
    """
    from pipeline.compute_rri import relative_rate_index

    records = json.loads((PROCESSED / "rri.json").read_text("utf-8"))["records"]
    key = lambda r: (r["decision_point"], r["geo_id"], r["provenance"],
                     r["period_basis"], r["pooled"], r["year"])
    baselines = {key(r): r for r in records if r["ethnicity"] == "White"}
    unit = 10 ** -SERIALISED_DECIMALS
    close, checked = [], 0
    for r in records:
        if (r["provenance"] != "prism_r_derived" or r["ethnicity"] == "White"
                or r.get("ci_lower") is None):
            continue
        base = baselines[key(r)]
        result = relative_rate_index(r["events"], r["total"],
                                     base["events"], base["total"])
        for field in ("ci_lower", "ci_upper"):
            raw = getattr(result, field)
            assert stable_float(raw) == r[field], (
                "the committed bound should be the rounded recomputation", r)
            scaled = raw / unit
            gap = abs((scaled - math.floor(scaled)) - 0.5) * unit
            checked += 1
            if gap < OBSERVED_DRIFT * 100:
                close.append((r["decision_point"], r["ethnicity"], field, raw, gap))
    assert checked, "expected interval bounds to check"
    assert not close, (
        f"these bounds sit near a rounding half-way point and may round "
        f"differently across platforms: {close}")


def test_the_cascade_csv_inherits_the_rounding():
    lines = [line for line in (PROCESSED / "csv" / "road-to-remand-cascade.csv")
             .read_text("utf-8").splitlines() if not line.startswith("#")]
    for row in csv.DictReader(lines):
        for field in ("ci_lower", "ci_upper"):
            if row[field]:
                assert _decimals(float(row[field])) <= SERIALISED_DECIMALS, row
