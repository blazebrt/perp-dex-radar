# Separate prospective paper ledger: version 1

Owner selected a separate ledger on 2026-11-27. This contract precedes any market
evaluation of the new lifecycle. Implementation: `v9/prospective_paper.py`.
This is an offline paper-observation contract, not a strategy confirmation study.

## Fixed rules

All times are integer UTC seconds. Authorization retains exact audit, decision
and quant-journal source strings, rechecking their byte/hash bindings. Only one
unambiguous DIRECTIONAL_STRATEGY candidate with TRADE state, FULL or PROBATION tier,
a passing SIGNAL gate, no failed/missing gate, valid policy/implementation hashes,
positive risk fraction and a valid stop/holding plan may be registered. Decision
time must precede the audit time, which must not exceed the observation time;
equality is allowed. Both candidate and document expiry must be strictly later.

Identity is the hash of candidate ID and original signal-bar time. A signal may
be registered only once, including after cancellation or closure. Venue and exact
instrument mapping must be explicitly supplied and retained before entry. They
are caller assertions until independently verified by a production adapter.

Entry requires a separately retained, subsequent quote: quote time must be
strictly later than authorization, no earlier than the latest authority recheck,
and no later than receipt or observation. Quotes may be at most 30 seconds old.
Entry rechecks the bound candidate's TRADE state, tier, policy, implementation,
signal identity and expiry. Changed authority refuses entry; a cancellation can
then retain the demotion. The first successfully submitted admissible quote is
used. The offline API cannot prove that a caller supplied every earlier quote.

Prices are positive fixed decimal strings (at most 18 integer and 18 fractional
digits); crossed markets fail. Long entries use ask and short entries use bid.
The registered absolute stop must still be on the protective side of entry.
Paper entry time is the actual observation time, never the older signal-bar time.
The original candidate, entry tier, authorization time and source bindings remain
unchanged after entry.

Subsequent observations require strictly increasing quote timestamps. Long exits
use observed bid, short exits observed ask. A protective-stop crossing closes at
the observed quote, not at an invented stop fill. Otherwise, the first submitted
quote at/after entry plus the registered holding period closes as a time exit.
Stop takes precedence when both conditions hold. No interpolation, trailing-stop
simulation, continuous monitoring, liquidity fill or unseen intrabar excursion is
claimed. Missing quotes leave an open observation unresolved; they never imply
zero return. Pending registrations can be cancelled for expiry, demotion, missing
price or an explicitly recorded operator cancellation.

Gross price return is descriptive only. Fees, slippage and funding remain unknown;
net_R is always null. There is no position quantity, portfolio allocation, execution
authority or qualified performance. Production use requires a reviewed prospective
book risk/sizing policy; existing quant-book limits do not qualify this new book.

## Durable local event journal

SQLite retains exact event inputs in one transaction with synchronous FULL.
The authorization transaction must return successfully before a later entry is
attempted. BEGIN IMMEDIATE serializes writers. Identical event retries return the
current retained state without repeating an entry or reversing later events.
Every read/write verifies sequence, chained SHA-256 and replays all transition
rules; derived state is not accepted from storage. Failed transitions and failed
inserts leave no partial accepted event. Rejected invocations are not durable
events; a caller must retain its own acquisition/error log. Explicit cancellations
are durable events.

Limits: 4 MiB per event, 10,000 events and 64 MiB total event bodies. Limits fail
rather than discard old observations. Connections close after every operation.
Read-only inspection cannot create a missing database. Content hashes detect
accidental mutation; a privileged rewrite or suffix deletion is not independently
detectable without a separately retained head. SQLite is local atomic retention,
not remote backup, independent timestamping or production durability.

## Offline interface

`python -m v9.prospective_paper --ledger <database> --event <event.json>`
applies one event; omit `--event` to verify and inspect a retained database.
The module neither downloads data nor publishes files or places orders.

All events contain `contract: "v9.prospective-paper/1"`, `action`, and `at`.
An `authorize` event includes `candidate`, `venue`, `instrument`, and `sources`
mapping these paths to their exact UTF-8 document strings:

- `data/v8/audit_latest.json`
- `data/v8/decision.json`
- `data/quant_journal.json`

An `enter` event includes authorization `key`, current `sources`, and `quote` as
an exact JSON string. An `observe` event includes `key` and `quote`. A `cancel`
event includes `key` and `reason` (`EXPIRED`, `DEMOTED`, `MISSING_PRICE`, or
`OPERATOR_CANCELLED`). Quote documents contain schema `v9.paper-quote/1`, `venue`,
`instrument`, `asset`, `as_of`, `received_at`, and decimal-string `bid`/`ask`.
Synthetic examples and failure cases are in `tests/test_v9_prospective_paper.py`.

## Acceptance boundary

This completes the separate offline authorization/entry/observation/exit lifecycle
and local retention implementation. Existing quant code, paper records, evidence
bindings, published pages and production Scan remain unchanged. No market run has
occurred and no existing journal entry acquired a tier.

F4 remains open for independently bound source/clock/instrument adapters, durable
remote retention and failure recovery, prospective book risk/cost qualification,
separate page integration with pinned publication deltas, and an authorized
production qualification. The retained historical ledger remains a distinct
diagnostic population. Do not add a performance claim merely because this
software passes its tests.
