"""Fetch layer: download the fast-refreshing raw sources.

One fetcher per source. Each fetcher parses its landing page for the latest
release, downloads only when the release is newer than the recorded state,
and records the download URL, retrieval timestamp, SHA-256 and the source's
own publication date in data/raw/fetch_manifest.json. The manifest is
tracked in git: it is the machine-readable arm of the retrieval log in
docs/data-sources.md.

Automated sources, in refresh order:

  ycs             the monthly youth custody report. The media path changes
                  every month, so the publication page is parsed for the
                  latest ODS link; a new linked filename triggers a download.
  dfe_exclusions  suspensions and permanent exclusions in England, via the
                  explore-education-statistics content API. The latest
                  full-academic-year release is used; termly releases are
                  ignored. A new release id triggers a download.
  yjs             the annual Youth Justice Statistics: the collection page
                  is parsed for the latest year's publication, and its
                  supplementary tables and local-level open data archives
                  are downloaded. A new publication year triggers a
                  download.

ONS Census, IMD, Home Office and StatsWales remain manual and are listed in
the manifest with manual: true and their last retrieval date.

Run directly (python pipeline/fetch.py [source ...]) or via
python pipeline/build.py --fetch. Without --fetch the build stays offline.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import ssl
import sys
import urllib.request
from pathlib import Path

import certifi

REPO_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = REPO_ROOT / "data" / "raw"
FETCH_MANIFEST = RAW_DIR / "fetch_manifest.json"

USER_AGENT = "PRISM-R data pipeline (https://github.com/SGilr/prism-r)"

YCS_PAGE = "https://www.gov.uk/government/publications/youth-custody-data"
DFE_RELEASES_API = (
    "https://content.explore-education-statistics.service.gov.uk/api/"
    "publications/suspensions-and-permanent-exclusions-in-england/releases"
)
DFE_ZIP_API = (
    "https://content.explore-education-statistics.service.gov.uk/api/"
    "releases/{release_id}/files?fromPage=ReleaseDownloads"
)
YJS_COLLECTION = "https://www.gov.uk/government/collections/youth-justice-statistics"

MANUAL_SOURCES = {
    "ons_census_2021": {
        "manual": True,
        "last_retrieved": "2026-05-17",
        "note": "pulled through the ONS filter service; request specs in "
                "data/raw/ons-census-2021/filter_manifest.json",
    },
    "imd": {
        "manual": True,
        "last_retrieved": "2026-05-17",
        "note": "IoD2025 files from gov.uk; WIMD 2019 export from StatsWales",
    },
    "home_office": {
        "manual": True,
        "last_retrieved": "2026-05-17",
        "note": "Police powers and procedures open data tables, year ending "
                "March 2025",
    },
    "statswales": {
        "manual": True,
        "last_retrieved": "2026-05-17",
        "note": "Welsh exclusions and children looked after; the stats.gov.wales "
                "platform needs a browser export",
    },
}


# --------------------------------------------------------------------------
# HTTP and manifest helpers
# --------------------------------------------------------------------------
_SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())


def _get(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=120,
                                context=_SSL_CONTEXT) as response:
        return response.read()


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_manifest() -> dict:
    if FETCH_MANIFEST.exists():
        return json.loads(FETCH_MANIFEST.read_text(encoding="utf-8"))
    return {"meta": {}, "sources": {}}


def save_manifest(sources: dict) -> None:
    payload = {
        "meta": {
            "dataset": "fetch_manifest",
            "generated_by": "pipeline/fetch.py",
            "schema_note": (
                "One entry per source. Automated entries record the download "
                "URL, retrieval timestamp, SHA-256 and the source's own "
                "publication date; status is downloaded or unchanged, and "
                "last_checked is stamped on every run. Manual sources carry "
                "manual: true and their last retrieval date. The manifest is "
                "the machine-readable arm of docs/data-sources.md."
            ),
        },
        "sources": sources,
    }
    FETCH_MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    with FETCH_MANIFEST.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")


def _download(url: str, dest: Path) -> dict:
    data = _get(url)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return {
        "download_url": url,
        "path": str(dest.relative_to(REPO_ROOT)),
        "filename": dest.name,
        "bytes": len(data),
        "sha256": _sha256(data),
        "retrieved_at": _now(),
    }


def _page_updated_at(html: str) -> str | None:
    """The gov.uk page's last-updated stamp.

    dateModified (JSON-LD) or the govuk:updated-at meta tag; datePublished is
    the page's original publication date, often years old, and is the last
    resort only.
    """
    for pattern in (
        r'"dateModified"\s*:\s*"([^"]+)"',
        r'<meta name="govuk:updated-at" content="([^"]+)"',
        r'"datePublished"\s*:\s*"([^"]+)"',
    ):
        match = re.search(pattern, html)
        if match:
            return match.group(1)
    return None


# --------------------------------------------------------------------------
# Fetchers
# --------------------------------------------------------------------------
def fetch_ycs(previous: dict) -> dict:
    """The monthly youth custody report ODS, from the publication page."""
    html = _get(YCS_PAGE).decode("utf-8", "replace")
    links = re.findall(
        r'href="(https://assets\.publishing\.service\.gov\.uk/media/[a-f0-9]+/'
        r'(youth-custody[^"]*?\.ods))"', html)
    if not links:
        raise ValueError("no youth custody ODS link found on the publication page")
    url, filename = links[0]
    updated = _page_updated_at(html)

    if previous.get("filename") == filename:
        return {**previous, "status": "unchanged", "last_checked": _now()}

    entry = _download(url, RAW_DIR / "ycs" / filename)
    return {
        **entry,
        "manual": False,
        "page_url": YCS_PAGE,
        "source_publication_date": updated,
        "status": "downloaded",
        "last_checked": entry["retrieved_at"],
    }


def fetch_dfe_exclusions(previous: dict) -> dict:
    """The latest full-academic-year DfE exclusions release, via the EES API."""
    releases = json.loads(_get(DFE_RELEASES_API).decode("utf-8"))
    if isinstance(releases, dict):
        releases = releases.get("results", releases.get("releases", []))
    full_years = [
        r for r in releases
        if str(r.get("coverageTitle", r.get("title", ""))).lower().startswith(
            "academic year")
        and "term" not in str(r.get("title", "")).lower()
    ]
    if not full_years:
        raise ValueError("no full-academic-year release found in the EES API")
    latest = max(full_years, key=lambda r: str(r.get("published", "")))
    release_id = latest["id"]

    if previous.get("release_id") == release_id:
        return {**previous, "status": "unchanged", "last_checked": _now()}

    slug = str(latest.get("slug", release_id)).replace("/", "-")
    dest = RAW_DIR / "dfe" / f"exclusions_{slug}_alldata.zip"
    entry = _download(DFE_ZIP_API.format(release_id=release_id), dest)
    return {
        **entry,
        "manual": False,
        "page_url": (
            "https://explore-education-statistics.service.gov.uk/find-statistics/"
            "suspensions-and-permanent-exclusions-in-england"),
        "release_id": release_id,
        "release_title": latest.get("title"),
        "release_slug": latest.get("slug"),
        "source_publication_date": latest.get("published"),
        "status": "downloaded",
        "last_checked": entry["retrieved_at"],
    }


def fetch_yjs(previous: dict) -> dict:
    """The latest annual Youth Justice Statistics archives."""
    collection = _get(YJS_COLLECTION).decode("utf-8", "replace")
    stats_pages = re.findall(
        r'href="(/government/statistics/youth-justice-statistics-(\d{4})-to-\d{4})"',
        collection)
    if not stats_pages:
        raise ValueError("no youth justice statistics publication found on the "
                         "collection page")
    path, start_year = max(stats_pages, key=lambda p: int(p[1]))
    page_url = f"https://www.gov.uk{path}"

    if previous.get("publication_path") == path:
        return {**previous, "status": "unchanged", "last_checked": _now()}

    html = _get(page_url).decode("utf-8", "replace")
    updated = _page_updated_at(html)
    zips = re.findall(
        r'href="(https://assets\.publishing\.service\.gov\.uk/media/[a-f0-9]+/'
        r'([^"]*?\.zip))"', html)
    wanted = {}
    for url, filename in zips:
        lowered = filename.lower()
        if "supplementary" in lowered and "supplementary" not in wanted:
            wanted["supplementary"] = (url, filename)
        elif "open_data" in lowered or "open-data" in lowered:
            wanted["local"] = (url, filename)  # the open data tables, preferred
        elif "local" in lowered and "local" not in wanted:
            wanted["local"] = (url, filename)  # fallback, for example pivot tables
    if len(wanted) < 2:
        raise ValueError(
            f"expected supplementary and local-level archives on {page_url}, "
            f"found {sorted(wanted)}")

    year_dir = RAW_DIR / f"yjb-{start_year}-{str(int(start_year) + 1)[2:]}"
    files = []
    for _, (url, filename) in sorted(wanted.items()):
        files.append(_download(url, year_dir / filename))
    return {
        "manual": False,
        "page_url": page_url,
        "publication_path": path,
        "source_publication_date": updated,
        "files": files,
        "status": "downloaded",
        "retrieved_at": files[0]["retrieved_at"],
        "last_checked": files[0]["retrieved_at"],
    }


FETCHERS = {
    "ycs": fetch_ycs,
    "dfe_exclusions": fetch_dfe_exclusions,
    "yjs": fetch_yjs,
}


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------
def run(names: list[str] | None = None) -> int:
    """Run the named fetchers (all automated fetchers by default)."""
    selected = names or list(FETCHERS)
    unknown = [n for n in selected if n not in FETCHERS]
    if unknown:
        print(f"unknown source(s): {unknown}; valid: {sorted(FETCHERS)}",
              file=sys.stderr)
        return 1

    sources = load_manifest().get("sources", {})
    failures = 0
    for name in selected:
        previous = sources.get(name, {})
        try:
            entry = FETCHERS[name](previous)
        except Exception as error:  # noqa: BLE001 - report and continue
            failures += 1
            print(f"  {name}: FAILED ({error})", file=sys.stderr)
            if previous:
                sources[name] = {**previous, "last_check_failed": _now()}
            continue
        sources[name] = entry
        label = entry["status"]
        detail = entry.get("filename") or entry.get("publication_path") or ""
        print(f"  {name}: {label}  {detail}")

    for name, entry in MANUAL_SOURCES.items():
        sources.setdefault(name, entry)

    save_manifest(sources)
    print(f"fetch_manifest.json written, {len(sources)} sources")
    return 1 if failures else 0


def main() -> int:
    return run(sys.argv[1:] or None)


if __name__ == "__main__":
    sys.exit(main())
