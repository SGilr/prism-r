# Methods and data

This page records how PRISM-R is built so that every figure can be traced to a public source. It is a working draft; it is completed across sprints 2 to 5 and published on the methods page of the site.

## Source files

Each source is listed with its retrieval date and version. See [data-sources.md](data-sources.md).

## Remand type partition

PRISM-R reports four remand types that are mutually exclusive and together sum to total remand episodes: bail, community_remand, rlaa, and ydp.

This differs from the YJB supplementary tables. The YJB groups Bail Supervision and Support, ISS Bail, and Remand to Local Authority Accommodation together under "community remand with intervention". PRISM-R keeps Remand to Local Authority Accommodation as its own type, rlaa, so community_remand here covers only Bail Supervision and Support plus ISS Bail. A user comparing PRISM-R figures to YJB Table 6.1 should note this: PRISM-R community_remand plus rlaa equals the YJB "community remand with intervention" total. bail and ydp match the YJB categories directly.

## What we cannot yet show

Remand data in v1 is held at England and Wales level only. The YJB publishes remand figures nationally; its local-level open data tables cover children, proven offences, and cautions or sentences, not remand. YOT-level remand data is held by the YJB but is not published openly.

PRISM-R therefore shows remand directly in the national picture, and at sub-national level shows the upstream drivers that pre-date the remand decision: the road to remand. Securing access to YOT-level remand data, so that remand can be shown sub-nationally, is a stated aim for v2.

The monthly remand tracker inherits a further limit: the Youth Custody Service monthly tables are one-dimensional, so the remand stock cannot be shown by age, ethnicity or region of youth justice service. The tracked stock is the whole youth secure estate, including the small number aged 18 who remain in the youth estate, and the ethnic composition published alongside it is the whole custody population, clearly labelled as such.

## Tracking the target

The Youth Justice White Paper Cutting Youth Crime. Changing Young Lives. (MoJ, 18 May 2026) commits to reducing custodial remand for children by 25% over this Parliament. The White Paper does not publish an operational definition, so PRISM-R tracks both readings and states which is which; the full definition is in [target-metric.md](target-metric.md).

The headline tracker is the stock: the youth secure estate remand population from the monthly Youth Custody Service report, presented as a trailing 12-month rolling average to remove seasonality, with the full series from April 2015 so the pre-commitment trend is visible. The baseline is the mean of the twelve monthly values April 2024 to March 2025, 215.75; the target line is 75% of that, 161.8. The accountable measure is the flow: remands to youth detention accommodation from Youth Justice Statistics chapter 6, baseline 988 in the year ending March 2025, target 741 or fewer. The rolling average had already fallen 16.1% between March 2025 and May 2026, before any White Paper effect could operate; progress claimed against the baseline must be read against that pre-existing trend.

Two markers anchor the series. February 2026 is the month cited to the Justice Committee on 18 May 2026: the published estate total was 412 and the published remand figure 149, a 36.2% share. The "about 185" remand figure quoted in that evidence applied the annual 44% remand share to the estate total rather than the published February remand count. The second marker is the White Paper's publication date itself.

The tracker is computed by `pipeline/compute_target.py` into `data/processed/target_tracker.json`, refreshed monthly when the YCS report is ingested; the latest month is provisional and is overwritten at the following ingest.

## Remand duration

The remand stock is the product of the flow and the duration of each remand, so duration is the third leg of the target's equity condition: a reduction in the stock achieved by shortening remands is assessed for whether the shortening is equal across ethnic groups.

YCS table 3.4 gives the length of legal-basis episodes ending in each year by ethnicity. The published ethnicity split is binary, ethnic minority groups against White including white minorities; PRISM-R carries it as published (`ethnicity_basis: "binary"`) and does not map it onto the YJB five groups. The measure counts episodes ending in the year, not children on remand, and makes no adjustment for offence mix or court tier. On that basis the median remand episode for children from ethnic minority groups has been longer than for White children in every year since the series begins in 2019: 74 nights against 40.5 in the year ending March 2025, and 70 against 48 in the provisional 2025-26 year.

