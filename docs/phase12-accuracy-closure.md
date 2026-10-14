# Phase 12 accuracy closure (draft PR #24)

The independent A02–A08 audit authorizes narrow correctness changes; strategy parameters, signal order,
statistical gates, Phase 10 limits, Phase 11 state/ranking policy and production Research publication remain unchanged.

* A02: Analyzer displays the exact candidate proposal evaluated by Phase 10. Its mark, stop, equity, quantity,
  notional, leverage, stop risk and costs are the authority. Saved browser preferences and chart quotes cannot
  reprice it. Custom proposal fields yield WAIT and no approved styling; restoring the exact proposal restores
  the display. AI/export payloads preserve proposal values without rounding or invented exits.
* A06: both public decision boundaries require integer scan time, the discovery/quant/portfolio timing map,
  existing freshness limits and explicit v8.discovery/1 provenance. Missing, future, stale and malformed
  input authority refuses the build. Known degraded discovery retains its existing WATCH semantics. Empty
  trade_dexes behavior is unchanged.
* A07: the shared desk reader requires as_of <= now <= valid_until, and every supplied directional start
  and expiry must fit the document. There is no clock-skew grace or validity extension. Expired candidates
  are excluded from actionable sections; malformed/future windows fail closed for Today and Analyzer.
* A03/A04/A05: see the Smart and Quant execution documents. Identity and execution proof are both required
  for qualified realized evidence. Unknown history remains unknown; historical fields and rows are preserved.
* A08: Picks/Quant/Smart/retired Radar are visibly diagnostic. Positive legacy records are unqualified
  historical results; score bands are watchlists, not approved trades. Their numerical scoring stays unchanged.

## Intentional parity changes

The exact field manifest pins every permitted delta: 238 JSON leaves in the deterministic fixture, plus
published source hashes. Quant open diagnostic R/mark/hours now use only completed replayed bars rather
than a forming candle. This is an accounting-context change, not a signal or ranking adjustment. Added
execution and funding metadata is explicit; Smart/Quant old stored closed values remain intact. Dashboard
copy and copied diagnostic mark/R fields follow those changes. Fully observed exits match the previous
arithmetic in separate old-source comparisons. No universe, venue, identity or strategy/scan decision delta
is permitted. The parity validator must reject any unlisted field or value.

## Release boundary (A01)

A01 code path protected; final deployment verification pending merge.

The operational main deployment already includes analyze.js, analyze.html and data/v8/decision.json.
After independent review and separately authorized merge, qualification must bind the Pages artifact and
deployment to the exact merged SHA, check those consumer/authority files and schema, and confirm missing,
stale or future decisions fail closed without legacy fallback. This draft does not authorize merge or deployment.

## Research identity

Changing quant.py changes its runtime implementation identity. Re-run all governed Phase 9 adjudication
at the exact new head; retain the reviewed policy and census. A hash change earns no promotion. Review
Research may publish its normal branch; production Research publication must stay skipped on this phase branch.
