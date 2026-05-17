# Sprint 2 closure summary

Sprint 2 closed on 17 May 2026, tagged `v0.2.0-sprint-2`. It delivered the
suppression module, the Relative Rate Index computation, the context overlay
ingests (DfE and StatsWales exclusions and looked-after children, Home Office
stop and search and arrests, English and Welsh child deprivation) and the
build orchestrator.

## 1. Processed outputs (`data/processed/`)

| File | Records | Description |
|---|---|---|
| `geographies.json` | 208 | Geographic reference: 1 nation, 10 regions, 42 police forces, 155 YOTs |
| `geo_crosswalk.json` | 318 | One row per local authority, mapping LA to YOT and to police force |
| `remand_outcomes.json` | 64 | National remand episodes by ethnicity, year, remand type |
| `populations.json` | 9,452 | ONS Census 2021 child population (10-17) by LA, ethnicity, age band, sex |
| `ethnicity_crosswalk.json` | mappings | ONS Census and DfE school-census ethnicity rollups to the YJB 5 groups |
| `context_indicators.json` | 3,770 | Six indicators, see below |
| `rri.json` | 45 | Relative Rate Index cascade by ethnicity and provenance |
| `manifest.json` | provenance | Per-output checksum, size, record count and source provenance |

`context_indicators.json` by indicator: `lac_count` 1,062, `permanent_exclusion_rate`
943, `suspension_rate` 943, `imd_score` 318, `stop_search_rate` 252,
`arrest_count` 252.

## 2. Methodology decisions made in Sprint 2

Cross-referenced to `docs/methods.md`:

- **RRI computation**: child-specific RRIs computed from open data using the
  MoJ-recommended method; Wald log-ratio confidence intervals; three-year
  pooling for the small-count child custodial sentencing series.
  ("Relative Rate Index", "Pooling for small-count stability",
  "Confidence interval methodology")
- **The road-to-remand cascade**: `stop_search` and `arrest` decision points
  added to `rri.json`; four of the spec's five cascade stages populated,
  charge omitted as no open data supports it. ("The road-to-remand cascade")
- **Cascade findings**: recorded as empirical findings, not interpretation:
  divergent ethnic patterns (Black declining downstream, Asian rising), and
  disparity present upstream of the courts. ("What the cascade reveals")
- **Rate harmonisation**: English exclusion rates per 100, Welsh per 1,000,
  harmonised to `rate_per_100` canonical with source values preserved.
  ("Rate harmonisation")
- **Looked-after children**: carried as `lac_count`, a count not a rate,
  because no 0 to 17 ethnic denominator exists.
  ("Children looked after: counts rather than rates")
- **Welsh exclusions**: LA-level overall plus all-Wales by ethnicity, no
  cross-tabulation; documented gap; Chinese not folded into Welsh Asian.
  ("England-Wales methodological differences in context indicators")
- **Stop and search and arrests**: self-defined ethnicity for both, as the
  combined column collapses Mixed and Other; `stop_search_rate` per 1,000
  canonical; arrests as `arrest_count`; British Transport Police excluded;
  Metropolitan and City of London Police fold into `pf-london`.
  ("Stop and search and arrests")
- **Deprivation**: a child-focused income measure, not the overall index:
  IDACI for England, WIMD child income for Wales; parallel, deliberately
  un-harmonised scales; WIMD 2019 used as WIMD 2025 local-authority indicator
  data is not yet published.
  ("Deprivation: child income, parallel English and Welsh scales")
- **Co-writer merge**: `context_indicators.json` is co-written by three ingest
  scripts, each owning its indicator codes and preserving the others' records;
  order-independent.
- **Build orchestrator**: dependency-ordered execution, per-step validation
  gates, a provenance manifest with checksums.

## 3. TODOs carried into Sprint 3

- **Visualisation constraints** (flagged in `methods.md`): the pooled child
  custodial sentencing RRI chart must overlay the three single-year points;
  `lac_count` must be shown against child population, never as a bare count.
- **Methodology reviewer sign-off**: `methods.md` carries an explicit TODO
  that the confidence-interval method must be reviewed and signed off before
  launch.
- **Disclosure suppression not yet wired**: `suppress.py` is built and tested
  but applied to no output. Sprint 3 must wire it into the build, or the
  serving layer, and produce the suppression audit trail required by
  disclosure-control rule 4.
- **Spec reconciliation**: completed at Sprint 2 close; the v1 spec sections
  4.5, 4.6 and 8 now match the realised implementation.
- **Re-ingest flags** (in `data-sources.md`): WIMD 2025 local-authority
  income-by-age data when published; full DfE 2024/25 exclusions; Welsh
  looked-after children for the year ending March 2025, expected June 2026.
- **Hosting subdomain**: the PRISM-R subdomain root under howpreventionworks.com
  is still unconfirmed and needs settling before the front-end build.

## 4. Pipeline shape

Seven steps, run by `pipeline/build.py` in dependency order:

1. `ingest_yjb.py` writes `geographies.json`, `remand_outcomes.json`
2. `build_crosswalk.py` writes `geo_crosswalk.json` (needs `geographies.json`)
3. `ingest_ons.py` writes `populations.json`
4. `ingest_dfe.py` writes `ethnicity_crosswalk.json`, `context_indicators.json`;
   covers English and Welsh exclusions and looked-after children
5. `ingest_home_office.py` merges into `context_indicators.json`
6. `ingest_imd.py` merges into `context_indicators.json`
7. `compute_rri.py` writes `rri.json`

There is no separate Welsh ingest script: `ingest_dfe.py` handles both nations
because `context_indicators.json` is co-written by indicator code, and a second
writer owning the same codes would overwrite the first. The build reproduces
every processed output byte for byte.