HMI Prisons' thematic review Children on short-term remand (May 2026) reports 216 children on remand in YOIs and STCs. That figure cannot be reconciled from the published YCS tables: table 1.8 gives sector by month for the whole population only, with no legal-basis cross, and the whole-estate remand stock at March 2025 was 199, below 216, so the HMIP figure is on a different basis. It is recorded here so the difference is visible, not treated as an inconsistency.

## Geography crosswalk

`data/processed/geo_crosswalk.json` maps every local authority in England and Wales to its parent youth justice service (YOT) and its parent police force. It is built by `pipeline/build_crosswalk.py`.

The local authority register and the local authority to police force mapping come from the ONS lookup table for UK Authority Codes 2024. The ONS code (E06, E07, E08, E09, W06) is the canonical local authority identifier. There are 318 local authorities: 296 in England and 22 in Wales.

The figure of 296 English authorities is lower than older counts of around 320 because of local government reorganisation since 2021. Northamptonshire was replaced by two unitary authorities in 2021. North Yorkshire, Somerset, and Cumbria, the last now Cumberland and Westmorland and Furness, were reorganised into unitary authorities in 2023. The crosswalk uses the 2024 authority geography throughout.

YOTs operate at upper-tier authority level, so each local authority is joined to a YOT through its ONS upper-tier authority. 275 of 318 local authorities match a YOT of the same name. The rest are partnership YOTs covering several authorities (22 authorities), cosmetic name variants (4), or derived assignments (17). The derived assignments for West Mercia, Northamptonshire, and Rutland were confirmed against the gov.uk youth justice services directory. The assignment of the Isles of Scilly to the Cornwall YOT is an assumption, not a confirmed mapping; the Isles of Scilly child population is immaterial.

No youth justice service spans more than one police force. Every YOT's constituent authorities sit within a single force.

### Gwynedd duplicate

The YJB local-level tables spell one Welsh service two ways, "Gwynedd & Ynys Mon" and "Gwynedd Mon", across their three files. Sprint 1 therefore produced two YOT records for a single service. Both spellings are now canonicalised to "Gwynedd and Ynys Môn", the spelling used in the gov.uk youth justice services directory, so the service appears once. geographies.json holds 155 youth justice services.

### Naming convention

Geography names use the English form, following YJB convention. The Welsh-language forms of Welsh authority and service names are deferred to v2. The one exception is the Gwynedd and Ynys Môn service, where the YJB's own published spelling is mirrored exactly.

## Relative Rate Index

The Relative Rate Index (RRI) compares the rate at which an ethnic group experiences an outcome with the rate for the White baseline group:

    RRI = (event rate for the group) / (event rate for the White group)

A value of 1 is parity. Above 1, the group is more likely to experience the outcome; below 1, less likely. The method was recommended in the Lammy Review (2017) and is used by the Ministry of Justice in Statistics on Ethnicity and the Criminal Justice System. It is computed by `pipeline/compute_rri.py` and written to `data/processed/rri.json`.

PRISM-R holds six RRI series across four decision points:

- Adult custodial sentencing and adult remand, `provenance: "moj_published"`. These are adopted verbatim from MoJ tables 9.01 and 5.17a. See "Reproducibility of MoJ-published RRIs" below.
- Child custodial sentencing and child remand, `provenance: "prism_r_derived"`. These are computed by PRISM-R.
- Child stop and search and child arrests, `provenance: "prism_r_derived"`. These are computed by PRISM-R from Home Office data. See "The road-to-remand cascade" below.

PRISM-R is therefore producing a child-specific RRI that does not exist in published official statistics. It is computed transparently from open data, applying the MoJ-recommended methodology to children specifically. Child custodial sentencing uses YJB Table 5.8, children sentenced for indictable offences by ethnicity and sentence type. Child remand uses YJB Table 6.1: the rate is the proportion of children subject to a remand decision who are remanded to youth detention accommodation, that is custodial remand.

