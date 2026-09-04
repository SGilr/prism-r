"""Build the raw-data release bundle.

Packages data/raw/ as a single tar.gz for a GitHub release tagged
raw-data-YYYY-MM, with RAW_BUNDLE.md inside listing every file, its source
URL, retrieval date, SHA-256 and licence. The refresh workflow downloads the
latest raw-data-* release, unpacks it to data/raw/, then runs
build.py --fetch so the automated sources overwrite with anything newer.

Procedure when a manual source is refreshed locally: re-run the build, run
this script, publish the release it prints, and note it in
docs/data-sources.md. See README, "Reproducing the pipeline".

Usage: python pipeline/make_raw_bundle.py [output-dir]
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import subprocess
import sys
import tarfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = REPO_ROOT / "data" / "raw"
BUNDLE_DOC = RAW_DIR / "RAW_BUNDLE.md"

OGL = "OGL v3.0, https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/"
OGL_WALES = ("OGL v3.0, https://www.gov.wales/copyright-statement (Welsh "
             "Government), https://www.nationalarchives.gov.uk/doc/"
             "open-government-licence/version/3/")
OGL_ONS = ("OGL v3.0, https://www.ons.gov.uk/methodology/geography/licences "
           "(ONS), https://www.nationalarchives.gov.uk/doc/"
           "open-government-licence/version/3/")

# Directory prefix -> (source description, source URL, retrieval date, licence).
# Longest prefix wins. Retrieval dates mirror docs/data-sources.md.
SOURCES: list[tuple[str, tuple[str, str, str, str]]] = [
    ("dfe/exclusions_2023-24", (
        "DfE suspensions and permanent exclusions in England, 2023/24 all-data",
        "https://explore-education-statistics.service.gov.uk/find-statistics/"
        "suspensions-and-permanent-exclusions-in-england", "2026-05-17", OGL)),
    ("dfe/exclusions_2024-25", (
        "DfE suspensions and permanent exclusions in England, 2024/25 all-data",
        "https://explore-education-statistics.service.gov.uk/find-statistics/"
        "suspensions-and-permanent-exclusions-in-england", "2026-09-03", OGL)),
    ("dfe/cla_2025", (
        "DfE children looked after in England including adoptions, 2025",
        "https://explore-education-statistics.service.gov.uk/find-statistics/"
        "children-looked-after-in-england-including-adoptions", "2026-05-17", OGL)),
    ("moj/", (
        "MoJ statistics on ethnicity and the criminal justice system 2024, "
        "and criminal justice statistics tools",
        "https://www.gov.uk/government/statistics/"
        "ethnicity-and-the-criminal-justice-system-2024", "2026-05-17", OGL)),
    ("home-office/", (
        "Home Office police powers and procedures, year ending March 2025",
        "https://www.gov.uk/government/statistics/"
        "stop-and-search-arrests-and-mental-health-detentions-march-2025",
        "2026-05-17", OGL)),
    ("imd/wimd2019", (
        "Welsh Index of Multiple Deprivation 2019, income deprivation by age",
        "https://www.gov.wales/welsh-index-multiple-deprivation-2025",
        "2026-05-17", OGL_WALES)),
    ("imd/", (
        "MHCLG English indices of deprivation 2025",
        "https://www.gov.uk/government/statistics/"
        "english-indices-of-deprivation-2025", "2026-05-17", OGL)),
    ("ons-census-2021/", (
        "ONS Census 2021, dataset RM032, via the ONS filter service",
        "https://www.ons.gov.uk/datasets/RM032", "2026-05-17", OGL_ONS)),
    ("yjb-2024-25/", (
        "YJB and MoJ youth justice statistics 2024 to 2025",
        "https://www.gov.uk/government/statistics/"
        "youth-justice-statistics-2024-to-2025", "2026-05-16", OGL)),
    ("geo/police_force_areas", (
        "ONS Open Geography portal, police force areas December 2023 BGC",
        "https://geoportal.statistics.gov.uk/", "2026-05-18", OGL_ONS)),
    ("geo/boundaries-2023", (
        "ONS Open Geography portal, December 2023 boundaries at BUC "
        "(ultra-generalised clipped): local authority districts, counties "
        "and unitary authorities, police force areas and English regions",
        "https://geoportal.statistics.gov.uk/", "2026-09-03", OGL_ONS)),
    # Named for the one file it describes, not the whole geo/ directory.
    # geo/ holds files from different ONS sources, so a directory-wide entry
    # here silently attributes anything added later to whichever file it was
    # written for. A new file falls through to the unattributed fallback
    # instead, which tests/test_raw_bundle.py fails on.
    ("geo/uk_authority_codes", (
        "ONS lookup table for UK authority codes 2024 (FOI-2024-2008)",
        "https://www.ons.gov.uk/aboutus/transparencyandgovernance/"
        "freedomofinformationfoi/lookuptableforukauthoritycodes2024",
        "2026-05-17", OGL_ONS)),
    ("statswales/", (
        "StatsWales and gov.wales: Welsh exclusions and children looked after",
        "https://www.gov.wales/permanent-and-fixed-term-exclusions-schools",
        "2026-05-17", OGL_WALES)),
    ("ycs/", (
        "MoJ Youth Custody Service monthly youth custody report",
        "https://www.gov.uk/government/publications/youth-custody-data",
        "2026-09-03", OGL)),
    ("fetch_manifest.json", (
        "Generated by pipeline/fetch.py: the machine-readable retrieval log",
        "https://github.com/SGilr/prism-r", "generated", OGL)),
]


def _source_for(relative: str) -> tuple[str, str, str, str]:
    best = None
    for prefix, meta in SOURCES:
        if relative.startswith(prefix) and (best is None or len(prefix) > len(best[0])):
            best = (prefix, meta)
    if best is None:
        return ("unattributed; add a SOURCES entry", "", "unknown", OGL)
    return best[1]


def write_bundle_doc(tag: str) -> int:
    files = sorted(
        p for p in RAW_DIR.rglob("*")
        if p.is_file() and p.name not in ("RAW_BUNDLE.md", ".gitkeep")
        and ".DS_Store" not in p.name
    )
    lines = [
        "# PRISM-R raw data bundle",
        "",
        f"Release {tag}, generated "
        f"{dt.date.today().isoformat()} by pipeline/make_raw_bundle.py.",
        "",
        "Every raw source file feeding the PRISM-R pipeline, as retrieved "
        "from the publishers. All content is public sector information "
        "licensed under the Open Government Licence v3.0; the licence "
        "column cites each publisher's licence page. Unpack to data/raw/ "
        "at the repository root, then run python pipeline/build.py.",
        "",
        "| file | source | source URL | retrieved | SHA-256 | licence |",
        "|---|---|---|---|---|---|",
    ]
    for path in files:
        relative = str(path.relative_to(RAW_DIR))
        description, url, retrieved, licence = _source_for(relative)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        lines.append(
            f"| {relative} | {description} | {url} | {retrieved} | "
            f"{digest} | {licence} |")
    BUNDLE_DOC.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return len(files)


def main() -> int:
    output_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else REPO_ROOT
    tag = f"raw-data-{dt.date.today().strftime('%Y-%m')}"
    count = write_bundle_doc(tag)
    print(f"RAW_BUNDLE.md written, {count} files listed")

    archive = output_dir / f"{tag}.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(RAW_DIR, arcname="data/raw", filter=lambda info:
                None if ".DS_Store" in info.name else info)
    size_mb = archive.stat().st_size / 1024 / 1024
    limit_gb = 2
    print(f"{archive.name}: {size_mb:.0f} MB "
          f"({'within' if size_mb < limit_gb * 1024 else 'EXCEEDS'} the "
          f"{limit_gb} GiB per-asset limit)")
    if size_mb >= limit_gb * 1024:
        return 1

    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT,
                            capture_output=True, text=True).stdout.strip()
    print("\nTo publish:")
    print(f"  gh release create {tag} {archive} \\")
    print(f"    --title 'Raw data bundle, {tag[9:]}' \\")
    print(f"    --notes 'Raw source files as listed in RAW_BUNDLE.md inside "
          f"the archive. Pipeline state: {commit[:12]}.'")
    return 0


if __name__ == "__main__":
    sys.exit(main())
