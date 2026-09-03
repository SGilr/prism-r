# Disclosure control

These rules are non-negotiable and apply uniformly across PRISM-R. They are described openly on the methods page of the site so that users can see the rule, not just its consequence. They are enforced in `pipeline/suppress.py` and verified by `tests/test_suppression.py`.

## Rules

1. Cells with a count of 1 to 5 are suppressed and displayed as "<6, suppressed for disclosure control". A count of exactly 0 is a true zero, not a disclosure risk, and is shown as "0".
2. A suppressed count must leave no published field from which it can be recovered. This has two limbs.

   **2a. Within-table back-calculation.** Secondary suppression applies where suppressing one cell would allow another to be back-calculated from a published group total. Standard ONS practice is used: the next-smallest cell in the same group is suppressed, so a group never holds exactly one suppressed cell.

   **2b. Derived-field recovery.** Suppressing the count is not sufficient on its own. Any rate, share, percentage, index or other derived figure computed from that count must be suppressed with it, wherever the denominator is published by PRISM-R or by any of its sources. A rate against a known denominator is the count, written differently: it can be multiplied back. This applies whether the denominator sits in the same record, in another PRISM-R output such as `populations.json`, or in the publisher's own release. In practice, suppressing a count nulls every field on the record from which the count could be reconstructed, including `numerator`, `rate_per_100`, `rate_per_1000`, `source_rate` and `share`.

   Limb 2b was added on 3 September 2026 after a defect was found in which it was not enforced. See the "Corrections" section of `docs/methods.md`.

   **Where the rules are applied.** Suppression runs once, as a stage of the build, over the files named in `SUPPRESSION_PLANS`. Steps that derive their outputs from those files run after that stage and read the flags it leaves, rather than applying the rules again themselves. `pipeline/build.py` derives this requirement from each step's declared reads and refuses to run when a step reading suppression-controlled data would produce an output that nothing downstream will clean. One stage, one pattern: a second implementation of the rules is a second place for them to drift.
3. Rates are not displayed where the denominator population is below 100 in the relevant cell. The display reads "rate not shown, population too small".
4. Every suppression decision is logged in a methods-page audit trail.
5. Where the YJB has already suppressed a value in source data, that suppression is propagated downstream and flagged as inherited.

## Audit trail

Every decision is recorded in `data/processed/suppression_audit.json` by `pipeline/suppress.py`, so a reader can see the rule applied and not just its effect.

The audit file will materialise when sub-national data lands in Sprint 2 tasks 5 and 6, the first data with cells small enough to suppress. Until then there is nothing to suppress and the file is not written.

National YJB remand data is not put through suppression. It is published by the YJB at England and Wales level and is already disclosure-controlled at source; applying PRISM-R suppression to it would suppress figures the YJB has itself released.

## Limitations of the suppression approach

When every cell in a small group is primary-suppressed and the group total is published, an observer can derive the sum of the hidden cells by subtracting the visible cells from the total. This bounds each hidden cell to a range. It never reveals an exact figure, but on a small group the range can be narrow.

This is accepted for v1. National remand data is published by the YJB and is not put through PRISM-R suppression. The sub-national context data, school exclusions, looked-after children, and child population, is already disclosure-controlled at source by the DfE and the ONS; the PRISM-R module applies as a belt-and-braces layer for cells derived in the pipeline. The risk of meaningful range disclosure on a derived cell at local authority level is low, because the underlying counts are typically large. This is to be revisited if sub-national remand data, which has much smaller cells, is ingested in v2.