The adult rows are calendar year 2024, as MoJ publishes them. The child youth-justice rows are the year ending March 2025, the latest YJB year. The stop and search and arrest rows are also the year ending March 2025, the latest Home Office year. These period bases are recorded in the `rri.json` meta block.

### The road-to-remand cascade

Spec section 6.2 frames the national picture as a cascade: stop and search, then arrest, then charge, then remand, then custodial sentence. Each stage is a point at which disproportionality can enter or compound. PRISM-R populates four of the five stages. Charge is omitted: no open data gives child charges by ethnicity at a usable granularity.

The stop and search and arrest RRIs differ from the youth-justice RRIs in their denominator. Custodial sentencing and remand are rates within the justice system: the denominator is a count of children already at that stage, for example children sentenced. Stop and search and arrests have no such prior stage, so the denominator is the resident child population aged 10 to 17 from the 2021 Census. The RRI is then the population-based event rate for an ethnic group divided by that for White children. This is the same denominator basis the Home Office itself uses for its published stop and search disparity figures.

The national event counts are summed from the by-ethnicity records in `context_indicators.json`; the population denominator is summed from `populations.json`. Because these counts run to thousands, the Wald confidence intervals are tight, narrower than those on the small-count youth-justice RRIs.

Spec section 4.6 will be revised after Task 3 to reflect what PRISM-R actually does: applying the MoJ-recommended methodology to youth-specific data and decision points, with explicit provenance labelling.

## What the cascade reveals

The cascade shows that the ethnic groups do not follow a single pattern across the decision points. For Black children the relative rate index is highest at stop and search, 2.40, and is lower at the court stages, 1.92 at remand and 1.59 at pooled custodial sentencing: the measured disparity is largest at the first point of contact. For Asian children the pattern runs the other way, from 0.60 at stop and search and 0.52 at arrest, both below parity, to 1.51 at remand and 1.38 at custodial sentencing. These are distinct empirical findings and PRISM-R reports them as such; they should not be merged into a single account of disproportionality.

Across the four populated stages, measurable disparity is present at stop and search and arrest for Black and Mixed children, before any court involvement. The disparity observed at remand is therefore not created wholly at the court stage; a substantial part of it is already present in the policing decisions upstream of the courts. On PRISM-R's figures the cascade locates a large share of the measured racial disparity upstream of remand, while also showing that the court stages are not themselves free of disparity.

## Pooling for small-count stability

The YJB immediate-custody counts for children by ethnicity are small enough that single-year RRIs are statistically fragile, with confidence intervals that typically cross 1 and point estimates that swing year to year. The Black single-year RRI, for example, runs 1.52, 2.57 and 0.91 across the years ending March 2023, 2024 and 2025, the last driven by a fall in the count from 86 to 38.

PRISM-R therefore presents the child custodial sentencing RRI as a three-year pooled estimate, counts summed across the years ending March 2023, 2024 and 2025, as its primary figure. Single-year values are retained in `rri.json` for inspection, marked `pooled: false`. This follows standard practice for small-count disproportionality analysis. The child remand RRI is not pooled: those counts are stable and the single-year confidence intervals are tight.

v1 visualisation requirement, for Sprint 3: the chart of the pooled child custodial sentencing RRI must show the pooled estimate together with the three single-year points overlaid, so a reader sees the underlying instability rather than a smoothed-over headline.

## Reporting periods

MoJ and YJB use different reporting calendars. The Criminal Justice Statistics Quarterly, the source of the adult RRIs, reports by calendar year. Youth Justice Statistics, the source of the child RRIs, reports by financial year, the year ending March.

