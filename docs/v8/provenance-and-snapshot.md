# Provenance and the audit snapshot

## Manifest

Every snapshot starts with a manifest:

| Field | Meaning |
|---|---|
| `scan_id` | `gh-<run id>-<attempt>` in GitHub Actions (shared by every engine of one scan), `local-<time>` offline |
| `ts` | the scanner's scan time |
| `repo`, `ref`, `git_sha` | where the code came from |
| `schema`, `audit_version` | `v8.audit/4`, `v8-phase6.0` (Phase 1 wrote `v8.audit/1`, Phase 2 `v8.audit/2`, Phases 3 and 4 `v8.audit/3`, Phase 5 `v8.audit/4` with `v8-phase5.0`) |
| `identity_version`, `liquidity_version` | `v8.identity/4`, `v8.liquidity/1`: the universe identity and liquidity semantics that built this scan's universe (Phase 2 wrote `v8.identity/1`, Phases 3 and 4 `v8.identity/2`, Phase 5 `v8.identity/3`) |
| `identity_config_hash` | Phase 3: sha256 of everything that decides an identity state (`v8.provenance.identity_config()`: version, tolerance, venue label sets, base-only-symbol venues and quote suffixes, the tradfi and known-crypto lists, FX codes, the tradfi name pattern), also in every engine part's header |
| `engine_versions` | each legacy engine's own version string |
| `config_hashes` | per engine, sha256 of its decision-relevant configuration (below) |
| `parts` | whether each engine's audit part was written (`ok`, `failed`, `missing`) |
| `scan_ids_consistent` | all parts come from the same scan |
| `registry_contracts`, `dispositions` | counts |
| `data_sources` | which DEX market lists loaded, whether the fallback coin list was used, and (Phase 5) the state of each economic-exposure metadata source (`exposure_metadata.LIGHTER_TOKENLIST`: OK, FAILED, UNAVAILABLE, MALFORMED or NOT_REQUESTED) |
| `legacy_output_hashes` | sha256 of every legacy data file of the scan (the audit never changes them) |
| `strategy_authority` | where quant strategy authority comes from today: `quant.py`'s runtime `ORDER`, the research `FINAL` tuple in `tools/research/qexport.py`, whether its `verdict()` pre-assigns "live", the research file's verdicts, and the hashes of those files (exposed, not changed) |

### Config hashes

The hash covers the engine's `CFG` (minus `schedule_minute` and `schedule_every_min`, which the workflow sets through
the environment), its strategy definitions or score weights, the ticker lists (tradfi, known crypto, aliases,
symbol overrides, FX codes, the tradfi name pattern), the trade DEXs and liquidity minimum, and the sha256 of the
research file that decides what is "tested" (`quant_research.json`, `picks_research.json`, `smart_research.json`),
the identity version with its tolerance and venue-label sets and the liquidity version (Phase 2),
and of `strategies.json` when present. The structure is serialised canonically: sorted keys, sets sorted,
functions by qualified name, no memory addresses. No secret is part of any engine configuration: API keys and
webhook URLs stay in the environment and are never read by the audit.

## Snapshot

`data/v8/audit_latest.json` (and `.json.gz`) has schema `v8.audit/4`. What each phase added:

* **Phase 2:** the identity columns of every contract, `registry.assets[t].identity` and the identity counts.
* **Phase 3:** the identity state, evidence, parsed symbols, links and raw venue fields, and `coverage.summary.identity`.
* **Phase 4:** the candidate evidence.
* **Phase 5:** the contract columns `wrapper` and `xcheck`, and, per asset, `wrapper_evidence`, `exposure_checks`, `wrapper_only`, `exposure_trace` and `previous` (the previous identity version on the same contracts). Also `registry.counts.exposure_safety`, `data_health.exposure_metadata` and `coverage.summary.identity.exposure_safety`.
* **Phase 6:** per asset `ticker_authority` (the known-crypto list's exposure binding), per exposure `binding`, and `exposure_trace.binding` (the Decision Trace of the binding); `previous` is now `v8.identity/3`. Also `registry.counts.ticker_authority`, `registry.counts.known_crypto_list` and `coverage.summary.identity.ticker_authority` (unaccounted 0). No new contract column.

See [contract-identity.md](contract-identity.md), [phase3-identity-coverage.md](phase3-identity-coverage.md) and [phase5-economic-exposure.md](phase5-economic-exposure.md). Next to it, `data/v8/identity_state.json` (Phase 3:
asset -> [identity state, since], read back from the site next scan to list identity transitions), and
`data/v8/identity_authority.json`, which the scanner writes for the engines of the same scan that do not build the
universe (smart money; see [phase3-identity-coverage.md](phase3-identity-coverage.md#smart-money-the-same-scan-identity-authority)).
The smart part's journal evidence - identity-qualified and legacy-unqualified paper trades - appears in the snapshot
as `coverage.engines.smart.journal`:

| Section | Contents |
|---|---|
| `manifest` | above |
| `registry` | `counts`, every contract (`contracts.fields` names the columns, `contracts.rows` holds one row per contract; `v8.snapshot.contract_records()` turns them back into records), `assets`, universe `events` (price conflicts, fallback) |
| `data_health` | see [data-health.md](data-health.md) |
| `dispositions` | per engine, one compact record per asset (no candles, no price arrays); the human sentence is rendered from the code, observed value and rule by `v8.ledger.expand()`, which also joins the scan, engine, commit, config hash and version fields |
| `coverage` | the per-scan accounting below, plus each engine's counts by disposition and by reason and its stages |
| `reasons`, `steps` | the taxonomy, so the file reads on its own |
| `legacy_output_refs` | path, sha256 and size of each legacy file |
| `storage` | this snapshot's measured size and projections |

The snapshot is deterministic: for the same engine parts, legacy files and previous first-seen map it is
byte-identical (sorted keys, no wall-clock values other than the scan's own; the gzip header carries no name or
time). `tests/test_v8_audit.py` checks this.

### Coverage accounting

`coverage.summary` reports per scan: raw contracts, active perps, canonical assets, the legacy universe and its
crypto part, tradfi exclusions and collisions, universe-level exclusions, radar no-data exclusions, scanner stage 1,
stage 2, extras and deep dives, quant-eligible coins, swing-eligible coins, coins represented in smart money,
dispositions per engine, and **unaccounted** assets:

* `registry_assets`: canonical assets of the registry with neither a universe nor a radar record;
* per engine: assets the engine received without a final disposition.

All are zero on the fixture, and the tests fail if any is not.

## History: bounded, append-only, temporary

Phase 1 does not choose permanent storage. It provides:

* the latest snapshot in the published site (`data/v8/audit_latest.json`);
* `data/v8/first_seen.json`: contract id -> [first seen, last seen], carried from scan to scan through the site
  and pruned after 400 days without a sighting;
* an append-only archive: `python -m v8.snapshot --archive-dir DIR` writes `audit_<scan id>.json.gz` and never
  overwrites an existing scan's file. The Scan workflow uploads that folder as an Actions artifact kept for
  **14 days**, so the archive is bounded by GitHub's retention, not by a growing git history.

No database, bucket, paid service or new account is used. Measured sizes are in the PR and in each snapshot's
`storage` section.
