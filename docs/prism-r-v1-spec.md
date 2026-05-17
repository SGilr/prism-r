# PRISM-R v1 Specification

**Project:** PRISM-R, an open tool for analysis of remand disproportionality in the youth justice system of England and Wales.
**Owner:** Stan Gilmour KPM FRSA, Oxon Advisory.
**Host:** Prevention Works (howpreventionworks.com), as a top-level section at `/prism-r` or subdomain `prism-r.howpreventionworks.com` (final hosting decision pending).
**Status:** Specification for v1 build, May 2026.
**Revision:** 2026-05-16, sub-national remand rescoped. Remand data stays at England and Wales level for v1; the sub-national explorer is built around the upstream drivers of remand. See sections 2 and 6.3.
**Reconciled:** 2026-05-17, at Sprint 2 close. Sections 4.5, 4.6 and 8 have been aligned with the realised implementation: the context-layer indicator codes, the rate-index decision points, and the pipeline file list now match what was built. See `docs/SPRINT_2_CLOSURE.md`.

---

## 1. Purpose

PRISM-R makes the case that remand disproportionality in the youth justice system is a prevention failure, and that a trans-disciplinary lens reveals patterns that siloed reporting hides. It is not a statistics portal. It is an argument made interactive, sitting alongside Peat and the Prevention Works community of practice as part of an emerging prevention informatics field.

The tool answers four questions in order:

1. What is happening? Headline disparity numbers, refreshed annually.
2. Where is it happening? Geographic patterns at region, YOT, and police force resolution.
3. Why might it be happening? Trans-disciplinary overlays of exclusions, looked-after rates, deprivation, and stop and search.
4. What works? Curated evidence layer pointing to pathfinders, accommodation alternatives, and prevention-informed responses.

The tool is empirical. It shows co-occurrence, not causation. The biographical criminology framing sits in the narrative and evidence layers, not in the analytic claims of the dashboard.

## 2. Scope

### In v1

- National picture for England and Wales, including remand.
- Geographic explorer at three resolutions: region (9 English regions plus Wales), YOT (around 150 areas), police force area (43 forces). At sub-national level the explorer covers the upstream drivers that pre-date the remand decision, not remand itself. See the scope note below.
- Cross-filtering by ethnicity, age band, sex, offence severity band, year.
- Comparison tool: side-by-side view of any two geographies.
- Trans-disciplinary overlay: child exclusions, looked-after rate, IMD score, child population by ethnicity, stop and search rate.
- Evidence and what works section.
- Methods and data sources page with full provenance.
- Download: every chart exports as PNG, underlying data as CSV.
- Annual refresh pipeline.

### Scope note: remand resolution

Remand data is held at England and Wales level for v1. The YJB publishes remand figures nationally only; its local-level open data tables cover children, proven offences, and cautions or sentences, not remand. YOT-level remand data is held by the YJB but not published openly.

The geographic explorer therefore works at two levels. The national picture shows remand directly. The sub-national explorer shows the road to remand: the upstream drivers that pre-date the remand decision, namely arrests, stop and search, school exclusions, looked-after rates, IMD, child population by ethnicity, and child poverty. The narrative framing for the sub-national explorer is the road to remand rather than remand itself.

Pursuing access to YOT-level remand data, so that remand can be shown sub-nationally, is a stated aim for v2. The methods page carries a "what we cannot yet show" note describing this gap openly.

### Deferred to v2