PRISM-R does not force one calendar onto the other. The adult `moj_published` rows are calendar year 2024; the child `prism_r_derived` rows are years ending March. Each row records its `period_basis`. This difference should be borne in mind when comparing an adult value with a child value: they are close in time but not the same period.

## Confidence interval methodology

PRISM-R reports a 95% confidence interval for every `prism_r_derived` RRI. The interval is the Wald interval on the log of the rate ratio:

    SE(ln RRI) = sqrt(1/a + 1/b - 1/A - 1/B)
    95% CI     = exp( ln(RRI) plus or minus 1.96 x SE(ln RRI) )

where a and A are the event count and total for the group, and b and B those for the White baseline. This is the standard interval for a ratio of rates in epidemiology and public health. It is cited to Altman, Machin, Bryant and Gardner, Statistics with Confidence, 2nd ed., BMJ Books, 2000.

Two points of method:

1. MoJ uses p-value-based significance flags rather than confidence intervals. PRISM-R adopts confidence intervals because they convey magnitude and uncertainty together in a single visual, whereas a p-value flag is binary. Both are valid; confidence intervals are the more informative choice for a public-facing tool. MoJ's flag is still carried, on the `moj_published` rows, in the `significance_flag` field.

2. The Wald log-ratio interval is unreliable when any underlying count is small, below about 5. PRISM-R suppresses cells below 6, so this is largely a non-issue, but it is flagged honestly: intervals computed near the suppression boundary will be wide and may extend implausibly. Exact methods, such as the Wilson or Fisher interval, are deferred to v2.

3. Ethnic groups with small underlying populations, the "Other" group in particular and at times "Mixed", carry wider confidence intervals as a structural feature of disaggregation, not a flaw in the analysis: a smaller denominator gives a larger standard error. Such results should be read as less precise, not less real. The pooled "Other" child custodial sentencing RRI is a case in point: 1.47 with a 95% interval of 1.01 to 2.14. Its lower bound sits just above 1, so it is significant but only marginally; it should be presented as such, not treated as equivalent to a tighter finding.

TODO, methodology reviewer: the confidence interval method above is to be reviewed and signed off before launch.

## Reproducibility of MoJ-published RRIs

The Ministry of Justice publishes RRI values in tables 9.01 (custodial sentencing) and 5.17a (remand in custody) of Statistics on Ethnicity and the Criminal Justice System 2024. It does not publish the underlying counts: the numbers of defendants sentenced, and sentenced to immediate custody, by ethnic group and offence type.

Those counts are derived from the Court Proceedings Database, which is not public. The published Criminal Justice Statistics outcomes tools hold the data only inside an embedded analytical model that is not machine-readable with an open toolchain, and the Ethnicity Facts and Figures service has not been refreshed past 2017.

End-to-end reproduction of the MoJ RRIs from public sources is therefore not possible. PRISM-R adopts the published values as reference, cited verbatim, with `provenance: "moj_published"`.

This is not a criticism of MoJ practice. It is a description of the disclosure environment: aggregate RRIs can be released where the underlying record-level data cannot. It explains why two of the six RRI series in `rri.json` carry `provenance: "moj_published"` rather than `prism_r_derived`, and why those two carry no confidence interval, since the interval needs the same withheld counts.

## Denominator basis

Population denominators use the 2021 Census basis, recorded per record in the `census_basis` field. The change from the 2011 Census affects comparability and is flagged where any 2011-based figure is used.

## Disclosure-aware coverage of LA-level population data

`data/processed/populations.json` is the child population denominator, built by `pipeline/ingest_ons.py` from ONS Census 2021 dataset RM032, pulled through the ONS filter service. Three filter requests produced the data: a 5-category ethnic group by sex by single-year age cube for all local authorities; a sex-aggregated top-up for authorities the first cube did not release; and a 20-category detailed cube retained as a raw audit artefact, not used in the pipeline. The exact requests, filter IDs, download URLs and checksums are recorded in `data/raw/ons-census-2021/filter_manifest.json`, so the artefacts are reproducible by anyone holding that manifest.

