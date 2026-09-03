"""Tests for the pipeline orchestrator in pipeline/build.py.

Most tests are fast and check the dependency graph, step planning, the
validation gate and the manifest schema. One end-to-end smoke test runs the
whole pipeline twice and is marked slow; deselect it with -m "not slow".
"""

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from pipeline import build  # noqa: E402

EXPECTED_ORDER = ["yjb", "crosswalk", "boundaries", "explorer_boundaries", "ycs", "ons", "dfe", "home_office", "imd", "rri", "target", "explorer"]


# --------------------------------------------------------------------------
# Dependency graph
# --------------------------------------------------------------------------
def test_dependency_graph_is_acyclic_and_complete():
    assert build.dependency_issues() == []


def test_steps_are_listed_in_dependency_order():
    """Every step's dependencies appear before it, so the order is a valid
    topological sort and the graph is acyclic."""
    seen: set[str] = set()
    for step in build.STEPS:
        for dependency in step.depends_on:
            assert dependency in seen, (
                f"{step.name} depends on {dependency}, which runs later"
            )
        seen.add(step.name)


def test_every_manifest_output_is_produced_by_a_step():
    produced = {output for step in build.STEPS for output in step.produces}
    assert set(build.PROCESSED_OUTPUTS) == produced


# --------------------------------------------------------------------------
# Step planning, used by --dry-run, --from and --only
# --------------------------------------------------------------------------
def test_planned_steps_default_is_the_full_ordered_pipeline():
    assert [s.name for s in build.planned_steps(None, None)] == EXPECTED_ORDER


def test_planned_steps_from_starts_midway():
    names = [s.name for s in build.planned_steps(None, "dfe")]
    assert names == ["dfe", "home_office", "imd", "rri", "target", "explorer"]


def test_planned_steps_only_is_a_single_step():
    assert [s.name for s in build.planned_steps("imd", None)] == ["imd"]


def test_dry_run_exits_zero():
    assert build.main(["--dry-run"]) == 0


def test_unknown_step_name_is_rejected():
    assert build.main(["--only", "not-a-step"]) == 1


# --------------------------------------------------------------------------
# Failure handling
# --------------------------------------------------------------------------
def test_failing_step_halts_the_pipeline(monkeypatch):
    """When a step fails, no later step runs and the build reports failure."""
    calls: list[str] = []

    def fake_run_step(step):
        calls.append(step.name)
        failed = step.name == "crosswalk"
        return {
            "name": step.name,
            "script": f"pipeline/{step.script}",
            "status": "failed" if failed else "ok",
            "return_code": 1 if failed else 0,
            "duration_seconds": 0.0,
            "stdout": "",
            "stderr": "simulated failure" if failed else "",
        }

    monkeypatch.setattr(build, "run_step", fake_run_step)
    monkeypatch.setattr(build, "validate_output", lambda name: (True, f"{name}: ok"))

    exit_code, results = build.run_pipeline(list(build.STEPS))
    assert exit_code == 1
    assert calls == ["yjb", "crosswalk"]  # stopped at the failing step
    assert len(results) == 2


def test_validation_gate_halts_on_a_bad_output(monkeypatch):
    """A step that exits cleanly but produces an invalid output still halts."""
    monkeypatch.setattr(
        build, "run_step",
        lambda step: {
            "name": step.name, "script": f"pipeline/{step.script}",
            "status": "ok", "return_code": 0, "duration_seconds": 0.0,
            "stdout": "", "stderr": "",
        },
    )
    monkeypatch.setattr(
        build, "validate_output",
        lambda name: (False, f"{name}: simulated schema failure"),
    )
    exit_code, results = build.run_pipeline(list(build.STEPS))
    assert exit_code == 1
    assert len(results) == 1  # halted after the first step's failed gate


# --------------------------------------------------------------------------
# Manifest schema
# --------------------------------------------------------------------------
def test_manifest_entry_has_integrity_and_provenance_fields():
    entry = build.file_entry("rri.json")
    for key in ("file", "schema_version", "sha256", "bytes", "records",
                "generated_by", "sources"):
        assert key in entry
    assert entry["schema_version"] == "1.0.0"
    assert len(entry["sha256"]) == 64
    assert entry["sources"], "every output must carry at least one source"
    for source in entry["sources"]:
        for key in ("description", "url", "reference_period",
                    "publication_date", "retrieval_date"):
            assert key in source


def test_committed_manifest_is_well_formed():
    manifest = json.loads(
        (REPO_ROOT / "data" / "processed" / "manifest.json").read_text("utf-8")
    )
    assert manifest["meta"]["dataset"] == "build_manifest"
    assert {s["name"] for s in manifest["steps"]} <= set(EXPECTED_ORDER)
    files = {output["file"] for output in manifest["outputs"]}
    assert "data/processed/rri.json" in files
    assert "data/processed/context_indicators.json" in files


# --------------------------------------------------------------------------
# End-to-end smoke test: a real build, run twice, must be idempotent
# --------------------------------------------------------------------------
@pytest.mark.slow
def test_smoke_full_build_is_idempotent():
    """Run the whole pipeline twice; every processed output must be
    byte-identical between the two runs. Slow: a real build, not a mock."""
    def build_once() -> None:
        result = subprocess.run(
            [sys.executable, "pipeline/build.py"],
            cwd=REPO_ROOT, capture_output=True, text=True,
        )
        assert result.returncode == 0, result.stdout + result.stderr

    def digests() -> dict[str, str]:
        return {
            name: hashlib.sha256(
                (REPO_ROOT / "data" / "processed" / name).read_bytes()
            ).hexdigest()
            for name in build.PROCESSED_OUTPUTS
        }

    build_once()
    first = digests()
    build_once()
    second = digests()
    assert first == second
