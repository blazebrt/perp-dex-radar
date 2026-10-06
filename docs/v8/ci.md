# Blocking CI

## `.github/workflows/ci.yml`

Runs on every pull request to main, every push to main and to `v8/*` branches, and on demand. No step uses
`continue-on-error` and no test command ends in `|| true`: a failing command fails the job.

| Job | Steps |
|---|---|
| Unit tests and legacy parity | all unit tests (`python -m unittest discover -s tests`); the v8 Phase 1 tests on their own; legacy parity against the committed golden digests; on pull requests, legacy parity against the base commit rebuilt on the same runner; every workflow file parses |
| Simulator and no-edge checks | installs numpy and numba; `tools/research/test_qsim.py`; `tools/no_edge_check.py` |

To make a red run block merging, add both jobs as **required status checks** for `main` (Settings > Branches >
branch protection rule > Require status checks to pass before merging). That is a repository setting for the owner
to switch on; the workflow cannot do it.

## Scan workflow gate

`scan.yml` now runs the fast core unit tests (every engine's and the v8 unit tests, about 20 seconds) right after
Python is set up. If they fail, the job stops there: the scanner does not run and nothing is published. The
downstream resilience of the scan is unchanged: smart money, quant desk and coin picks keep `continue-on-error`
with their "keep the published files" fallbacks, and the v8 snapshot step is also `continue-on-error` because an
observability problem must never stop the pages from being published.

## Research workflow

`research.yml` (non-blocking by design: it runs the engines on live data and saves the results to the `research`
branch) now also runs on `v8/phase-*` branches and saves `research_v8_summary.json` and the gzip snapshot, so the
registry and coverage counts of a live run can be read before main changes.
