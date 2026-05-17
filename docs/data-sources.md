# Data sources

Every source feeding PRISM-R, with retrieval date and version. This file is the provenance record; it is kept current as each ingest script is added.

## Tier 1: spine data

- YJB and MoJ Youth Justice Statistics 2024-25 supplementary tables, chapters 1, 3, 6, 7. https://www.gov.uk/government/statistics/youth-justice-statistics-2024-to-2025
- YJB local-level data tables published alongside the annual statistics.
- MoJ Ethnicity and the Criminal Justice System annual report, RRI tables.
- Home Office stop and search data, force level.

## Tier 2: contextual overlays

- DfE permanent and fixed-term exclusions by ethnicity and local authority.
- DfE children looked after statistics by local authority.
- DLUHC English Indices of Multiple Deprivation, latest release.
- ONS child population by local authority and ethnicity, 2021 Census.
- StatsWales equivalents for Welsh local authorities.

## Geography reference

- ONS lookup table for UK Authority Codes 2024 (FOI-2024-2008), published 20 May 2024. Provides the local authority register and the local authority to police force area mapping used by the crosswalk. https://www.ons.gov.uk/aboutus/transparencyandgovernance/freedomofinformationfoi/lookuptableforukauthoritycodes2024
- gov.uk youth justice services contact directory, used to confirm youth justice service structure. https://www.gov.uk/government/collections/youth-offending-team-contact-details

## Retrieval log

| source | file | retrieved | licence | notes |
|---|---|---|---|---|
| YJS 2024-25 supplementary tables | Ch 1 - Gateway to the youth justice system.xlsx | 2026-05-16 | OGL v3.0 | chapter 1 |
| YJS 2024-25 supplementary tables | Ch 3 - Children cautioned or sentenced.xlsx | 2026-05-16 | OGL v3.0 | chapter 3 |
| YJS 2024-25 supplementary tables | Ch 6 - Use of remand for children.xlsx | 2026-05-16 | OGL v3.0 | chapter 6, remand spine |
| YJS 2024-25 supplementary tables | Ch 7 - Children in youth custody.xlsx | 2026-05-16 | OGL v3.0 | chapter 7 |
| YJS 2024-25 local level open data tables | Children_Table.ods | 2026-05-16 | OGL v3.0 | youth justice service level |
| YJS 2024-25 local level open data tables | Offence_Table v2.ods | 2026-05-16 | OGL v3.0 | youth justice service level |
| YJS 2024-25 local level open data tables | Outcome_Table.ods | 2026-05-16 | OGL v3.0 | youth justice service level |
| ONS UK Authority Codes 2024 | uk_authority_codes_2024.xlsx | 2026-05-17 | OGL v3.0 | LA register and LA to police force lookup |
| MoJ Ethnicity and the CJS 2024 | A_Technical_Guide_to_Ethnicity_and_the_CJS_2024.pdf | 2026-05-17 | OGL v3.0 | RRI methodology reference |
| MoJ Ethnicity and the CJS 2024 | A_User_Guide_to_Ethnicity_and_the_CJS_2024.pdf | 2026-05-17 | OGL v3.0 | publication user guide |
| MoJ Ethnicity and the CJS 2024 | ch9_offence_analysis_2024.ods | 2026-05-17 | OGL v3.0 | Table 9.01, adult custodial sentencing RRI |
| MoJ Ethnicity and the CJS 2024 | ch5_defendants_tables_2024.ods | 2026-05-17 | OGL v3.0 | Table 5.17a, adult remand RRI |
| YJB Youth Justice Statistics 2024-25 | Ch 5 - Sentencing of children.xlsx | 2026-05-16 | OGL v3.0 | Table 5.8, child custodial sentencing RRI |
| ONS Census 2021, dataset RM032 | census2021_5cat_age_sex.csv and four further filter pulls | 2026-05-17 | OGL v3.0 | child population denominator; pulled via the ONS filter service. Full request specs, filter IDs, URLs and checksums in data/raw/ons-census-2021/filter_manifest.json |
| DfE Suspensions and permanent exclusions in England | exclusions_2023-24_alldata.zip (exc_characteristics.csv) | 2026-05-17 | OGL v3.0 | LA by ethnicity exclusion and suspension rates |
| DfE Children looked after in England including adoptions | cla_2025_alldata.zip (la_cla_on_31_march_by_characteristics.csv) | 2026-05-17 | OGL v3.0 | LA by ethnicity looked-after counts |
| StatsWales Children looked after on 31 March by ethnicity | welsh_cla_by_la_ethnicity.json | 2026-05-17 | OGL v3.0 | exported from stats.gov.wales |
| StatsWales Permanent and fixed-term exclusions from schools | welsh_exclusions_2023-24.ods | 2026-05-17 | OGL v3.0 | accompanying spreadsheet from the gov.wales release |

YJS files were downloaded from gov.uk. The Youth Justice Statistics 2024 to 2025 release was published on 29 January 2026. The original download archives (`supplementary_tables.zip`, `local_level_open_data_tables.zip`) are retained in `data/raw/yjb-2024-25/` as the canonical source.

## Release currency

Per the standing instruction, the most recent published release of each source is verified at source. Publication date, reference period and next expected release:

| Source | Latest release | Published | Reference period | Next expected |
|---|---|---|---|---|
| DfE suspensions and permanent exclusions | Academic year 2023/24 | 10 July 2025 | academic year 2023/24, full year | full 2024/25 later in 2026 |
| DfE children looked after in England | Reporting year 2025 | 26 November 2025 | year ending 31 March 2025 | November 2026 |
| StatsWales Welsh school exclusions | Sept 2023 to Aug 2024, provisional | November 2025 | academic year 2023/24 | revision or next year, to confirm |
| StatsWales Welsh children looked after | data to 2023-24 | updated 30 January 2026 | year ending 31 March 2024 | June 2026 |
| ONS Census 2021, RM032 | Census 2021 | 2023 | Census day, 21 March 2021 | next census, around 2031 |

Re-ingest flags: a termly DfE exclusions release (spring term 2024/25, published 30 April 2026) exists but is partial-year, so PRISM-R uses the latest full academic year; re-ingest when the full 2024/25 year is published. The Welsh children looked after update for the year ending March 2025 is expected in June 2026; re-ingest soon after.

### Known source issue

The `England_Wales` column in `Offence_Table v2.ods` contains stray "London" values where "England" is expected. The pipeline derives nation from the region column instead.
