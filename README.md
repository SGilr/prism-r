# PRISM-R

An open tool for analysis of remand disproportionality in the youth justice system of England and Wales.

PRISM-R makes the case that remand disproportionality is a prevention failure, and that a trans-disciplinary lens reveals patterns that siloed reporting hides. It is not a statistics portal. It is an argument made interactive, sitting alongside Peat and the Prevention Works community of practice.

The tool shows co-occurrence, not causation.

## Status

v1 build, started May 2026. The full specification, including scope, data model, disclosure control rules, and the sprint plan, is in [docs/prism-r-v1-spec.md](docs/prism-r-v1-spec.md). This repository currently holds the data pipeline; the Astro site is built in later sprints.

Sprints 1 and 2 are complete. The data pipeline is built: YJB remand and sentencing, ONS child population, DfE and StatsWales exclusions and looked-after children, Home Office stop and search and arrests, and English and Welsh child deprivation are all ingested, with Relative Rate Index computation and disclosure-control logic. `python pipeline/build.py` reproduces every processed output and writes a provenance manifest.

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
- `--only STEP` run a single step (`yjb`, `crosswalk`, `ons`, `dfe`, `home_office`, `imd`, `rri`)
- `--from STEP` start at a step and run every step after it
- `--skip-raw-fetch` use the local `data/raw/` files; this is the only v1 behaviour, as PRISM-R does not yet automate downloads

The pipeline needs the raw source files under `data/raw/`, which are not in the repository. See `docs/data-sources.md` for every source with its retrieval date.

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
