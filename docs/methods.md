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