ONS disclosure control will not release a fine ethnicity-by-age cross-tabulation for the smallest authorities. Coverage therefore comes in three tiers, recorded per LA in a `disclosure_status` field:

- `full`, 314 LAs: ethnicity by age band by sex.
- `sex_aggregated`, 2 LAs (Melton and Merthyr Tydfil): ethnicity by age band, with the sex dimension suppressed by ONS.
- `unavailable`, 2 LAs (Isles of Scilly and City of London): ONS released no ethnicity-by-age cross-tabulation at any granularity attempted.

The national total reconciles against a separate national-level filter pull, which carries no disclosure restriction. The national figure is 5,635,559; the sum across the 316 covered LAs is 5,635,156; the gap of 403 is consistent, within cell-key perturbation noise, with the 409 children the two unavailable LAs hold according to an age-only ONS table. Those two LAs together are under 0.05% of the England and Wales population aged 10 to 17.

PRISM-R declines to model figures for the two unavailable LAs. A rate calculation for them returns null, with a documented reason, rather than a manufactured value. This is not a shortcoming to apologise for: ONS disclosure control is doing what it should, and PRISM-R's task is to respect that boundary visibly rather than paper over it.

## Geographic vintages

PRISM-R uses 2023 local authority boundaries throughout, via the ONS `ltla23` area type, aligned with the geography crosswalk built in Task 1. Census 2021 was collected on Census day, 21 March 2021; ONS re-publishes it through the filter service aggregated to several boundary vintages, including 2023. The population figures are therefore 2021 observations presented on 2023 boundaries. The two are distinct and should not be conflated: the count is from 2021, the geography is 2023.

## Context indicators

`data/processed/context_indicators.json` holds the upstream drivers for the sub-national explorer, built by `pipeline/ingest_dfe.py`: `permanent_exclusion_rate`, `suspension_rate` and `lac_count`. Exclusions and looked-after data are reported at upper-tier local authority level (around 153 authorities in England, 22 in Wales), not the 318 districts of `populations.json`; `geo_id` is the upper-tier authority.

### Rate harmonisation

English DfE exclusion rates are per 100 pupils; Welsh rates are per 1,000. Every rate record carries `rate_per_100` (the canonical, harmonised value used in all calculations and visualisations), `source_rate` (the original published value) and `source_rate_base` (100 for England, 1,000 for Wales). The original value is preserved alongside the harmonised one so any figure can be verified against its source.

### England-Wales methodological differences in context indicators

- **Rate base**: England per 100, Wales per 1,000, harmonised to per-100 as above.
- **Terminology**: Welsh "fixed-term exclusions" are the equivalent of English "suspensions"; PRISM-R uses `suspension_rate` for both.
- **No LA by ethnicity for Welsh exclusions**: DfE publishes English exclusions crossed by local authority and ethnicity. StatsWales publishes Welsh exclusions by local authority and by ethnicity in two separate tables, with no cross-tabulation. Welsh exclusion rows are therefore either local-authority level for all ethnicities (`breakdown: overall`) or all-Wales by ethnicity (`geo_id: rgn-wales`, `breakdown: by_ethnicity`). There is no Welsh LA by ethnicity exclusion figure. This is a documented gap, not an omission.
- **Welsh "Chinese"**: Welsh exclusion statistics report Chinese separately from Asian. The ONS and YJB schemes place Chinese within Asian, but the Welsh exclusion table is a rate table with no pupil denominator, so the two cannot be exactly recombined. The Welsh all-Wales Asian exclusion rate is the Welsh "Asian" category alone; Chinese, a small group, is not folded in.
- **Welsh looked-after rounding**: Welsh looked-after counts are rounded to the nearest 5, with counts below 5 suppressed. English counts are not rounded this way.
- **Reference year**: Welsh looked-after data is a year behind England, year ending March 2024 against England's March 2025.

