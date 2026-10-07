# Blocking CI

## `.github/workflows/ci.yml`

Runs on every pull request to main, every push to main and to `v8/*` branches, and on demand. No step uses
`continue-on-error` and no test command ends in `|| true`: a failing command fails the job.

| Job | Steps |
|---|---|
| Unit tests and legacy parity | all unit tests (`python -m unittest discover -s tests`); the v8 tests on their own (Phase 1 audit, Phase 2 identity, liquidity and delta validator); legacy parity against this branch's committed golden digests; differential parity against the phase base commit rebuilt on the same runner (`tools/v8/delta_parity.py`: only the deltas listed in `tests/fixtures/v8/phase2_expected_deltas.json`, all of them, nothing else); every workflow file parses |
| Simulator and no-edge checks | installs numpy and numba; `tools/research/test_qsim.py`; `tools/no_edge_check.py` |

Both jobs are required status checks of `main` (ruleset 24588029, strict). Their names are what the ruleset matches:
do not rename them.

### Differential parity (Phase 2)

Phase 1 required the legacy outputs to be identical to the base. Phase 2 changes them on purpose, so the base check
became a differential one: the base commit named in the manifest must reproduce its own golden digests (also with
its own universe injected, which proves injection changes nothing else); this branch must reproduce its own; the
universe delta between the two (per coin field, venue set, DEX status count and note) must equal the manifest; and
the base's code fed this branch's universe must produce this branch's outputs except for the manifest's code deltas.
A difference outside the manifest, or a manifest entry that does not occur, fails the job.

## Scan workflow gate

`scan.yml` now runs the fast core unit tests (every engine's, the v8 unit tests and, since Phase 2, the identity and
liquidity tests; about 20 seconds) right after
Python is set up. If they fail, the job stops there: the scanner does not run and nothing is published. The
downstream resilience of the scan is unchanged: smart money, quant desk and coin picks keep `continue-on-error`
with their "keep the published files" fallbacks, and the v8 snapshot step is also `continue-on-error` because an
observability problem must never stop the pages from being published.

## Research workflow

`research.yml` (non-blocking by design: it runs the engines on live data and saves the results to the `research`
branch) now also runs on `v8/phase-*` branches and saves `research_v8_summary.json`, the gzip snapshot and (Phase 2)
`research_identity.json`, the live collision matrix from `tools/v8/identity_report.py`, so the registry, coverage and
identity decisions of a live run can be read before main changes.
