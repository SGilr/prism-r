# PRISM-R

An open tool for analysis of remand disproportionality in the youth justice system of England and Wales.

PRISM-R makes the case that remand disproportionality is a prevention failure, and that a trans-disciplinary lens reveals patterns that siloed reporting hides. It is not a statistics portal. It is an argument made interactive, sitting alongside Peat and the Prevention Works community of practice.

The tool shows co-occurrence, not causation.

## Status

v1 build, started May 2026. The full specification, including scope, data model, disclosure control rules, and the sprint plan, is in [docs/prism-r-v1-spec.md](docs/prism-r-v1-spec.md). This repository currently holds the data pipeline; the Astro site is built in later sprints.

Sprint 1 is complete: the YJB 2024-25 national remand data is ingested and the pipeline reproduces every published national total.

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

Run the YJB ingest:

```
.venv/bin/python pipeline/ingest_yjb.py
```

Run the tests:

```
.venv/bin/python -m pytest
```

## Owner

Oxon Advisory. Hosted on Prevention Works (howpreventionworks.com). Independent of government, of the Youth Justice Board, and of any commissioned client. All data is drawn from publicly available sources, listed in `docs/data-sources.md`.

## Licence

PRISM-R is dual-licensed.

- Code, meaning the pipeline and the site source, is under the MIT licence. See [LICENSE](LICENSE).
- Documentation and processed data, meaning the contents of `docs/` and `data/processed/`, are under the Creative Commons Attribution 4.0 International licence (CC BY 4.0). See [LICENSE-data](LICENSE-data).

In short: MIT for code, CC BY 4.0 for documentation and processed data.