### Children looked after: counts rather than rates

`lac_count` is a count, not a rate. A true looked-after rate by ethnicity needs a 0 to 17 child population by ethnic group at local authority level. The Census denominator in `populations.json` covers ages 10 to 17, to match the youth justice age range, so it cannot serve as a 0-17 looked-after denominator. The indicator code is `lac_count`, not the spec's `lac_rate`, so the name does not misrepresent the figure. A v2 enhancement could re-ingest a 0-17 ethnic child population to support proper looked-after rate calculations.

v1 visualisation requirement, for Sprint 3: when `lac_count` is shown in the geographic explorer, the count must be contextualised against the area's total child population, for example a two-axis chart, a proportional-area mark, or a rate per 1,000 against the general 10-17 population as a proxy with an explicit caveat. A raw count alone invites misleading comparison across authorities of very different sizes.

### Stop and search and arrests

`stop_search_rate` and `arrest_count` come from Home Office Police powers and procedures open data, year ending March 2025. They are published by police force area, so their records are keyed to the `pf-` geographies, not local authorities. The 43 territorial forces of England and Wales map to PRISM-R's 42 police force areas: the Metropolitan Police and the City of London Police both fold into `pf-london`. British Transport Police is excluded, as it polices the rail network and has no resident-population base; this is a documented gap.

Both datasets are rolled up to the YJB 5 ethnic groups from self-defined ethnicity. The stop and search open data also carries a combined officer-and-self-defined ethnicity column, which has fewer "not stated" records, but it collapses Mixed and Other into one category. Self-defined ethnicity is used for both datasets so all five groups are distinguished and the two are consistent. Searches and arrests recorded with a "not stated" self-defined ethnicity are counted in the overall figure but cannot be assigned to a group; the national not-stated counts are recorded in the `context_indicators.json` meta block.

Rate base differs from the exclusion indicators. `stop_search_rate` is carried as `rate_per_1000` (canonical), the Home Office and ONS convention for stop and search, with `rate_per_100` also provided so the file stays cross-comparable with the exclusion rates. The denominator is the 2021 Census child population aged 10 to 17 for the ethnic group in the force area, aggregated from local authorities via the geography crosswalk. This is a PRISM-R derived rate: the Home Office open data publishes counts, not rates.

`arrest_count` is carried as a count, not a rate, by the same reasoning as `lac_count`. The arrests open data and the Census denominator do share the 10 to 17 age band exactly, so an arrest rate would be well founded; arrests nonetheless feed the RRI cascade as a rate, computed in `rri.json`. The count is the figure carried in the context layer for consistency with the v1 indicator set.

### Deprivation: child income, parallel English and Welsh scales

The spec context layer carries an `imd_score` indicator. PRISM-R uses a child-focused income deprivation measure rather than the overall index, to match its youth focus. For England this is the Income Deprivation Affecting Children Index (IDACI) average score from the English Indices of Deprivation 2025: the proportion of children aged 0 to 15 in income-deprived families, averaged across each lower-tier local authority's small areas, with income data for the 2022/23 financial year. For Wales it is the WIMD income deprivation for children (aged 0 to 15) indicator, the percentage of children in income-deprived households, carried as a proportion, with income data for 2016/17.

England and Wales are carried as parallel scales, deliberately not harmonised. They measure the same concept, child income deprivation among children aged 0 to 15, but the English measure is an index-transformed score and the Welsh is a direct rate; the two use different income definitions, benefit data and reference years. A figure from one jurisdiction cannot be compared with a figure from the other: the English values run to 0.713, the Welsh to 0.33, and the difference is method, not deprivation. Each record names its `jurisdiction`, `measure` and `source_release` so the scale it belongs to is explicit. Cross-jurisdiction deprivation harmonisation, including the ONS experimental work, is a v2 question; deprivation in PRISM-R is context, not a primary outcome, so a cross-border comparison is not analytically core.

