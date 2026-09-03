"""Orchestrate the full PRISM-R pipeline: one command, reproducible build.

Runs every ingest and compute step in dependency order, validates each
output, and writes a provenance manifest. After this, the whole pipeline is
reproducible with:

    python pipeline/build.py

Step order (dependency-ordered; the order is checked at runtime):

  1. ingest_yjb.py        geographies.json, remand_outcomes.json
  2. build_crosswalk.py   geo_crosswalk.json        (needs geographies.json)
  3. build_force_boundaries.py  force_boundaries.json  (needs geographies.json)
  4. ingest_ycs.py        custody_monthly.json, custody_episodes_ending.json,
                          custody_episode_length.json
  5. ingest_ons.py        populations.json
  6. ingest_dfe.py        ethnicity_crosswalk.json, context_indicators.json
  7. ingest_home_office.py  context_indicators.json (merge; needs 2, 5, 6)
  8. ingest_imd.py        context_indicators.json   (merge; needs 6)
  9. compute_rri.py       rri.json                  (needs 1, 5, 6, 7, 8)
  10. compute_target.py   target_tracker.json       (needs 1, 4)

There is no separate Welsh ingest: ingest_dfe.py ingests English and Welsh
exclusions and looked-after children together, because context_indicators.json
is co-written by indicator code and a second writer owning the same codes
would overwrite the first. context_indicators.json is co-written by steps 4
to 6; each owns its indicator codes and preserves the others' records.

Outputs go to data/processed/ only; the build never writes to data/raw/.

CLI flags:
  --dry-run         print the planned step order and exit
  --only STEP       run a single step by name (yjb, crosswalk, boundaries,
                    ycs, ons, dfe, home_office, imd, rri, target)
  --from STEP       start at STEP and run every step after it
  --fetch           run the fetch layer (pipeline/fetch.py) first, so the
                    fast-refreshing raw sources are brought up to date before
                    ingest. Default behaviour stays offline, using the local
                    data/raw/ files.

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
SUPPRESSION_AUDIT = PROCESSED_DIR / "suppression_audit.json"

SCHEMA_VERSION = "1.0.0"

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
from pipeline.suppress import Cell, apply_suppression  # noqa: E402

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
    Step("boundaries", "build_force_boundaries.py",
         ("force_boundaries.json",), ("yjb",)),
    Step("ycs", "ingest_ycs.py",
         ("custody_monthly.json", "custody_episodes_ending.json",
          "custody_episode_length.json"), ()),
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
    Step("target", "compute_target.py",
         ("target_tracker.json",), ("yjb", "ycs")),
)

# Every processed output, in a stable manifest order.
PROCESSED_OUTPUTS: tuple[str, ...] = (
    "geographies.json",
    "geo_crosswalk.json",
    "force_boundaries.json",
    "custody_monthly.json",
    "custody_episodes_ending.json",
    "custody_episode_length.json",
    "remand_outcomes.json",
    "populations.json",
    "ethnicity_crosswalk.json",
    "context_indicators.json",
    "rri.json",
    "target_tracker.json",
)

# Validation gate: minimum record count per output. ethnicity_crosswalk.json
# carries mappings rather than a records array and is validated separately.
MIN_RECORDS: dict[str, int] = {
    "geographies.json": 200,
    "geo_crosswalk.json": 300,
    "force_boundaries.json": 42,
    "custody_monthly.json": 2500,
    "custody_episodes_ending.json": 40,
    "custody_episode_length.json": 200,
    "remand_outcomes.json": 60,
    "populations.json": 9000,
    "context_indicators.json": 3700,
    "rri.json": 40,
    "target_tracker.json": 900,
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
_YCS = {
    "description": "MoJ Youth Custody Service, monthly youth custody report, "
    "June 2026 edition",
    "url": "https://www.gov.uk/government/publications/youth-custody-data",
    "reference_period": "monthly, April 2000 to June 2026; the latest month "
    "is provisional",
    "publication_date": "2026-08-14",
    "retrieval_date": "2026-09-03",
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
    "force_boundaries.json": [
        {
            "description": "ONS Open Geography portal, Police Force Areas "
            "(December 2023), generalised clipped boundaries (BGC)",
            "url": "https://geoportal.statistics.gov.uk/",
            "reference_period": "December 2023 police force geography, unchanged since",
            "publication_date": "2024",
            "retrieval_date": "2026-05-18",
        },
    ],
    "custody_monthly.json": [_YCS],
    "custody_episodes_ending.json": [_YCS],
    "custody_episode_length.json": [_YCS],
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
    "target_tracker.json": [
        _YCS,
        {**_YJS, "description": "YJB Youth Justice Statistics 2024 to 2025, "
         "remand episodes (chapter 6)"},
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
    "suppression_audit.json": [
        {
            "description": "PRISM-R disclosure control audit, every suppression "
            "decision across the count-bearing outputs, generated by the build",
            "url": "",
            "reference_period": "applies to the outputs of this build",
            "publication_date": None,
            "retrieval_date": "2026-05-18",
        },
    ],
}

# Files listed in the manifest: the seven step outputs plus the suppression
# audit, which is written by the build's suppression stage, not by a step.
MANIFEST_OUTPUTS: tuple[str, ...] = PROCESSED_OUTPUTS + ("suppression_audit.json",)


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
# Disclosure suppression
# --------------------------------------------------------------------------
# Suppression is the final build stage. It runs after every step, so the
# ingest and RRI computation work on complete data and national totals
# reconcile; suppression is then applied to the published outputs. It is
# deterministic, so the build stays reproducible.
@dataclass(frozen=True)
class SuppressionPlan:
    """How disclosure suppression applies to one processed output.

    count_field   the field holding the count protected by rules 1 and 2
    group_fields  fields that define a suppression group, that is every
                  dimension except the one being protected
    id_fields     fields whose values form a unique cell id
    indicators    if set, only records with one of these indicator values
                  are in scope; None means every record
    """

    filename: str
    count_field: str
    group_fields: tuple[str, ...]
    id_fields: tuple[str, ...]
    indicators: tuple[str, ...] | None = None


SUPPRESSION_PLANS: tuple[SuppressionPlan, ...] = (
    SuppressionPlan(
        "remand_outcomes.json", "count",
        ("geo_id", "year", "breakdown", "remand_type"),
        ("geo_id", "year", "breakdown", "remand_type", "ethnicity", "sex", "age_band"),
    ),
    SuppressionPlan(
        "context_indicators.json", "value",
        ("geo_id", "year", "indicator", "breakdown"),
        ("geo_id", "year", "indicator", "breakdown", "ethnicity"),
        indicators=("lac_count", "arrest_count", "stop_search_rate"),
    ),
    SuppressionPlan(
        "custody_monthly.json", "count",
        ("month", "measure", "scope"),
        ("month", "measure", "scope", "category"),
    ),
    SuppressionPlan(
        "custody_episodes_ending.json", "count",
        ("year_ending_march", "ethnicity_group"),
        ("year_ending_march", "ethnicity_group", "legal_basis"),
    ),
    SuppressionPlan(
        "custody_episode_length.json", "value",
        ("year_ending_march", "ethnicity_group", "legal_basis"),
        ("year_ending_march", "ethnicity_group", "legal_basis", "indicator",
         "nights_band"),
        indicators=("episode_count",),
    ),
    SuppressionPlan(
        "rri.json", "events",
        ("geo_id", "decision_point", "provenance", "period_basis"),
        ("geo_id", "decision_point", "provenance", "period_basis", "ethnicity"),
    ),
)

# populations.json is not re-suppressed: its counts are ONS Census denominators,
# already subject to ONS disclosure control at source. The exclusion-rate and
# imd_score indicators carry no in-record count, so the count rules do not
# reach them; their rate and proportion values are released as published.


def suppress_records(records: list[dict], plan: SuppressionPlan) -> list[dict]:
    """Apply disclosure suppression to a records list, in place.

    A record on which a rule fires has its count field set to null and gains
    suppressed and suppression_rule fields. Records on which no rule fires are
    left untouched, so an output with no suppression is byte-identical to the
    unsuppressed build. Returns the audit entries.
    """
    scope = [
        i for i, record in enumerate(records)
        if plan.indicators is None or record.get("indicator") in plan.indicators
    ]
    cells: list[Cell] = []
    index_by_id: dict[str, int] = {}
    for i in scope:
        record = records[i]
        cell_id = "|".join(str(record.get(f)) for f in plan.id_fields)
        group = "|".join(str(record.get(f)) for f in plan.group_fields)
        source_suppressed = (
            record.get("disclosure_status") == "source_suppressed"
            or record.get("suppressed") is True
        )
        cells.append(Cell(
            cell_id=cell_id, group=group,
            count=record.get(plan.count_field),
            source_suppressed=source_suppressed,
        ))
        index_by_id[cell_id] = i
    result = apply_suppression(cells)
    for cell in result.cells:
        if not cell["suppressed"]:
            continue
        record = records[index_by_id[cell["cell_id"]]]
        record[plan.count_field] = None
        record["suppressed"] = True
        record["suppression_rule"] = cell["rule"]
    return [{**entry, "dataset": plan.filename} for entry in result.audit]


def _write_processed(path: Path, payload: dict) -> None:
    """Write a processed JSON file with the pipeline's standard formatting."""
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")


