# Disclosure control

These rules are non-negotiable and apply uniformly across PRISM-R. They are described openly on the methods page of the site so that users can see the rule, not just its consequence. They are enforced in `pipeline/suppress.py` and verified by `tests/test_suppression.py`.

## Rules

1. Cells with a count of 1 to 5 are suppressed and displayed as "<6, suppressed for disclosure control". A count of exactly 0 is a true zero, not a disclosure risk, and is shown as "0".
2. Secondary suppression applies where suppressing one cell would allow another to be back-calculated. Standard ONS practice is used: the next-smallest cell in the same group is suppressed, so a group never holds exactly one suppressed cell.
3. Rates are not displayed where the denominator population is below 100 in the relevant cell. The display reads "rate not shown, population too small".
4. Every suppression decision is logged in a methods-page audit trail.
5. Where the YJB has already suppressed a value in source data, that suppression is propagated downstream and flagged as inherited.

## Audit trail

Every decision is recorded in `data/processed/suppression_audit.json` by `pipeline/suppress.py`, so a reader can see the rule applied and not just its effect.

The audit file will materialise when sub-national data lands in Sprint 2 tasks 5 and 6, the first data with cells small enough to suppress. Until then there is nothing to suppress and the file is not written.

National YJB remand data is not put through suppression. It is published by the YJB at England and Wales level and is already disclosure-controlled at source; applying PRISM-R suppression to it would suppress figures the YJB has itself released.