The IDACI average score and the Welsh child income measure are proportions, not rates per population, so the rate-base harmonisation applied to the exclusion and stop and search rates does not apply here; the rate fields are null.

The Welsh figure is WIMD 2019, not WIMD 2025. WIMD 2025 was published in November 2025 as an index with domain ranks and LSOA-level indicator data, but the income-by-age indicator data at local authority level was not yet available when PRISM-R ingested it. WIMD 2019 is the most recent child income figure obtainable by Welsh local authority. This is recorded in `docs/data-sources.md` as a re-ingest flag. The gap means the Welsh income data, for 2016/17, is about six years older than the English, for 2022/23, a further reason the two are not compared.

## Disclosure control

See [disclosure-control.md](disclosure-control.md).

## Corrections

Defects found in PRISM-R's own published figures or methods are recorded here, dated, whether or not anyone outside the project noticed them. An entry stays permanently.

### 3 September 2026: the explorer payloads republished 141 suppressed cells

**What the defect was.** Disclosure suppression runs as a stage after the pipeline's ingest and compute steps. Two steps added the same day, `build_explorer.py` and `build_csv_exports.py`, derive their outputs from `context_indicators.json`, but they were placed in the ordinary step list and so ran before that stage. They read the pre-suppression figures and wrote them out. The resulting records carried no suppression flag at all: they looked released, because at the moment they were built nothing had yet been suppressed. This is the same underlying failure as the entry below, one layer further out: suppression held in the file where it was applied and was lost in the files derived from it.

**Which file and which cells.** `data/processed/explorer/utla.json` and `explorer/pfa.json`, and the same figures served from the live site at `/data/explorer/`. 141 cells: 85 `lac_count`, 30 `stop_search_rate` and 26 `arrest_count`. Of those, 52 were primary suppressions, cells whose own count was between 1 and 5; the other 89 were secondary. None was a source suppression, so no publisher's own withholding was breached. The CSV exports shared the defect structurally but were regenerated after suppression before release, so no CSV was published containing a suppressed figure.

**How long it was present.** Committed at 14:05 on 3 September 2026 in commit `ded0100`, and deployed to the live site shortly after 14:18 with the deployment accompanying commit `1991370`. Corrected and redeployed at 16:56 the same day, in the work released as `v0.5.0-explorer`. The exposure was about two and a half hours on the live site and just under three hours in the public repository. The Internet Archive was checked afterwards for a cached copy: its CDX index holds no capture of `prism-r.howpreventionworks.com`, of the `prism-r.pages.dev` deployment previews, or of any path beneath `/data`, so no snapshot of the affected payloads was taken and no exclusion request was needed.

**How it was found.** By the guard written for the first defect, applied one layer further out. At 16:49 on 3 September 2026, while testing the browser CSV export, the export for a police force area showed no suppressed rows where twelve were expected. Reading the explorer payload for a cell already known to be suppressed found its rate present and no suppression flag on the record. The cross-output test written immediately afterwards reproduced the defect at 141 cells, which is where the count in this entry comes from. Again nobody outside the project reported it; both entries in this section were found by tests written for this class of defect, and the second was found because the first had taught us where to look.

**When it was fixed.** The same hour: `Step` gained an `after_suppression` marker, the derived steps were marked with it, and `build.py` now runs the suppression stage between the ordinary steps and the derived ones. The corrected data was deployed before this entry was written.

**The rule change that followed.** No change to the disclosure rules themselves; the rules were right and the pipeline had not applied them in the correct order. The guards were changed in three ways.

`tests/test_suppression.py` now cross-checks every derived output against its parent file, because the existing test inspects suppressed records for stray values and cannot see a record that never claimed to be suppressed. A cell suppressed in `context_indicators.json` that carries a value in an explorer payload, a CSV export or the target tracker fails the suite.

