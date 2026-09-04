"""Tests for the raw-data bundle in pipeline/make_raw_bundle.py.

The bundle's RAW_BUNDLE.md is the provenance record a reader uses to verify
that the files the pipeline reads are the files the publishers issued. A file
with no SOURCES entry is attributed by whichever directory prefix happens to
match, so these tests hold the attribution honest.
"""

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from pipeline import make_raw_bundle as bundle  # noqa: E402

RAW_DIR = REPO_ROOT / "data" / "raw"
UNATTRIBUTED = "unattributed; add a SOURCES entry"


def _raw_files() -> list[str]:
    return sorted(
        str(p.relative_to(RAW_DIR))
        for p in RAW_DIR.rglob("*")
        if p.is_file() and p.name not in ("RAW_BUNDLE.md", ".gitkeep")
        and ".DS_Store" not in p.name
    )


def test_every_raw_file_has_a_source_entry():
    """No file may reach the bundle unattributed.

    Skipped on a checkout with no raw data; CI unpacks the bundle first, so
    this runs there.
    """
    files = _raw_files()
    if len(files) < 10:
        pytest.skip("data/raw not populated; unpack the raw-data bundle first")
    unattributed = [
        name for name in files
        if bundle._source_for(name)[0] == UNATTRIBUTED
        or not bundle._source_for(name)[1]
    ]
    assert unattributed == [], (
        "these raw files would be published with no source: "
        f"{unattributed}"
    )


def test_the_explorer_boundaries_are_attributed_to_the_geography_portal():
    """Regression test.

    The bundle published on 3 September 2026 was cut hours before these four
    files were retrieved, so it did not contain them and the pipeline could
    not be reproduced from it. When they were added, the geo/ prefix in
    SOURCES was a directory-wide entry describing a different ONS file, an
    FOI lookup table, so the four boundary files would have been published
    with that file's source URL and retrieval date.
    """
    for layer in ("LAD", "CTYUA", "PFA", "RGN"):
        name = f"geo/boundaries-2023/{layer}_2023_BUC.geojson"
        description, url, retrieved, licence = bundle._source_for(name)
        assert "boundaries" in description.lower()
        assert url == "https://geoportal.statistics.gov.uk/"
        assert retrieved == "2026-09-03"
        assert "ons.gov.uk/methodology/geography/licences" in licence


def test_no_source_prefix_is_a_bare_directory_that_mixes_publishers():
    """geo/ holds files from three different ONS retrievals.

    A prefix of "geo/" would absorb any file added there later and attribute
    it to whichever entry it was written for. Each geo file is named
    specifically instead.
    """
    prefixes = [prefix for prefix, _ in bundle.SOURCES]
    assert "geo/" not in prefixes
