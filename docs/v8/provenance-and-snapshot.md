# Provenance and the audit snapshot

## Manifest

Every snapshot starts with a manifest:

| Field | Meaning |
|---|---|
| `scan_id` | `gh-<run id>-<attempt>` in GitHub Actions (shared by every engine of one scan), `local-<time>` offline |
| `ts` | the scanner's scan time |
| `repo`, `ref`, `git_sha` | where the code came from |
| `schema`, `audit_version` | `v8.audit/1`, `v8-phase1.0` |
| `engine_versions` | each legacy engine's own version string |
| `config_hashes` | per engine, sha256 of its decision-relevant configuration (below) |
| `parts` | whether each engine's audit part was written (`ok`, `failed`, `missing`) |
| `scan_ids_consistent` | all parts come from the same scan |
| `registry_contracts`, `dispositions` | counts |
| `data_sources` | which DEX market lists loaded, whether the fallback coin list was used |
| `legacy_output_hashes` | sha256 of every legacy data file of the scan (the audit never changes them) |

### Config hashes

The hash covers the engine's `CFG` (minus `schedule_minute` and `schedule_every_min`, which the workflow sets through
the environment), its strategy definitions or score weights, the ticker lists (tradfi, known crypto, aliases,
symbol overrides, FX codes, the tradfi name pattern), the trade DEXs and liquidity minimum, and the sha256 of the
research file that decides what is "tested" (`quant_research.json`, `picks_research.json`, `smart_research.json`)
and of `strategies.json` when present. The structure is serialised canonically: sorted keys, sets sorted,
functions by qualified name, no memory addresses. No secret is part of any engine configuration: API keys and
webhook URLs stay in the environment and are never read by the audit.

## Snapshot

`data/v8/audit_latest.json` (and `.json.gz`), schema `v8.audit/1`:

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