def suppress_outputs() -> dict:
    """Apply suppression to the count-bearing outputs and write the audit.

    Only sound immediately after a full build: the inputs must be freshly
    regenerated, unsuppressed outputs. Running it over already-suppressed
    files double-applies the rules, re-marking build-suppressed cells as
    inherited and cascading spurious secondary suppression, which is why
    main() calls it only when every step has just run.
    """
    audit: list[dict] = []
    by_dataset: dict[str, int] = {}
    for plan in SUPPRESSION_PLANS:
        path = PROCESSED_DIR / plan.filename
        if not path.exists():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        entries = suppress_records(payload["records"], plan)
        _write_processed(path, payload)
        audit.extend(entries)
        suppressed = sum(1 for e in entries if e["resulting_state"] == "suppressed")
        by_dataset[plan.filename] = suppressed
        if suppressed:
            log.warning("  suppression: %s, %d cells suppressed", plan.filename, suppressed)
        else:
            log.info("  suppression: %s, no cell suppressed", plan.filename)

    by_rule: dict[str, int] = {}
    for entry in audit:
        by_rule[entry["rule"]] = by_rule.get(entry["rule"], 0) + 1
    audit_payload = {
        "meta": {
            "dataset": "suppression_audit",
            "generated_by": "pipeline/build.py",
            "schema_note": (
                "One record per disclosure control decision, across every "
                "count-bearing output. rule is inherited, primary, secondary "
                "or rate-threshold; dataset names the output. The trail lets "
                "a reader see the rule applied, not just its effect. National "
                "figures rarely trigger suppression; sub-national cells do."
            ),
            "counts": {
                "decisions": len(audit),
                "by_rule": by_rule,
                "cells_suppressed_by_dataset": by_dataset,
            },
        },
        "records": sorted(
            audit,
            key=lambda a: (a["dataset"], a["group"], a["cell_id"] or "", a["rule"]),
        ),
    }
    _write_processed(SUPPRESSION_AUDIT, audit_payload)
    return audit_payload


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
    outputs = [file_entry(name) for name in MANIFEST_OUTPUTS
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
    parser.add_argument("--fetch", action="store_true",
                        help="run the fetch layer first; default is offline")
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
    if args.fetch:
        log.info("--fetch: running the fetch layer")
        fetch_result = subprocess.run(
            [sys.executable, str(PIPELINE_DIR / "fetch.py")],
            cwd=REPO_ROOT, capture_output=True, text=True,
        )
        for line in (fetch_result.stdout + fetch_result.stderr).splitlines():
            log.info("  %s", line)
        if fetch_result.returncode != 0:
            log.error("fetch layer failed; aborting before ingest")
            return 1
    else:
        log.info("offline build: using local data/raw/ files (run with "
                 "--fetch to refresh the fast-moving sources first)")
    if len(steps) != len(STEPS):
        log.warning("partial build: %d of %d steps; outputs of skipped steps "
                    "must already exist", len(steps), len(STEPS))

    exit_code, results = run_pipeline(steps)
    if exit_code == 0 and len(steps) == len(STEPS):
        log.info("applying disclosure suppression")
        audit = suppress_outputs()
        log.info("  suppression audit: %d decisions written to "
                 "suppression_audit.json", audit["meta"]["counts"]["decisions"])
    elif exit_code == 0:
        log.warning("partial build: disclosure suppression skipped; "
                    "run a full build to refresh the suppressed outputs")
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
