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

The RRI calculation method is documented here in sprint 2.

## Denominator basis

Population denominators use the 2011 or 2021 Census basis. The basis is flagged per indicator, because the change between censuses affects comparability.

## Disclosure control

See [disclosure-control.md](disclosure-control.md).

## Known limitations

Recorded here as the build proceeds. See spec section 12.

## Citation guidance

Added before launch.
