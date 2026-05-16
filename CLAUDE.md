# CLAUDE.md

Guidance for Claude Code when working in this repository. Read it at the start of every session.

## Project purpose

PRISM-R is an open tool for analysis of remand disproportionality in the youth justice system of England and Wales. It is produced by Oxon Advisory and hosted on Prevention Works (howpreventionworks.com).

PRISM-R makes the case that remand disproportionality is a prevention failure, and that a trans-disciplinary lens reveals patterns that siloed reporting hides. It is not a statistics portal. It is an argument made interactive, sitting alongside Peat and the Prevention Works community of practice.

The tool answers four questions in order: what is happening, where is it happening, why might it be happening, and what works. It is empirical. It shows co-occurrence, not causation. Causal or biographical-criminology framing belongs in the narrative and evidence layers, never in the analytic claims of the dashboard.

The tool is independent of government, of the Youth Justice Board, and of any commissioned client. All data is drawn from publicly available sources.

Authoritative scope, sprint plan, and acceptance criteria live in the v1 specification. This file summarises the parts needed to work day to day; the spec wins on any conflict.

## Architecture

The whole site is statically served. No database server, no per-request compute. The Python pipeline reads public source files and emits flat JSON for the front-end plus Parquet or CSV for download. The Astro site consumes that JSON.

```
data/raw/        public source files as downloaded, grouped by release
data/interim/    pipeline working files, not committed
data/processed/  emitted JSON consumed by the site
pipeline/        Python ingest and build scripts
site/            Astro static site (built in later sprints)
docs/            methods, data sources, disclosure control
tests/           pytest suite
```

## Data model

All data is flat JSON for the front-end, Parquet or CSV for download. Six entities.

### Geographies

One row per geographic unit. Fields: `geo_id` (stable internal id), `geo_name`, `geo_type` (`region` | `yot` | `police_force` | `la`), `parent_region`, `parent_force`, `ons_code`, `centroid_lat`, `centroid_lon`, `boundary_ref`. Three working resolutions: 9 English regions plus Wales, around 150 YOTs, 43 police force areas.

### Population denominators

One row per `geo_id` x `year` x `ethnicity` x `age_band` x `sex`. Fields add `population` (10 to 17 count) and `census_basis` (`2011` | `2021`).

### Remand outcomes

One row per `geo_id` x `year` x `ethnicity` x `age_band` x `sex` x `offence_band` x `remand_type`. Fields add `count` and `suppressed`.

### Post-remand outcomes

One row per `geo_id` x `year` x `ethnicity`. Fields: `remanded_n`, `custodial_sentence_n`, `non_custodial_sentence_n`, `acquittal_dismissed_n`. Drives the headline metric, the proportion of remanded children not receiving a custodial sentence.

### Context layer

One row per `geo_id` x `year` x `indicator` x `breakdown`. Indicators: `exclusion_rate`, `lac_rate`, `imd_score`, `child_poverty_rate`, `stop_search_rate`. `breakdown` is `overall` or `by_ethnicity`; `ethnicity` is null when `breakdown` is `overall`.

### Rate index

Pre-calculated Relative Rate Index per `geo_id` x `year` x `ethnicity` x `decision_point`. Decision points: `stop_search`, `arrest`, `charge`, `remand`, `custodial_sentence`. Fields: `rri`, `rri_lower_ci`, `rri_upper_ci`.

### Shared enumerations

- `ethnicity`: White, Black, Asian, Mixed, Other, Unknown.
- `age_band`: 10-11, 12-14, 15-17.
- `sex`: male, female.
- `offence_band`: violence, robbery, sexual, drugs, theft, public order, criminal damage, other.
- `remand_type`: bail, community_remand, rlaa, ydp.
- `year` is an integer, the year ending March.

## Disclosure control

These rules are non-negotiable and apply uniformly. They are described openly on the methods page. Full text in `docs/disclosure-control.md`; enforced in `pipeline/suppress.py`; verified in `tests/test_suppression.py`.

1. Counts below 6 are suppressed and shown as "<6, suppressed for disclosure control".
2. Secondary suppression applies where suppressing one cell would let another be back-calculated. Use standard ONS practice.
3. Rates are not shown where the denominator population in the relevant cell is below 100. Show "rate not shown, population too small".
4. Every suppression decision is logged in a methods-page audit trail.
5. Where the YJB has already suppressed a source value, propagate that suppression and flag it as inherited.

Never emit, infer, or reconstruct a suppressed value. Individual-level data is out of scope, always.

## Pipeline conventions

- Ingest scripts read from `data/raw/`, may stage in `data/interim/`, and emit to `data/processed/`.
- Scripts are idempotent: running twice produces byte-identical output.
- Every pipeline output must reproduce the published source national totals to the nearest unit. This is an acceptance criterion, not a nicety.
- JSON is written with sorted keys and a stable row order so diffs are meaningful.
- Tests live in `tests/` and run with `.venv/bin/python -m pytest`.
- Source provenance is recorded in `docs/data-sources.md` with retrieval date and version whenever a file is downloaded.

## Environment

- Pipeline dependencies are pinned in `requirements.txt`; the virtual environment is `.venv/`.
- The spec names Python 3.12 as the target runtime. This environment runs Python 3.14, because 3.12 was not installed on the build machine and every pinned wheel resolves cleanly on 3.14. If you later move to 3.12, recreate `.venv` and re-pin.
- Note that pandas is 3.x. Copy-on-write is the default; there is no `inplace` fallback to rely on.

## Working conventions

Editorial rules apply to code comments, error messages, placeholder text, commit messages, and all visible copy.

- UK English throughout: organisation, behaviour, analyse, programme, colour, centre.
- Sentence case in headings, not Title Case. "Risk and protective factors", not "Risk And Protective Factors".
- No em-dashes anywhere. Use commas, semicolons, colons, brackets, or a full stop.
- No clichéd LLM phrasing.
- Metric units. A4 for any printable asset.
- Verified facts only. If a statistic, attribution, or date is uncertain, verify it or mark it `[TO VERIFY]`. Never present an unverified figure as established.
- Stan Gilmour is referred to as "Stan Gilmour KPM FRSA" or "Mr Stan Gilmour", never as "Professor". His academic appointment is "Honorary Senior Research Fellow at the University of Exeter".

## Build order

The front-end is not started until the pipeline reproduces published national totals and that is confirmed. Current sprint: 1, the data pipeline core.
