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

YJS files were downloaded from gov.uk. The Youth Justice Statistics 2024 to 2025 release was published on 29 January 2026. The original download archives (`supplementary_tables.zip`, `local_level_open_data_tables.zip`) are retained in `data/raw/yjb-2024-25/` as the canonical source.

### Known source issue

The `England_Wales` column in `Offence_Table v2.ods` contains stray "London" values where "England" is expected. The pipeline derives nation from the region column instead.
