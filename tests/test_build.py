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

EXPECTED_ORDER = ["yjb", "crosswalk", "boundaries", "explorer_boundaries", "ycs", "ons", "dfe", "home_office", "imd", "rri", "target", "explorer", "csv_exports"]


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


def test_no_step_reads_suppression_controlled_data_too_early():
    """The ordering rule, derived from the step definitions themselves.

    A step reading a file that disclosure control rewrites must either
    produce an output the suppression stage also processes, or be marked
    after_suppression. Checked against SUPPRESSION_PLANS and each step's
    declared reads, so a step added later inherits the check without anyone
    remembering to extend a list.
    """
    assert build.suppression_ordering_issues() == []


def test_the_ordering_guard_catches_an_unmarked_derived_step():
    """The guard must fail on the shape of the 3 September 2026 defect: a
    step reading suppressed data, producing something suppression does not
    process, and not marked to run after the stage."""
    import dataclasses
    original = build.STEPS
    try:
        build.STEPS = tuple(
            dataclasses.replace(step, after_suppression=False)
            if step.name == "explorer" else step
            for step in original)
        issues = build.suppression_ordering_issues()
        assert any("explorer" in issue and "after_suppression" in issue
                   for issue in issues), issues
        # and the build refuses to run at all
        assert build.dependency_issues() != []
    finally:
        build.STEPS = original


def test_a_step_producing_suppressed_output_is_not_marked_after():
    """The converse error: a step marked after_suppression whose output the
    suppression stage processes would never actually be suppressed."""
    import dataclasses
    original = build.STEPS
    try:
        build.STEPS = tuple(
            dataclasses.replace(step, after_suppression=True)
            if step.name == "rri" else step
            for step in original)
        assert any("rri" in issue and "never be suppressed" in issue
                   for issue in build.suppression_ordering_issues())
    finally:
        build.STEPS = original


def test_declared_reads_are_real_outputs():
    """A typo in a step's reads would silently weaken the ordering check."""
    produced = set(build.PROCESSED_OUTPUTS)
    for step in build.STEPS:
        assert set(step.reads) <= produced, (step.name, set(step.reads) - produced)


def test_suppression_splits_the_planned_pipeline_last():
    """Every post-suppression step comes after every ordinary step, so the
    split in main() cannot reorder the dependency graph."""
    names = [s.name for s in build.planned_steps(None, None)]
    marked = [s.after_suppression for s in build.planned_steps(None, None)]
    first_post = marked.index(True) if True in marked else len(names)
    assert all(marked[i] for i in range(first_post, len(names))), (
        "post-suppression steps must be contiguous at the end of the plan")


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
    assert names == ["dfe", "home_office", "imd", "rri", "target", "explorer", "csv_exports"]


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
    files = {output["file"] for output in manifest["outputs"]}
    assert "data/processed/rri.json" in files
    assert "data/processed/context_indicators.json" in files


def test_committed_manifest_records_a_whole_build():
    """The committed record must describe every step, in order, all passing.

    A subset check would not do. On 4 September 2026 a failed build
    overwrote this file with the one step it had managed to run, and the
    outputs list still named every file on disk, so the result read as a
    valid manifest. Equality is what makes that visible.
    """
    manifest = json.loads(
        (REPO_ROOT / "data" / "processed" / "manifest.json").read_text("utf-8")
    )
    assert [s["name"] for s in manifest["steps"]] == EXPECTED_ORDER
    assert all(s["status"] == "ok" for s in manifest["steps"])
    assert manifest["meta"].get("build_complete") is not False


def test_only_a_complete_build_may_write_the_committed_manifest():
    """Both branches of the destination choice, without writing either file.

    The complete branch is otherwise exercised only by the slow smoke test,
    which CI deselects, so this is the only automated check that a whole
    build still writes the committed record.
    """
    assert build.manifest_destination(True) == build.MANIFEST
    assert build.manifest_destination(False) == build.MANIFEST_PARTIAL
    assert build.MANIFEST.name == "manifest.json"
    assert build.MANIFEST_PARTIAL != build.MANIFEST


