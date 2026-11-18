# A4.4 fixed assembly specification

Registered after inspecting A4/A5 results and before implementing or applying the assembly. This is a provenance-preserving inventory of existing studies, not an unseen-data hypothesis or a new strategy search. Known limitations and results are disclosed in `phase-a4-evidence-review.md`.

## Fixed inputs

- A4 result `18c14932bcc2ba9e8685f231e1725a786869edd9`: `evidence_a4.json`, `daily_returns.npz`, and its artifact manifest.
- A5 result `84412b14ae8a1dee7299c2ebdbb32a45ac5d0e0e`: `replay_run.json`, `evidence_a5.json`, `attempts_a5.json`, and their artifact bindings.
- Registered `research/v9/census_replay_plan.json`, the first five intact entries of `research/v9/evidence_runs.jsonl`, and `research/v9/a5_replay_verification.json`.
- Resolve exact commits, never moving result-branch tips. Verify source evidence bytes against the hash-chained records; verify matrix/driver hashes and current plan against source bindings. Fail on missing or inconsistent provenance.

## Assembly rules

1. Preserve all 199 trial IDs and registered order. Require exactly the 192 registered four-hour/daily identities and seven hourly identities; reject duplicates, extras, omissions or changed definition bindings.
2. Verify the A4 daily axis is consecutive and exactly covers its declared window including the terminal exit day. Require A5's declared window to match. Do not intersect calendars, trim days or shift exit dates to manufacture comparability.
3. Preserve all A4 matrix values exactly, including missing hourly entries. Verify every completed four-hour/daily column is finite and every hourly column is wholly missing.
4. This specification accepts only the inspected A5 result whose seven net series are unavailable. Validate those statuses and retain seven wholly missing columns. An unexpectedly available series must fail validation, not trigger a new statistical calculation. Preserve all attempt counts and unavailability reasons in column metadata.
5. Missing remains missing, never zero. Do not use gross-price outcomes as net returns, impute funding, remove unresolved trades, rank subsets, tune parameters, or drop constant/sparse columns.
6. Copy retained A4 full-family unavailable-statistic dispositions with their original provenance and label them as inherited, not recomputed. Preserve the 192-column diagnostics by reference only. Assert historical-census completeness false, known-family return completeness false, common-universe experiment false, promotion authority false and confirmed empty.
7. Disclose broad four-hour versus top-150 hourly universe, legacy versus gap-aware execution, unknown hourly funding, observed-event FUND_FADE, unavailable FUND_CARRY, retrospective quality exclusions and continuity resets in both machine-readable and human-readable output.

## Output and acceptance

Write into a new empty directory only: `daily_returns.npz`, per-column status/provenance JSON, a human-readable report, and a final assembly manifest with input/output hashes, exact source commits, specification/tool hashes and unavailable-statistic reasons. Write the final manifest last. Preserve failure evidence without manufacturing completion.

The matrix is an unchanged inventory of 192 diagnostic columns plus seven unavailable columns. A changed compression hash is permitted only if decoded days, IDs and values are identical, including missing-value locations. Independently compare every cell and identity to the retained A4 source, and reconcile every hourly metadata count to the retained A5 source.

Synthetic tests must reject corrupt hashes, wrong source identity, reordered/duplicate/missing trials, changed windows/day axes, non-finite completed columns, finite values in missing hourly columns, contradictory A5 availability and output overwrite. Test that an incomplete family cannot produce available full-family statistics or promotion authority.

Record the derived assembly separately with links to evidence-history entries 4 and 5; do not append a fictitious strategy replay or change existing records. This fixed-input, no-new-statistic assembly does not close A5.3 or establish complete known-family returns. A4.4 reporting/assembly completion must be distinguished from the still-blocked complete-return objective.
