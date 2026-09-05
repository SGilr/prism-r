# PRISM-R

[![CI](https://github.com/SGilr/prism-r/actions/workflows/ci.yml/badge.svg)](https://github.com/SGilr/prism-r/actions/workflows/ci.yml)

An open tool for analysis of remand disproportionality in the youth justice system of England and Wales.

PRISM-R makes the case that remand disproportionality is a prevention failure, and that a trans-disciplinary lens reveals patterns that siloed reporting hides. It is not a statistics portal. It is an argument made interactive, sitting alongside Peat and the Prevention Works community of practice.

The tool shows co-occurrence, not causation.

## Status

v1 build, started May 2026. The full specification, including scope, data model, disclosure control rules, and the sprint plan, is in [docs/prism-r-v1-spec.md](docs/prism-r-v1-spec.md).

The site is live at [prism-r.howpreventionworks.com](https://prism-r.howpreventionworks.com): the national road-to-remand cascade, a force-level stop-and-search choropleth, a Lambeth worked example, and the White Paper remand target tracker, which follows the youth estate remand population monthly against the 25% reduction commitment of 18 May 2026 (see [docs/target-metric.md](docs/target-metric.md)). The pipeline ingests YJB remand and sentencing, the YCS monthly custody report, ONS child population, DfE and StatsWales exclusions and looked-after children, Home Office stop and search and arrests, and English and Welsh child deprivation, with Relative Rate Index computation and disclosure control throughout. `python pipeline/build.py` reproduces every processed output byte for byte and writes a provenance manifest. The geographic explorer and the launch audits are still to come.

## Repository layout

```
prism-r/
  data/        raw downloads, interim working files, processed JSON
  pipeline/    Python ingest and build scripts
  site/        Astro static site (later sprints)
  docs/        methods, data sources, disclosure control
  tests/       pytest suite
```

## Pipeline setup

```
python3.14 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## Reproducing the pipeline

`pipeline/build.py` is the canonical entry point. It runs every ingest and compute step in dependency order, validates each output, and writes the build manifest:

```
make build              # or: .venv/bin/python pipeline/build.py
```

This regenerates the seven JSON files in `data/processed/` and writes `data/processed/manifest.json`, a provenance record carrying, for each output, a SHA-256 checksum, byte size, record count, and the source description, URL, reference period and publication date. The processed outputs are deterministic: a second build reproduces them byte for byte.

`build.py` flags:

- `--dry-run` print the planned step order and exit
- `--only STEP` run a single step (`yjb`, `crosswalk`, `boundaries`, `ycs`, `ons`, `dfe`, `home_office`, `imd`, `rri`, `target`)
- `--from STEP` start at a step and run every step after it
- `--fetch` run the fetch layer first, refreshing the fast-moving sources; the default stays offline

The raw source files under `data/raw/` are not in the repository; they are published as a release asset. Download the latest `raw-data-*` release from [the releases page](https://github.com/SGilr/prism-r/releases), unpack the archive at the repository root (it expands into `data/raw/`), and the pipeline is fully reproducible. `RAW_BUNDLE.md` inside the archive lists every file with its source URL, retrieval date, SHA-256 and licence. See `docs/data-sources.md` for the retrieval log.

The fast-moving sources refresh automatically: `python pipeline/build.py --fetch` brings the YCS monthly report, the DfE exclusions release and the annual Youth Justice Statistics up to date before building, and a scheduled workflow does the same on the 15th of each month, opening a pull request when the data changes. When a manual source (ONS Census, IMD, Home Office, StatsWales) is refreshed locally, the procedure is: re-run the build, run `python pipeline/make_raw_bundle.py` and publish the dated release it prints, then note the refresh in `docs/data-sources.md`. Each cut is a new release; a published bundle is never rewritten in place, because readers cite it to verify the pipeline against its inputs.

Three workflows guard this. `ci.yml` runs the fast tests on every push and pull request. `verify.yml` runs weekly, and whenever a raw-data release is published, downloading the newest bundle and building from it offline: the result must reproduce the committed `data/processed/` byte for byte, which is the reproducibility claim tested rather than asserted. `refresh.yml` runs monthly, building with `--fetch` and opening a pull request when a source has published new data.

Run the tests:

```
make test               # full suite, including the end-to-end smoke test
make test-fast          # skips the slow smoke test
```

`make clean-processed` removes every generated file in `data/processed/`; `make build` regenerates them.

## Owner

Oxon Advisory. Hosted on Prevention Works (howpreventionworks.com). Independent of government, of the Youth Justice Board, and of any commissioned client. All data is drawn from publicly available sources, listed in `docs/data-sources.md`.

## Licence

PRISM-R is dual-licensed.

- Code, meaning the pipeline and the site source, is under the MIT licence. See [LICENSE](LICENSE).
- Documentation and processed data, meaning the contents of `docs/` and `data/processed/`, are under the Creative Commons Attribution 4.0 International licence (CC BY 4.0). See [LICENSE-data](LICENSE-data).

In short: MIT for code, CC BY 4.0 for documentation and processed data.