def test_an_incomplete_build_leaves_the_committed_manifest_alone(tmp_path):
    """write_manifest(complete=False) writes the partial file and nothing else.

    This is the guard on the defect above: a run that fails, or one narrowed
    by --only or --from, must not touch data/processed/manifest.json.
    """
    before = build.MANIFEST.read_bytes()
    partial_existed = build.MANIFEST_PARTIAL.exists()
    try:
        one_step = [{
            "name": "yjb", "script": "ingest_yjb.py", "status": "ok",
            "duration_seconds": 0.0,
        }]
        manifest = build.write_manifest(one_step, complete=False)

        assert build.MANIFEST.read_bytes() == before, (
            "an incomplete build overwrote the committed provenance record"
        )
        assert build.MANIFEST_PARTIAL.exists()
        assert manifest["meta"]["build_complete"] is False
        written = json.loads(build.MANIFEST_PARTIAL.read_text("utf-8"))
        assert [s["name"] for s in written["steps"]] == ["yjb"]
    finally:
        if not partial_existed:
            build.MANIFEST_PARTIAL.unlink(missing_ok=True)


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


# --------------------------------------------------------------------------
# Cleaning
#
# clean-processed removed only data/processed/*.json for a long time, so the
# boundaries, explorer and csv subdirectories survived a "clean" rebuild.
# Stale outputs that look freshly built are worse than missing ones, so the
# generated list is derived from the outputs and held here.
# --------------------------------------------------------------------------
def test_generated_files_cover_every_manifest_output():
    """Anything the manifest describes must also be something clean removes."""
    assert set(build.MANIFEST_OUTPUTS) <= set(build.GENERATED_FILES)


def test_generated_files_include_the_build_artefacts():
    for name in ("manifest.json", "manifest.partial.json", "build.log"):
        assert name in build.GENERATED_FILES, name


def test_clean_would_remove_everything_present_in_a_built_tree():
    """The real guard against drift: after a build, every file under
    data/processed is either generated or the .gitkeep placeholder. A step
    that starts writing something new and does not declare it fails here,
    rather than quietly surviving the next clean."""
    processed = REPO_ROOT / "data" / "processed"
    present = {p.relative_to(processed).as_posix()
               for p in processed.rglob("*") if p.is_file()}
    undeclared = present - set(build.GENERATED_FILES) - {".gitkeep"}
    assert not undeclared, (
        f"these files survive a clean but nothing declares them: "
        f"{sorted(undeclared)}")


def test_generated_files_are_all_inside_the_processed_directory():
    """A path escaping data/processed would have clean deleting elsewhere."""
    for name in build.GENERATED_FILES:
        resolved = (build.PROCESSED_DIR / name).resolve()
        assert resolved.is_relative_to(build.PROCESSED_DIR.resolve()), name


def test_no_step_reads_the_manifest():
    """The manifest is written after every step, so a step that reads it
    cannot work in a from-scratch build.

    build_csv_exports.py did exactly that. It passed for weeks because a
    previous build had always left a manifest behind, and on CI because the
    manifest is committed and arrives with the checkout. It failed the first
    time data/processed was genuinely empty. Provenance now comes from
    build.PROVENANCE, the record the manifest itself is written from.
    """
    offenders = []
    for step in build.STEPS:
        source = (REPO_ROOT / "pipeline" / step.script).read_text("utf-8")
        for line in source.splitlines():
            stripped = line.strip()
            if stripped.startswith("#") or "manifest.json" not in stripped:
                continue
            # A mention inside a docstring or comment is fine; a load is not.
            if any(token in stripped for token in
                   ("_load(", "open(", "read_text(", "json.load")):
                offenders.append(f"{step.script}: {stripped}")
    assert not offenders, (
        "these steps read the manifest, which does not exist during a "
        "from-scratch build:\n" + "\n".join(offenders))


def test_manifest_is_not_a_declared_input_of_any_step():
    for step in build.STEPS:
        assert "manifest.json" not in step.reads, step.name
