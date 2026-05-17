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

PRISM-R holds four RRI series, two decision points by two provenances:

- Adult custodial sentencing and adult remand, `provenance: "moj_published"`. These are adopted verbatim from MoJ tables 9.01 and 5.17a. See "Reproducibility of MoJ-published RRIs" below.
- Child custodial sentencing and child remand, `provenance: "prism_r_derived"`. These are computed by PRISM-R.

PRISM-R is therefore producing a child-specific RRI that does not exist in published official statistics. It is computed transparently from open YJB data, applying the MoJ-recommended methodology to children specifically. Child custodial sentencing uses YJB Table 5.8, children sentenced for indictable offences by ethnicity and sentence type. Child remand uses YJB Table 6.1: the rate is the proportion of children subject to a remand decision who are remanded to youth detention accommodation, that is custodial remand.

The adult rows are calendar year 2024, as MoJ publishes them. The child rows are the year ending March 2025, the latest YJB year and the basis used elsewhere in the pipeline. This period difference is recorded in the `rri.json` meta block.

Spec section 4.6 will be revised after Task 3 to reflect what PRISM-R actually does: applying the MoJ-recommended methodology to youth-specific data and decision points, with explicit provenance labelling.

## Confidence interval methodology

PRISM-R reports a 95% confidence interval for every `prism_r_derived` RRI. The interval is the Wald interval on the log of the rate ratio:

    SE(ln RRI) = sqrt(1/a + 1/b - 1/A - 1/B)
    95% CI     = exp( ln(RRI) plus or minus 1.96 x SE(ln RRI) )

where a and A are the event count and total for the group, and b and B those for the White baseline. This is the standard interval for a ratio of rates in epidemiology and public health. It is cited to Altman, Machin, Bryant and Gardner, Statistics with Confidence, 2nd ed., BMJ Books, 2000.

Two points of method:

1. MoJ uses p-value-based significance flags rather than confidence intervals. PRISM-R adopts confidence intervals because they convey magnitude and uncertainty together in a single visual, whereas a p-value flag is binary. Both are valid; confidence intervals are the more informative choice for a public-facing tool. MoJ's flag is still carried, on the `moj_published` rows, in the `significance_flag` field.

2. The Wald log-ratio interval is unreliable when any underlying count is small, below about 5. PRISM-R suppresses cells below 6, so this is largely a non-issue, but it is flagged honestly: intervals computed near the suppression boundary will be wide and may extend implausibly. Exact methods, such as the Wilson or Fisher interval, are deferred to v2.

TODO, methodology reviewer: the confidence interval method above is to be reviewed and signed off before launch.

## Reproducibility of MoJ-published RRIs

The Ministry of Justice publishes RRI values in tables 9.01 (custodial sentencing) and 5.17a (remand in custody) of Statistics on Ethnicity and the Criminal Justice System 2024. It does not publish the underlying counts: the numbers of defendants sentenced, and sentenced to immediate custody, by ethnic group and offence type.

Those counts are derived from the Court Proceedings Database, which is not public. The published Criminal Justice Statistics outcomes tools hold the data only inside an embedded analytical model that is not machine-readable with an open toolchain, and the Ethnicity Facts and Figures service has not been refreshed past 2017.

End-to-end reproduction of the MoJ RRIs from public sources is therefore not possible. PRISM-R adopts the published values as reference, cited verbatim, with `provenance: "moj_published"`.

This is not a criticism of MoJ practice. It is a description of the disclosure environment: aggregate RRIs can be released where the underlying record-level data cannot. It explains why two of the four RRI series in `rri.json` carry `provenance: "moj_published"` rather than `prism_r_derived`, and why those two carry no confidence interval, since the interval needs the same withheld counts.

## Denominator basis

Population denominators use the 2011 or 2021 Census basis. The basis is flagged per indicator, because the change between censuses affects comparability.

## Disclosure control

See [disclosure-control.md](disclosure-control.md).

## Known limitations

Recorded here as the build proceeds. See spec section 12.

## Citation guidance

Added before launch.
