# A5.2 conditional research-data acceptance

Accepted on 2026-10-19 as a separate, retrospectively quality-restricted research
input. The original collected archive remains rejected. Its diagnostics and the
candidate's original unaccepted build marker remain unchanged; this document and
`research/v9/a5_quality_acceptance.json` record the later acceptance decision.

## Immutable dataset and verification

- Result branch: `hourly-a5-quality-results`.
- Result commit: `0859e683910a7eea7ef446b27cf9773f33d9e9f8`.
- Candidate manifest SHA-256:
  `d9eaba6b1a190d86529b01362a665f83c1c52d2a88e04f4cd71f4d333e8527b2`.
- Publication source: `0a370ff8a8b74b7453b63a4cf6fa4b8139d47eb3`.
- Successful publication run: `39274041013`; both source CI runs passed.
- All 1,386 remotely retained files independently hash-verified against the
  locally audited candidate, including its complete artifact manifest.
- Full regression suite: 1,038 tests passed.

The registered overlay reconstructs 66 corroborated four-hour blocks (264 hours)
and quarantines 28 unresolved blocks (112 hours). Across 690 segments the result
retains 13,862,226 hourly rows, 7,026 original missing hours and all 663 observed
zero-trade hours. The unavailable union is 7,138 hours. Funding bytes, original
segment boundaries, universe and ordered ranking schedule are preserved.

The separate quality schedule prohibits all new entries on 70 of 2,345 scheduled
days because their preceding seven-day ranking windows intersect quarantined
observations. Empty days remain in the calendar; no ranking refill is permitted.

## Conditions on use

This is retrospective source-quality selection, not information known to a
historical trader. All subsequent evidence must disclose this selection and its
coverage cost. The pinned manifest, quality ledger, coverage and quality schedule
must travel together; the unmodified ranking schedule alone is insufficient.

Missing/quarantined intervals are unavailable. An observed zero-trade hour is not
proof of an executable price. Before any A5.3 replay, commit and synthetically test
the exact contiguous-lookback, indicator reset/warm-up, funding and exit-gap
rules. Positions spanning unobservable execution or funding intervals remain
explicitly unresolved. Never remove those trades or replace unknown returns with
zero or convenient exits. Affected statistics remain unavailable unless separate
preregistered bounds justify a stated result.

A4.4 must disclose both the original hourly top-150 versus broad four-hour
universe difference and this added quality restriction. The historical unknown
trial census remains incomplete. This acceptance authorizes no strategy
promotion or production behavior change. A5.3 replay and A4.4 remain pending.
