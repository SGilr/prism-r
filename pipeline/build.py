"""Orchestrate the full PRISM-R pipeline: one command, reproducible build.

Runs every ingest and compute step in dependency order, validates each
output, and writes a provenance manifest. After this, the whole pipeline is
reproducible with:

    python pipeline/build.py

Step order (dependency-ordered; the order is checked at runtime):

  1. ingest_yjb.py        geographies.json, remand_outcomes.json
  2. build_crosswalk.py   geo_crosswalk.json        (needs geographies.json)
  3. ingest_ons.py        populations.json
  4. ingest_dfe.py        ethnicity_crosswalk.json, context_indicators.json
  5. ingest_home_office.py  context_indicators.json (merge; needs 2, 3, 4)
  6. ingest_imd.py        context_indicators.json   (merge; needs 4)
  7. compute_rri.py       rri.json                  (needs 1, 3, 4, 5, 6)

There is no separate Welsh ingest: ingest_dfe.py ingests English and Welsh
exclusions and looked-after children together, because context_indicators.json
is co-written by indicator code and a second writer owning the same codes
would overwrite the first. context_indicators.json is co-written by steps 4
to 6; each owns its indicator codes and preserves the others' records.

Outputs go to data/processed/ only; the build never writes to data/raw/.

CLI flags:
  --dry-run         print the planned step order and exit
  --only STEP       run a single step by name (yjb, crosswalk, ons, dfe,
                    home_office, imd, rri)
  --from STEP       start at STEP and run every step after it
  --skip-raw-fetch  use the local data/raw/ files, do not fetch from source.
                    This is the only v1 behaviour: PRISM-R does not yet
                    automate downloads, so the flag is accepted and noted.

The build writes data/processed/manifest.json (the provenance record) and
data/processed/build.log (the run log). build.log is a runtime artefact and
is git-ignored; manifest.json is the committed provenance record.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import logging
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PIPELINE_DIR = REPO_ROOT / "pipeline"
PROCESSED_DIR = REPO_ROOT / "data" / "processed"
MANIFEST = PROCESSED_DIR / "manifest.json"
BUILD_LOG = PROCESSED_DIR / "build.log"

SCHEMA_VERSION = "1.0.0"

log = logging.getLogger("prism_r.build")


# --------------------------------------------------------------------------
# Pipeline definition
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class Step:
    """One pipeline step: a script, what it produces, and what it needs."""

    name: str
    script: str
    produces: tuple[str, ...]
    depends_on: tuple[str, ...]


STEPS: tuple[Step, ...] = (
    Step("yjb", "ingest_yjb.py",
         ("geographies.json", "remand_outcomes.json"), ()),
    Step("crosswalk", "build_crosswalk.py",
         ("geo_crosswalk.json",), ("yjb",)),
    Step("ons", "ingest_ons.py",
         ("populations.json",), ()),
    Step("dfe", "ingest_dfe.py",
         ("ethnicity_crosswalk.json", "context_indicators.json"), ("crosswalk",)),
    Step("home_office", "ingest_home_office.py",
         ("context_indicators.json",), ("dfe", "ons", "crosswalk", "yjb")),
    Step("imd", "ingest_imd.py",
         ("context_indicators.json",), ("dfe",)),
    Step("rri", "compute_rri.py",
         ("rri.json",), ("yjb", "ons", "dfe", "home_office", "imd")),
)

# Every processed output, in a stable manifest order.
PROCESSED_OUTPUTS: tuple[str, ...] = (
    "geographies.json",
    "geo_crosswalk.json",
    "remand_outcomes.json",
    "populations.json",
    "ethnicity_crosswalk.json",
    "context_indicators.json",
    "rri.json",
)

# Validation gate: minimum record count per output. ethnicity_crosswalk.json
# carries mappings rather than a records array and is validated separately.
MIN_RECORDS: dict[str, int] = {
    "geographies.json": 200,
    "geo_crosswalk.json": 300,
    "remand_outcomes.json": 60,
    "populations.json": 9000,
    "context_indicators.json": 3700,
    "rri.json": 40,
}


# --------------------------------------------------------------------------
# Provenance, for the manifest
# --------------------------------------------------------------------------
_YJS = {
    "description": "YJB and MoJ Youth Justice Statistics 2024 to 2025",
    "url": "https://www.gov.uk/government/statistics/youth-justice-statistics-2024-to-2025",
    "reference_period": "year ending March 2025",
    "publication_date": "2026-01-29",
    "retrieval_date": "2026-05-16",
}
_HOME_OFFICE = {
    "description": "Home Office Police powers and procedures, stop and search and arrests",
    "url": "https://www.gov.uk/government/statistics/stop-and-search-arrests-and-mental-health-detentions-march-2025",
    "reference_period": "year ending 31 March 2025",
    "publication_date": "2025-11-06",
    "retrieval_date": "2026-05-17",
}

PROVENANCE: dict[str, list[dict]] = {
    "geographies.json": [
        {**_YJS, "description": "YJB Youth Justice Statistics 2024 to 2025; "
         "gov.uk youth justice services directory"},
    ],
    "geo_crosswalk.json": [
        {
            "description": "ONS lookup table for UK Authority Codes 2024 (FOI-2024-2008)",
            "url": "https://www.ons.gov.uk/aboutus/transparencyandgovernance/freedomofinformationfoi/lookuptableforukauthoritycodes2024",
            "reference_period": "2024 local authority and police force geography",
            "publication_date": "2024-05-20",
            "retrieval_date": "2026-05-17",
        },
    ],
    "remand_outcomes.json": [
        {**_YJS, "description": "YJB Youth Justice Statistics 2024 to 2025, "
         "remand and outcomes tables"},
    ],
    "populations.json": [
        {
            "description": "ONS Census 2021, dataset RM032, ethnic group by sex "
            "by age, via the ONS filter service",
            "url": "https://www.ons.gov.uk/datasets/RM032",
            "reference_period": "Census day, 21 March 2021",
            "publication_date": "2023-03-28",
            "retrieval_date": "2026-05-17",
        },
    ],
    "ethnicity_crosswalk.json": [
        {
            "description": "ONS Census 2021 and DfE school census ethnicity "
            "classifications, rolled up to the YJB five groups",
            "url": "",
            "reference_period": "classification crosswalk, not a dated dataset",
            "publication_date": None,
            "retrieval_date": "2026-05-17",
        },
    ],
    "context_indicators.json": [
        {
            "description": "DfE Suspensions and permanent exclusions in England",
            "url": "https://explore-education-statistics.service.gov.uk/find-statistics/suspensions-and-permanent-exclusions-in-england",
            "reference_period": "academic year 2023/24",
            "publication_date": "2025-07-10",
            "retrieval_date": "2026-05-17",
        },
        {
            "description": "DfE Children looked after in England including adoptions",
            "url": "https://explore-education-statistics.service.gov.uk/find-statistics/children-looked-after-in-england-including-adoptions",
            "reference_period": "year ending 31 March 2025",
            "publication_date": "2025-11-26",
            "retrieval_date": "2026-05-17",
        },
        {
            "description": "StatsWales, Welsh Government, permanent and fixed-term "
            "exclusions from schools",
            "url": "https://www.gov.wales/permanent-and-fixed-term-exclusions-schools",
            "reference_period": "academic year 2023/24",
            "publication_date": "2025-11-01",
            "retrieval_date": "2026-05-17",
        },
        {
            "description": "StatsWales, Children looked after on 31 March by ethnicity",
            "url": "https://www.gov.wales/children-looked-after-local-authorities",
            "reference_period": "year ending 31 March 2024",
            "publication_date": "2026-01-30",
            "retrieval_date": "2026-05-17",
        },
        {**_HOME_OFFICE, "description": "Home Office Police powers and procedures, "
         "stop and search open data tables"},
        {**_HOME_OFFICE, "description": "Home Office Police powers and procedures, "
         "arrests open data tables"},
        {
            "description": "MHCLG English Indices of Deprivation 2025, IDACI "
            "supplementary index",
            "url": "https://www.gov.uk/government/statistics/english-indices-of-deprivation-2025",
            "reference_period": "income data financial year 2022/23",
            "publication_date": "2025-10-30",
            "retrieval_date": "2026-05-17",
        },
        {
            "description": "Welsh Index of Multiple Deprivation 2019, income "
            "deprivation for children indicator",
            "url": "https://www.gov.wales/welsh-index-multiple-deprivation-2025",
            "reference_period": "income data financial year 2016/17",
            "publication_date": "2019-11-27",
            "retrieval_date": "2026-05-17",
        },
    ],
    "rri.json": [
        {
            "description": "MoJ Statistics on Ethnicity and the Criminal Justice "
            "System 2024",
            "url": "https://www.gov.uk/government/statistics/ethnicity-and-the-criminal-justice-system-2024",
            "reference_period": "calendar year 2024",
            "publication_date": "2025-11-27",
            "retrieval_date": "2026-05-17",
        },
        {**_YJS, "description": "YJB Youth Justice Statistics 2024 to 2025, "
         "sentencing and remand tables"},
        {**_HOME_OFFICE, "description": "Home Office Police powers and procedures, "
         "stop and search and arrests open data"},
    ],
}


# --------------------------------------------------------------------------
# Dependency graph
# --------------------------------------------------------------------------
def dependency_issues() -> list[str]:
    """Check the step graph: unique names, known deps, valid acyclic order.

    Every dependency must reference a known step and must appear earlier in
    STEPS. If every dependency precedes its dependant, the listed order is a
    valid topological sort and the graph is therefore acyclic.
    """
    issues: list[str] = []
    names = [s.name for s in STEPS]
    if len(names) != len(set(names)):
        issues.append("step names are not unique")
    seen: set[str] = set()
    for step in STEPS:
        for dep in step.depends_on:
            if dep not in names:
                issues.append(f"step {step.name!r} depends on unknown step {dep!r}")
            elif dep not in seen:
                issues.append(
                    f"step {step.name!r} depends on {dep!r}, which is not run earlier"
                )
        seen.add(step.name)
    produced = {output for step in STEPS for output in step.produces}
    for output in PROCESSED_OUTPUTS:
        if output not in produced:
            issues.append(f"manifest output {output!r} is produced by no step")
    return issues


def step_by_name(name: str) -> Step | None:
    return next((s for s in STEPS if s.name == name), None)


def planned_steps(only: str | None, from_: str | None) -> list[Step]:
    """The steps to run, given --only and --from."""
    if only is not None:
        step = step_by_name(only)
        return [step] if step else []
    if from_ is not None:
        names = [s.name for s in STEPS]
        if from_ not in names:
            return []
        start = names.index(from_)
        return list(STEPS[start:])
    return list(STEPS)


# --------------------------------------------------------------------------
# Running and validating a step
# --------------------------------------------------------------------------
def run_step(step: Step) -> dict:
    """Run one pipeline script as a subprocess. Returns a result dict."""
    started = time.monotonic()
    completed = subprocess.run(
        [sys.executable, str(PIPELINE_DIR / step.script)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    return {
        "name": step.name,
        "script": f"pipeline/{step.script}",
        "status": "ok" if completed.returncode == 0 else "failed",
        "return_code": completed.returncode,
        "duration_seconds": round(time.monotonic() - started, 2),
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def validate_output(filename: str) -> tuple[bool, str]:
    """Validate one processed output: it parses, and meets schema expectations.

    Every output must be a JSON object with a meta block. Record-bearing files
    must have a records array of at least the expected size; the ethnicity
    crosswalk must have a non-empty mappings object.
    """
    path = PROCESSED_DIR / filename
    if not path.exists():
        return False, f"{filename}: not written"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        return False, f"{filename}: invalid JSON ({error})"
    if not isinstance(payload, dict) or "meta" not in payload:
        return False, f"{filename}: missing meta block"
    if filename == "ethnicity_crosswalk.json":
        mappings = payload.get("mappings")
        if not isinstance(mappings, dict) or not mappings:
            return False, f"{filename}: missing or empty mappings"
        return True, f"{filename}: {len(mappings)} mappings"
    records = payload.get("records")
    if not isinstance(records, list):
        return False, f"{filename}: missing records array"
    minimum = MIN_RECORDS.get(filename, 1)
    if len(records) < minimum:
        return False, f"{filename}: {len(records)} records, below the expected {minimum}"
    return True, f"{filename}: {len(records)} records"


def suppression_warnings(filename: str) -> list[str]:
    """Non-fatal notes: indicators carrying source-suppressed cells."""
    if filename != "context_indicators.json":
        return []
    payload = json.loads((PROCESSED_DIR / filename).read_text(encoding="utf-8"))
    notes = []
    for indicator, counts in payload.get("meta", {}).get("indicators", {}).items():
        suppressed = counts.get("source_suppressed", 0)
        if suppressed:
            notes.append(
                f"{indicator}: {suppressed} source-suppressed cells carried as null"
            )
    return notes


# --------------------------------------------------------------------------
# Manifest
# --------------------------------------------------------------------------
def file_entry(filename: str) -> dict:
    """One manifest entry: integrity and provenance for a processed output."""
    path = PROCESSED_DIR / filename
    data = path.read_bytes()
    payload = json.loads(data)
    records = len(payload["records"]) if isinstance(payload.get("records"), list) else None
    generated_by = payload.get("meta", {}).get("generated_by")
    return {
        "file": f"data/processed/{filename}",
        "schema_version": SCHEMA_VERSION,
        "sha256": hashlib.sha256(data).hexdigest(),
        "bytes": len(data),
        "records": records,
        "generated_by": generated_by,
        "sources": PROVENANCE.get(filename, []),
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

    status = _git("status", "--porcelain")
    return {
        "commit": _git("rev-parse", "HEAD"),
        "working_tree": None if status is None else ("clean" if status == "" else "dirty"),
    }


def write_manifest(step_results: list[dict]) -> dict:
    """Assemble and write data/processed/manifest.json."""
    outputs = [file_entry(name) for name in PROCESSED_OUTPUTS
               if (PROCESSED_DIR / name).exists()]
    manifest = {
        "meta": {
            "dataset": "build_manifest",
            "generated_by": "pipeline/build.py",
            "schema_version": SCHEMA_VERSION,
            "build_timestamp": dt.datetime.now(dt.timezone.utc).isoformat(
                timespec="seconds"),
            "git": git_state(),
            "python_version": sys.version.split()[0],
            "schema_note": (
                "A provenance record of one pipeline build. steps lists each "
                "script run, in order, with its timing. outputs gives a "
                "SHA-256 checksum, byte size, record count and source "
                "provenance for every processed JSON file. build_timestamp "
                "changes each run, so the manifest is not byte-identical "
                "between builds; the processed outputs themselves are "
                "deterministic and reproduce byte-for-byte."
            ),
        },
        "steps": [
            {
                "step": i + 1,
                "name": result["name"],
                "script": result["script"],
                "status": result["status"],
                "duration_seconds": result["duration_seconds"],
            }
            for i, result in enumerate(step_results)
        ],
        "outputs": outputs,
    }
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    with MANIFEST.open("w", encoding="utf-8") as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    return manifest


# --------------------------------------------------------------------------
# Logging
# --------------------------------------------------------------------------
def setup_logging(to_file: bool) -> None:
    """Configure the build logger: stdout always, build.log on real runs."""
    log.setLevel(logging.INFO)
    log.handlers.clear()
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(message)s",
                            datefmt="%Y-%m-%dT%H:%M:%S")
    stream = logging.StreamHandler(sys.stdout)
    stream.setFormatter(fmt)
    log.addHandler(stream)
    if to_file:
        PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(BUILD_LOG, mode="w", encoding="utf-8")
        handler.setFormatter(fmt)
        log.addHandler(handler)


# --------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------
def run_pipeline(steps: list[Step]) -> tuple[int, list[dict]]:
    """Run the given steps in order, validating each. Returns (exit, results)."""
    results: list[dict] = []
    for index, step in enumerate(steps, start=1):
        log.info("step %d/%d: pipeline/%s", index, len(steps), step.script)
        result = run_step(step)
        results.append(result)
        for line in result["stdout"].splitlines():
            log.info("  %s", line)
        if result["status"] != "ok":
            log.error("step %r failed, exit code %d", step.name, result["return_code"])
            for line in result["stderr"].splitlines():
                log.error("  %s", line)
            return 1, results

        gate_failed = False
        for output in step.produces:
            ok, message = validate_output(output)
            if ok:
                log.info("  validated %s", message)
                for note in suppression_warnings(output):
                    log.warning("  %s", note)
            else:
                log.error("  validation failed: %s", message)
                gate_failed = True
        if gate_failed:
            return 1, results
        log.info("  step %r ok, %.2fs", step.name, result["duration_seconds"])
    return 0, results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the PRISM-R pipeline and write the build manifest.")
    parser.add_argument("--dry-run", action="store_true",
                        help="print the planned step order and exit")
    parser.add_argument("--skip-raw-fetch", action="store_true",
                        help="use local data/raw/ files (the only v1 behaviour)")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--only", metavar="STEP",
                       help="run only the named step")
    group.add_argument("--from", metavar="STEP", dest="from_step",
                       help="start at the named step and run every step after it")
    args = parser.parse_args(argv)

    issues = dependency_issues()
    if issues:
        setup_logging(to_file=False)
        for issue in issues:
            log.error("dependency graph: %s", issue)
        return 1

    steps = planned_steps(args.only, args.from_step)
    if not steps:
        setup_logging(to_file=False)
        valid = ", ".join(s.name for s in STEPS)
        log.error("no steps selected; valid step names are: %s", valid)
        return 1

    if args.dry_run:
        setup_logging(to_file=False)
        log.info("PRISM-R pipeline, planned execution (%d steps):", len(steps))
        for index, step in enumerate(steps, start=1):
            produces = ", ".join(step.produces)
            log.info("  %d. %s  (pipeline/%s -> %s)", index, step.name,
                     step.script, produces)
        return 0

    setup_logging(to_file=True)
    log.info("PRISM-R pipeline build")
    if args.skip_raw_fetch:
        log.info("--skip-raw-fetch: using local data/raw/ files")
    else:
        log.info("PRISM-R v1 does not automate downloads; using local "
                 "data/raw/ files (as with --skip-raw-fetch)")
    if len(steps) != len(STEPS):
        log.warning("partial build: %d of %d steps; outputs of skipped steps "
                    "must already exist", len(steps), len(STEPS))

    exit_code, results = run_pipeline(steps)
    manifest = write_manifest(results)
    total = sum(r["duration_seconds"] for r in results)

    if exit_code == 0:
        log.info("build complete: %d steps in %.1fs", len(results), total)
        log.info("manifest.json written, %d processed outputs",
                 len(manifest["outputs"]))
        for output in manifest["outputs"]:
            records = output["records"]
            tag = f"{records:>7,} records" if records is not None else "       (mappings)"
            log.info("  %-38s %s  %s", output["file"], tag, output["sha256"][:12])
    else:
        log.error("build aborted after %d steps; partial manifest written", len(results))
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
