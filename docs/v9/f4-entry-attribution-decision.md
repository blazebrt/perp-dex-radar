# F4: entry-time attribution decision

Prepared 2026-11-27 for existing draft PR #30. Design only; no implementation,
research execution, production activation or historical attribution is claimed.

## Verified cause

The Scan workflow runs quant.py before v8.snapshot. quant.py creates new paper
records with t_in equal to the historical signal-bar boundary, then replays them.
The desk decision is generated later from the resulting outputs. Consequently,
neither that decision's timestamp nor its observed strategy tier establishes
authorization before the paper entry. Even moving a capture step immediately
before journal serialization would still be after the historical entry time.

Evidence locations: quant.py's new-paper-trades loop and replay(new), and the
quant/audit/paper-observation steps in .github/workflows/scan.yml.

## Required product distinction

Keep the existing historical/replayed quant journal as an unqualified diagnostic.
Do not attach later FULL or PROBATION labels to its entries, and do not change
historical timestamps to make them appear prospective.

A qualified prospective ledger needs a distinct entry lifecycle:

1. Retain the exact decision, policy and implementation bindings, candidate
   identity, direction, plan, tier, expiry and observation time before any entry.
2. Admit only a still-valid TRADE candidate with complete required evidence.
   A strategy tier alone is insufficient; candidate gates must pass.
3. Establish a subsequently observed executable paper entry using a fixed,
   preregistered price/time/cost rule. Never use the earlier signal-bar open.
   No future quote or candle may determine an earlier fill.
4. Atomically retain the authorization and entry identity before subsequent
   lifecycle processing. Retries must be idempotent; failures and missed scans
   remain explicit. An expired or unretained authorization cannot create an entry.
5. Preserve the original entry tier and bindings through later demotion or policy
   changes. Capture current authority separately. Cancellation, missing prices,
   gaps, funding and unknown outcomes must remain distinguishable.
6. Report this ledger separately from replayed quant returns. Do not combine the
   populations into per-tier performance or treat source consistency as strategy
   qualification.

This is more than adding a journal field. It introduces a prospective execution
contract and must not silently reuse the existing retrospective performance claim.

## Implementation and acceptance package

- Fix the prospective execution/expiry/cost/missingness contract before any
  market evaluation. Define whether it is a separate governed paper ledger or a
  refactor of the existing quant entry path; do not choose implicitly.
- Implement the lifecycle and immutable retention together, with synthetic
  checks for ordering, expired/missing authority, duplicate retries, interrupted
  publication, source mutation, demotion and unknown outcomes.
- If quant.py changes, its current probation implementation binding becomes
  invalid. Keep that policy fail-closed until the required confirmation and
  independently reviewed binding are complete. Frozen research methods must not
  be edited to make a new runtime appear equivalent.
- Verify published-output deltas, retain the required parity artifacts and run
  the full regression suite before uploading implementation to PR #30.
- Production activation requires explicit merge approval and a successful,
  independently checked Scan. A local synthetic pass is not production closure.

## Status

F4 remains open. Existing archive preservation and coverage work are implemented;
entry-time authority is not. No additional archive helper can close the ordering
gap. The other nine core acceptance items are unchanged. This document is a
reviewable scope decision, not a completed roadmap item.


## Owner decision and implementation

On 2026-11-27 the owner selected a separate prospective ledger. Its offline
lifecycle and local atomic retention are implemented in v9/prospective_paper.py;
see prospective-paper-contract.md for fixed rules, interface and remaining
production qualification. The existing quant runtime is unchanged.