- Court-level data (Crown Court and magistrates' court).
- Sub-national remand resolution, subject to securing access to YOT-level remand data from the YJB.
- Trend forecasting or projection.
- User-defined custom areas combining multiple LAs.
- API for third-party consumption.
- Welsh-language interface.
- Time-series animation.

### Out of scope

- Individual-level data, ever.
- Predictive modelling at YOT level.
- Anything that could be construed as judging individual courts or magistrates.

## 3. Data sources

### Tier 1: spine data

- YJB and MoJ Youth Justice Statistics 2024-25 supplementary tables. Chapters 1 (overview), 3 (demographics), 6 (remand), 7 (children in custody). https://www.gov.uk/government/statistics/youth-justice-statistics-2024-to-2025
- YJB local-level data tables and local-level maps published alongside the annual statistics.
- MoJ Ethnicity and the Criminal Justice System annual report, RRI tables.
- Home Office stop and search data, force level.

### Tier 2: contextual overlays

- DfE permanent and fixed-term exclusions by ethnicity and local authority.
- DfE children looked after statistics by local authority.
- DLUHC English Indices of Multiple Deprivation, latest release.
- ONS child population by local authority and ethnicity, 2021 Census.
- StatsWales equivalents for Welsh local authorities.

### Tier 3: practice and evidence (curated content, not data)

- London Accommodation Pathfinder.
- West Midlands Addressing Ethnic Disparity Pathfinder.
- Islington PSR reform with adultification statements.
- HMIP 2023 remand thematic review.
- Howard League regional FOI analysis.
- Peer-reviewed evidence (Williams, Kent, Lammy and others) linked via Peat where appropriate.

## 4. Data model

All data is held as flat JSON for the front-end and as Parquet/CSV for download. No database server. No per-request compute. The whole site is statically served.

### 4.1 Geographies

One row per geographic unit:

| field | type | notes |
|---|---|---|
| geo_id | string | stable internal identifier |
| geo_name | string | display name |
| geo_type | enum | region \| yot \| police_force \| la |
| parent_region | string | parent region geo_id, null for regions |
| parent_force | string | parent police force geo_id where applicable |
| ons_code | string | official ONS code where one exists |
| centroid_lat | float | for map labelling |
| centroid_lon | float | for map labelling |
| boundary_ref | string | reference to TopoJSON feature |

### 4.2 Population denominators

One row per `geo_id` x `year` x `ethnicity` x `age_band` x `sex`:

| field | type | notes |
|---|---|---|
| geo_id | string | |
| year | int | year ending March |
| ethnicity | enum | White, Black, Asian, Mixed, Other, Unknown |
| age_band | enum | 10-11, 12-14, 15-17 |
| sex | enum | male, female |
| population | int | 10-17 population count |
| census_basis | enum | 2011, 2021 |

### 4.3 Remand outcomes

One row per `geo_id` x `year` x `ethnicity` x `age_band` x `sex` x `offence_band` x `remand_type`:

| field | type | notes |
|---|---|---|
| geo_id | string | |
| year | int | |
| ethnicity | enum | as above |
| age_band | enum | as above |
| sex | enum | |
| offence_band | enum | violence, robbery, sexual, drugs, theft, public order, criminal damage, other |
| remand_type | enum | bail, community_remand, rlaa, ydp |
| count | int | |
| suppressed | bool | true if below disclosure threshold |

### 4.4 Post-remand outcomes

One row per `geo_id` x `year` x `ethnicity`:

| field | type |
|---|---|
| geo_id | string |
| year | int |
| ethnicity | enum |
| remanded_n | int |
| custodial_sentence_n | int |
| non_custodial_sentence_n | int |
| acquittal_dismissed_n | int |

This drives the 62% headline metric at every geographic resolution where data permits.

### 4.5 Context layer

One row per `geo_id` x `year` x `indicator` x `breakdown`:

| field | type | notes |
|---|---|---|
| geo_id | string | |
| year | int | |
| indicator | enum | permanent_exclusion_rate, suspension_rate, lac_count, imd_score, stop_search_rate, arrest_count |
| breakdown | enum | overall, by_ethnicity |
| ethnicity | enum | null when breakdown = overall |
| value | float | |

Reconciled at Sprint 2 close. The realised indicator codes differ from the original draft. Permanent exclusions and suspensions are carried separately as `permanent_exclusion_rate` and `suspension_rate`, not a single `exclusion_rate`. Looked-after children and arrests are carried as counts, `lac_count` and `arrest_count`, not rates, because neither has a sound 0 to 17 ethnic denominator; the codes name what the figure is. `child_poverty_rate` from the original draft is not implemented in v1 and is deferred to v2. Rate indicators carry harmonised rate fields alongside `value`; `imd_score` carries a child income deprivation proportion. See `docs/methods.md` and `docs/SPRINT_2_CLOSURE.md`.

### 4.6 Rate index

Pre-calculated Relative Rate Index values per geography, year, ethnicity, decision point, with confidence intervals.

| field | type |
|---|---|
| geo_id | string |
| year | int |
| ethnicity | enum |
| decision_point | enum (stop_search, arrest, remand, custodial_sentence) |
| rri | float |
| rri_lower_ci | float |
| rri_upper_ci | float |

Reconciled at Sprint 2 close. The road-to-remand cascade has four decision points, not five. `charge` is out of scope for v1: no open data gives child charges by ethnicity at a usable granularity. It is a v2 candidate, dependent on a suitable charge dataset becoming available. The realised `rri.json` also carries `provenance`, `period_basis`, `ci_method`, `pooled` and `significance_flag` fields; see `docs/methods.md`.

## 5. Disclosure control rules

These rules are non-negotiable and apply uniformly across the tool. They are described openly on the methods page.

1. Cells with count below 6 are suppressed and displayed as "<6, suppressed for disclosure control".
2. Secondary suppression applies where suppression of one cell allows back-calculation of another. Use standard ONS practice.
3. Rates are not displayed where the denominator population is below 100 in the relevant cell. Display "rate not shown, population too small".
4. Every suppression decision is logged in a methods-page audit trail so users can see the rule, not just the consequence.
5. Where YJB has already suppressed a value in source data, propagate that suppression downstream and flag it as inherited.

## 6. Page architecture

Pages live under `/prism-r/` (or the chosen subdomain root).

### 6.1 Landing (`/prism-r`)

Hero panel with four headline numbers from the latest YJS publication:

- Black children share of remand population.
- Mixed children share of remand population.
- Asian and Other children share of remand population.
- Proportion of remanded children not receiving a custodial sentence.

Three sentence framing the prevention argument. Three entry points: National picture, Explore my area, See what works. Footer links to methods, downloads, about.

### 6.2 National picture (`/prism-r/national`)

The trans-disciplinary argument on one page. Six panels:

1. Remand population trend ten years, by ethnicity.
2. RRI cascade: stop and search to arrest to charge to remand to custodial sentence.
3. 62% non-custodial outcome by ethnicity.
4. Choropleth map showing rate variation.
5. Overlay panel: school exclusion rate alongside remand rate by ethnicity.
6. Time spent on remand by ethnicity.

### 6.3 Geographic explorer (`/prism-r/explore`)

The dashboard proper. At sub-national level the explorer shows the road to remand: the upstream drivers that pre-date the remand decision, namely arrests, stop and search, school exclusions, looked-after rates, IMD, child population by ethnicity, and child poverty. Remand itself is shown at England and Wales level only, because YOT-level remand data is not published openly. See section 2 and the methods page.

- Left rail: geography selector with toggle for region / YOT / police force.
- Filter bar: ethnicity, age band, sex, offence band, year range.
- Centre: choropleth map of the selected upstream driver.
- Right rail: selected area summary card.
- Below: synced charts that update on cross-filter.
- Persistent download button.

### 6.4 Comparison (`/prism-r/compare`)

Pick area A and area B. Side-by-side identical chart pairs. Difference column. Use case examples: West Midlands vs West Yorkshire; Lancashire Police vs Greater Manchester Police.

### 6.5 Trans-disciplinary overlay (`/prism-r/overlay`)

Choose a geography, choose two indicators (e.g. remand rate for Black children alongside exclusion rate for Black pupils), see them juxtaposed on a single map and scatter. Explicit text: showing co-occurrence not causation, with links to the evidence layer.

### 6.6 Evidence and what works (`/prism-r/evidence`)

Curated content cards, not data viz. One card each for:

- London Accommodation Pathfinder.
- West Midlands Ethnic Disparity Pathfinder.
- Islington PSR reform (adultification statements).
- Howard League regional findings.
- HMIP 2023 remand thematic.
- Biographical criminology framing.
- ABI evidence (Williams, Kent).

Each card: one-paragraph summary, key reference, link out. Where Peat has relevant evidence, deep-link.

### 6.7 Methods and data (`/prism-r/methods`)

Full provenance. Source files listed with last refresh date. Disclosure control rules. RRI calculation method. Denominator basis (2011 vs 2021 Census). Known limitations. A "what we cannot yet show" note covering data the tool does not hold, including sub-national remand. Citation guidance for academic use.

### 6.8 About (`/prism-r/about`)

Statement of purpose, prevention informatics framing, Oxon Advisory and HPW relationship, contact, feedback link. Explicit independence statement.

## 7. Technology stack

| layer | choice | reason |
|---|---|---|
| Site generator | Astro | Static-first, hydrates only interactive components, low maintenance |
| Charts | Observable Plot + D3 | Plot for simple charts, D3 for the map and cross-filtered dashboard |
| Boundaries | TopoJSON | ONS open boundaries at ultra-generalised resolution |
| Styling | Tailwind | Matches HPW house style; sentence-case headings, no Title Case |
| Data pipeline | Python (pandas, openpyxl, geopandas, topojson, numpy) | Reproducible, scriptable, well-supported for ONS data |
| Source control | GitHub | Public from launch, versioned data releases |
| Hosting | Cloudflare Pages | Static, fast, supports the page weight; subdomain prism-r.howpreventionworks.com |

Python 3.12 is the target runtime for the pipeline. If the developer's default is 3.14 and geopandas or topojson wheels are not yet available, create the venv against 3.12 explicitly.

## 8. Repository structure

```
prism-r/
├── README.md
├── CLAUDE.md
├── data/
│   ├── raw/
│   ├── interim/
│   └── processed/
├── pipeline/                  # listed in build order; build.py runs steps 1 to 7
│   ├── ingest_yjb.py           # step 1: geographies, remand outcomes
│   ├── build_crosswalk.py      # step 2: LA to YOT to police force crosswalk
│   ├── ingest_ons.py           # step 3: Census child population
│   ├── ingest_dfe.py           # step 4: English and Welsh exclusions and looked-after children
│   ├── ingest_home_office.py   # step 5: stop and search, arrests
│   ├── ingest_imd.py           # step 6: English IDACI and Welsh WIMD child deprivation
│   ├── compute_rri.py          # step 7: Relative Rate Index
│   ├── suppress.py             # disclosure control library
│   └── build.py                # orchestrator and manifest
├── site/
│   ├── astro.config.mjs
│   ├── src/
│   │   ├── pages/
│   │   ├── components/
│   │   ├── layouts/
│   │   └── lib/
│   └── public/
├── docs/
│   ├── methods.md
│   ├── data-sources.md
│   ├── disclosure-control.md
│   └── SPRINT_2_CLOSURE.md
└── tests/
    ├── test_pipeline.py
    ├── test_rri.py
    ├── test_suppression.py
    └── test_build.py
```

## 9. Sprint plan

| sprint | focus | sessions |
|---|---|---|
| 1 | Data pipeline core: ingest YJB tables, geographies, populations, first JSON. Validate by reproducing published national totals. | 2-3 |
| 2 | Suppression logic, RRI computation, ingest DfE and ONS overlay data. | 2 |
| 3 | Astro site shell, navigation, styling, landing page, national picture. | 3 |
| 4 | Geographic explorer (map, cross-filter), comparison view. | 4 |
| 5 | Overlay page, evidence cards, methods page, accessibility audit, performance audit, launch checklist. | 3 |

Total: roughly 14-15 focused sessions, 6-8 weeks elapsed.

## 10. Editorial and styling rules

- UK English throughout.
- No em-dashes; use commas, brackets, or sentence breaks.
- Sentence case in headings (not Title Case).
- Metric units, A4 for printable assets.
- The title "Professor" is not used for Stan in any biographical text. He is "Stan Gilmour KPM FRSA" or "Mr Stan Gilmour".
- Academic appointment is "Honorary Senior Research Fellow at the University of Exeter".
- HPW visual identity for the site shell; PRISM family typographic continuity where it makes sense.

## 11. Acceptance criteria for v1 launch

- All pipeline outputs reproduce the published YJB national totals to the nearest unit.
- All disclosure control rules pass automated tests in `tests/test_suppression.py`.
- All pages render under 2 seconds on a cold load on a mid-range mobile device.
- All charts are keyboard navigable and screen-reader accessible (WCAG 2.2 AA).
- Every chart and table is downloadable.
- Methods page lists every source with retrieval date and version.
- An external methodology review note appears on the methods page, signed.
- The GitHub repository is public, with versioned data releases tagged by YJS publication year.

## 12. Known risks and limitations

- Small numbers at YOT level: many cells will be suppressed. Handle openly.
- Census denominator change between 2011 and 2021. Flag explicitly per indicator.
- The tool shows co-occurrence between context indicators and remand. It does not claim causation.
- YJB publishes annually in late January; the tool refreshes within four weeks of publication.
- YJB does not comment on regional or local themes (their stated policy). PRISM-R fills that gap independently, which is a feature, but means the analytic responsibility sits with us.
- Sub-national remand data is not published openly by the YJB. v1 shows remand nationally and the upstream drivers sub-nationally. Securing YOT-level remand data is a v2 aim.

## 13. Independence statement (to appear on About page)

PRISM-R is produced by Oxon Advisory and hosted on Prevention Works. It is independent of government, of the Youth Justice Board, and of any commissioned client. It is funded by Oxon Advisory as a contribution to the prevention informatics field. All data is drawn from publicly available sources, listed on the methods page. The tool exists to inform debate, not to recommend specific policy positions on contested questions.
