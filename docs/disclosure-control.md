# Disclosure control

These rules are non-negotiable and apply uniformly across PRISM-R. They are described openly on the methods page of the site so that users can see the rule, not just its consequence. They are enforced in `pipeline/suppress.py` and verified by `tests/test_suppression.py`.

## Rules

1. Cells with a count below 6 are suppressed and displayed as "<6, suppressed for disclosure control".
2. Secondary suppression applies where suppressing one cell would allow another to be back-calculated. Standard ONS practice is used.
3. Rates are not displayed where the denominator population is below 100 in the relevant cell. The display reads "rate not shown, population too small".
4. Every suppression decision is logged in a methods-page audit trail.
5. Where the YJB has already suppressed a value in source data, that suppression is propagated downstream and flagged as inherited.

## Audit trail

The suppression audit trail is produced by the pipeline from sprint 2 onwards and surfaced on the methods page.