`build.py` derives the ordering requirement rather than trusting it. Each step declares the processed files it reads, and `dependency_issues()` compares those against the files disclosure control rewrites: a step reading one of them must either produce an output the suppression stage also processes, as `compute_rri.py` does, or be marked `after_suppression`. The build refuses to run when that does not hold, and a step added later is checked without anyone remembering to extend a list.

`compute_target.py` was moved onto the same pattern on 3 September 2026. It had been carrying its own call to the suppression module, applying the rules a second time internally so that its output was correct whichever order it ran in. That worked, but it meant two patterns existed for the same problem, and the pattern that failed was the one used everywhere else. It is now an ordinary post-suppression step reading the flags already on its input; the tracker output is byte-identical before and after the move (`618092a3`), so the change is a refactor and not a correction to any published figure.

**Assessment.** More serious than the entry below, because these figures were served from the site rather than sitting in a repository, and because the affected set was wider: 85 of the 141 were counts of looked-after children by local authority and ethnic group, and 52 were counts between 1 and 5. They remain non-identifying at this granularity. The pattern of the two entries taken together is the useful lesson, and the reason both are recorded in full: a suppression is only as good as the last file derived from it, and each new derived output is a place it can be lost.

### 3 September 2026: suppressed stop and search counts were recoverable from their rates

**What the defect was.** The disclosure-control stage nulled a suppressed count but left the rate derived from it in place. Because the denominator, the ONS Census 2021 child population by police force area and ethnic group, is itself published by PRISM-R in `populations.json`, the suppressed count could be recovered exactly by multiplying the rate by that denominator and dividing by 1,000. Suppressing the count while publishing its rate hid nothing.

**Which file and which cells.** `data/processed/context_indicators.json`. Thirty cells of the `stop_search_rate` indicator, covering 15 of the 42 police force areas: 12 Asian, 13 Other, 3 Mixed and 2 Black. Twenty were primary suppressions, cells whose own count was between 1 and 5. The other ten were secondary suppressions, larger counts hidden to stop the primaries being back-calculated; recovering those re-opened the route that secondary suppression exists to close. No other indicator and no other output was affected, because no other suppressed count had a published rate alongside it.

**How long it was present.** From 18 May 2026, commit `30f4ab3`, which wired suppression into the build orchestrator, to 3 September 2026, commit `ded0100`: 108 days. Throughout that period the file was committed to the public repository at github.com/SGilr/prism-r. It was not served from this site: the site published `manifest.json` and the suppression audit, not `context_indicators.json`, and no chart or page on the site ever displayed the affected rates. The exposure was to anyone reading the repository.

**How it was found.** By a test written for this class of defect, not by inspection and not by anyone outside the project. While building the geographic explorer data layer on 3 September 2026 an integrity check was written asserting that no suppressed cell in any explorer record carried a value. It reported 30 failures, which traced back through the explorer to `context_indicators.json` itself. Nobody had reported the figures; without the check they would still be published.

**When it was fixed.** The same day, in commit `ded0100`, which nulls every field a suppressed count can be reconstructed from rather than the count alone.

**The rule change that followed.** Rule 2 of the disclosure-control standard covered within-table back-calculation only. It now has two limbs: 2a, the original secondary-suppression rule, and 2b, derived-field recovery, which requires that a suppressed count leave no published field it can be recovered from, including rates, shares and percentages computed against any denominator published by PRISM-R or by its sources. See [disclosure-control.md](disclosure-control.md). `tests/test_suppression.py` now carries a structural guard that reads every processed output and fails if any suppressed record retains a recoverable field, so a future indicator cannot reintroduce the pattern quietly.

**Assessment.** The recovered figures were counts of children stopped and searched, between 1 and 5 per force and ethnic group. They were low-sensitivity in isolation and are not individually identifying. The defect is recorded here in full regardless, because the standard PRISM-R sets is that a suppression either holds or it does not, and this one did not.

## Known limitations

Recorded here as the build proceeds. See spec section 12.

## Citation guidance

Added before launch.
