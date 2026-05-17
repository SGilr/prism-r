"""Orchestrate the full PRISM-R pipeline and emit a build manifest.

Runs every ingest and compute step in dependency order, then writes
data/processed/manifest.json: a provenance record of the build, with a
SHA-256 checksum, byte size and record count for each processed output, the
git commit, the Python version and a per-step timing log.

Step order matters:

  1. ingest_yjb.py        geographies.json, remand_outcomes.json
  2. build_crosswalk.py   geo_crosswalk.json        (needs geographies.json)
  3. ingest_ons.py        populations.json
  4. ingest_dfe.py        ethnicity_crosswalk.json, context_indicators.json
  5. ingest_home_office.py  context_indicators.json (merge; needs steps 3, 4)
  6. ingest_imd.py        context_indicators.json   (merge; needs step 4)
  7. compute_rri.py       rri.json                  (needs steps 1, 3, 4)

context_indicators.json is co-written by steps 4 to 6: each owns its indicator
codes and preserves the others' records, so the merge is order-independent,
but running them in this order keeps the build log readable.

Run from anywhere: python pipeline/build.py

The pipeline needs the raw source files under data/raw/, which are not in the
repository. The build fails cleanly if a source file is missing.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PIPELINE_DIR = REPO_ROOT / "pipeline"
PROCESSED_DIR = REPO_ROOT / "data" / "processed"
MANIFEST = PROCESSED_DIR / "manifest.json"

# Ordered pipeline steps: (script, outputs the step produces or updates).
STEPS: list[tuple[str, list[str]]] = [
    ("ingest_yjb.py", ["geographies.json", "remand_outcomes.json"]),
    ("build_crosswalk.py", ["geo_crosswalk.json"]),
    ("ingest_ons.py", ["populations.json"]),
    ("ingest_dfe.py", ["ethnicity_crosswalk.json", "context_indicators.json"]),
    ("ingest_home_office.py", ["context_indicators.json"]),
    ("ingest_imd.py", ["context_indicators.json"]),
    ("compute_rri.py", ["rri.json"]),
]

# Every processed output, in a stable order, for the manifest.
PROCESSED_OUTPUTS = [
    "geographies.json",
    "geo_crosswalk.json",
    "remand_outcomes.json",
    "populations.json",
    "ethnicity_crosswalk.json",
    "context_indicators.json",
    "rri.json",
]


# --------------------------------------------------------------------------
# Running steps
# --------------------------------------------------------------------------
def run_step(script: str) -> dict:
    """Run one pipeline script as a subprocess. Returns a step result dict."""
    started = time.monotonic()
    completed = subprocess.run(
        [sys.executable, str(PIPELINE_DIR / script)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    duration = round(time.monotonic() - started, 2)
    return {
        "script": f"pipeline/{script}",
        "status": "ok" if completed.returncode == 0 else "failed",
        "return_code": completed.returncode,
        "duration_seconds": duration,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


# --------------------------------------------------------------------------
# Manifest helpers
# --------------------------------------------------------------------------
def file_digest(path: Path) -> dict:
    """SHA-256, byte size and record count for a processed JSON file."""
    data = path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    records = None
    generated_by = None
    try:
        payload = json.loads(data)
    except json.JSONDecodeError:
        payload = None
    if isinstance(payload, dict):
        if isinstance(payload.get("records"), list):
            records = len(payload["records"])
        meta = payload.get("meta")
        if isinstance(meta, dict):
            generated_by = meta.get("generated_by")
    return {
        "file": f"data/processed/{path.name}",
        "sha256": digest,
        "bytes": len(data),
        "records": records,
        "generated_by": generated_by,
    }


def git_state() -> dict:
    """Current git commit and whether the working tree is clean."""
    def _git(*args: str) -> str | None:
        try:
            out = subprocess.run(
                ["git", *args], cwd=REPO_ROOT,
                capture_output=True, text=True, check=True,
            )
        except (subprocess.CalledProcessError, FileNotFoundError):
            return None
        return out.stdout.strip()

    commit = _git("rev-parse", "HEAD")
    status = _git("status", "--porcelain")
    working_tree = None
    if status is not None:
        working_tree = "clean" if status == "" else "dirty"
    return {"commit": commit, "working_tree": working_tree}


def write_manifest(steps: list[dict]) -> dict:
    """Assemble and write data/processed/manifest.json."""
    outputs = [
        file_digest(PROCESSED_DIR / name)
        for name in PROCESSED_OUTPUTS
        if (PROCESSED_DIR / name).exists()
    ]
    manifest = {
        "meta": {
            "dataset": "build_manifest",
            "generated_by": "pipeline/build.py",
            "build_timestamp": dt.datetime.now(dt.timezone.utc).isoformat(
                timespec="seconds"
            ),
            "git": git_state(),
            "python_version": sys.version.split()[0],
            "schema_note": (
                "A provenance record of one pipeline build. steps lists each "
                "script run, in order, with its timing. outputs gives a "
                "SHA-256 checksum, byte size and record count for every "
                "processed JSON file. build_timestamp changes each run, so "
                "the manifest is not byte-identical between builds; the "
                "processed outputs themselves are deterministic."
            ),
        },
        "steps": [
            {
                "step": i + 1,
                "script": step["script"],
                "outputs": [f"data/processed/{o}" for o in step["outputs"]],
                "status": step["status"],
                "duration_seconds": step["duration_seconds"],
            }
            for i, step in enumerate(steps)
        ],
        "outputs": outputs,
    }
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    with MANIFEST.open("w", encoding="utf-8") as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    return manifest


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------
def main() -> int:
    print("PRISM-R pipeline build")
    print("=" * 60)
    results: list[dict] = []
    for index, (script, outputs) in enumerate(STEPS, start=1):
        print(f"\n[{index}/{len(STEPS)}] pipeline/{script}")
        result = run_step(script)
        result["outputs"] = outputs
        results.append(result)
        for line in result["stdout"].splitlines():
            print(f"    {line}")
        if result["status"] != "ok":
            print(f"    STEP FAILED (exit {result['return_code']})")
            for line in result["stderr"].splitlines():
                print(f"    {line}")
            # Still write a manifest so the partial build is recorded.
            write_manifest(results)
            print(f"\nBuild aborted at step {index}. Manifest written.")
            return 1
        print(f"    ok, {result['duration_seconds']}s")

    manifest = write_manifest(results)
    total = sum(s["duration_seconds"] for s in results)
    print("\n" + "=" * 60)
    print(f"Build complete: {len(STEPS)} steps in {round(total, 1)}s")
    print(f"manifest.json written, {len(manifest['outputs'])} processed outputs")
    for output in manifest["outputs"]:
        records = output["records"]
        tag = (
            f"{records:>7,} records" if records is not None
            else "       no records array"
        )
        print(f"  {output['file']:42s} {tag}  {output['sha256'][:12]}")
    git = manifest["meta"]["git"]
    if git["commit"]:
        print(f"git commit {git['commit'][:12]} ({git['working_tree']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
