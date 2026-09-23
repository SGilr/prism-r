"""The site serves pipeline outputs copied at build time, never committed copies.

Until September 2026 site/public/data/ held hand-refreshed copies of
data/processed/, so a merged data refresh changed the pipeline outputs and
left the served downloads and explorer payloads on the previous month.
site/tools/sync-public.mjs now copies them on every build and dev start.
These tests hold that arrangement in place.
"""

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SITE = REPO_ROOT / "site"
SYNC = SITE / "tools" / "sync-public.mjs"
PROCESSED = REPO_ROOT / "data" / "processed"


def _listed(name: str) -> list[str]:
    text = SYNC.read_text("utf-8")
    match = re.search(rf"const {name} = \[([^\]]*)\]", text)
    assert match, f"{name} not found in sync-public.mjs"
    return re.findall(r"'([^']+)'", match.group(1))


def test_every_build_and_dev_start_syncs_first():
    scripts = json.loads((SITE / "package.json").read_text("utf-8"))["scripts"]
    assert scripts.get("prebuild") == "node tools/sync-public.mjs"
    assert scripts.get("predev") == "node tools/sync-public.mjs"


def test_the_copies_are_not_committed():
    ignore = (REPO_ROOT / ".gitignore").read_text("utf-8").splitlines()
    assert "site/public/data/" in ignore
    assert "site/public/scripts/" in ignore


def test_everything_synced_is_a_pipeline_output():
    """Only files the build writes, after suppression, may be served."""
    from pipeline import build
    outputs = set(build.MANIFEST_OUTPUTS) | {"manifest.json"}
    for name in _listed("DATA_FILES"):
        assert name in outputs, name
    for directory in _listed("DATA_DIRS"):
        assert any(o.startswith(directory + "/") for o in outputs), directory


def test_every_data_path_the_site_requests_is_synced():
    """A page linking to /data/x that the sync does not copy would 404.
    Root-relative URLs only; build-time reads of ../data/processed/ are not
    served paths."""
    synced = _listed("DATA_FILES") + [d + "/" for d in _listed("DATA_DIRS")]
    seen = 0
    for path in (SITE / "src").rglob("*"):
        if path.suffix not in (".astro", ".mjs", ".js", ".ts"):
            continue
        for ref in re.findall(r"[\"'`]/data/([A-Za-z0-9_./${}-]+)",
                              path.read_text("utf-8")):
            seen += 1
            assert any(ref == s or ref.startswith(s) for s in synced), (
                f"{path.relative_to(REPO_ROOT)} requests /data/{ref}")
    assert seen, "expected the site to request at least one /data/ file"


def test_the_client_scripts_come_from_src_lib():
    for name in _listed("SCRIPTS"):
        assert (SITE / "src" / "lib" / name).is_file(), name
