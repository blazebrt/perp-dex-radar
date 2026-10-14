# Perp Decision Desk: read me first

This repository is the Perp Decision Desk (formerly Perp DEX Radar). It is a crypto-perpetuals research and decision
product that runs entirely on GitHub Actions and GitHub Pages.

**Every session starts with `docs/v9/HANDOVER.md`.** It holds:

- the current state of the product;
- the diagnosis of what went wrong in v8;
- the evidence so far;
- the roadmap with acceptance criteria;
- the ordered next steps;
- a log of what each session did.

Update its "Where things stand" table and its session log before you finish.

## Facts about the environment (verified, do not re-discover)

- **This sandbox cannot reach exchanges or PyPI.** The egress allowlist blocks them. Data and research jobs therefore
  run in GitHub Actions. Actions job logs and artifacts cannot be downloaded from here (blob storage is blocked), so
  each job commits its results to a branch.
  - The local clone tracks only a few branches, so fetch a results branch with an explicit refspec:
    `git fetch origin +refs/heads/<branch>:refs/remotes/origin/<branch>`.
  - Then read files with `git show origin/<branch>:<file>`.
  - Do not fetch `archive-data` here: it is large, and the research code that uses it runs in Actions.
- **Workflow files on non-default branches cannot be dispatched.** Trigger them with a push that matches their
  `paths` filter.
- **Running research code locally:** numpy and pandas are installed here; numba is not. For small smoke tests, use
  `PYTHONPATH=tools/v9/devstub` and the synthetic archive from `tools/v9/make_fake_archive.py`.
- **GitHub-hosted runners sit in the US (Azure).** From there:
  - `fapi.binance.com` returns 451 and `api.bybit.com` returns 403;
  - `data.binance.vision`, OKX, Hyperliquid, Gate, MEXC, Bitget, HTX, KuCoin, Kraken, Deribit, dYdX, CoinGecko and
    DefiLlama (free endpoints) all work.
  - The full table is in `docs/v9/data-sources.md`. Re-run it with the "Data source probe" workflow.

## Research and results branches (force-pushed single commits, never merged)

| Branch | Written by | Contents |
|---|---|---|
| `probe-results` | `.github/workflows/probe.yml` | which data sources answer from Actions |
| `evidence-results` | `.github/workflows/evidence.yml` | survivorship-free re-test of every strategy (`REPORT.md`, `evidence.json`, `trades.json.gz`) |
| `archive-data` | `.github/workflows/evidence.yml` | the research dataset: 4h candles and funding for every Binance USD-M perpetual that ever traded, delisted ones included |
| `evidence-d1-results` | `.github/workflows/evidence_d1.yml` | the phase D1 study, tested once (`REPORT_D1.md`, `evidence_d1.json`, `trades_d1.json.gz`) |
| `market-results` | `.github/workflows/market.yml` | a check run of the market-context collector (`market.json`, `run.txt`) |
| `v9-market-history`, `v9-market-history-dryrun` | the Scan workflow on main; `market.yml` | the hourly append-only market-context history (`market/YYYY/MM/DD/HH.json.gz`) |
| `research`, `research-production` | `research.yml` | the v8 governed research jobs |
| `v8-history` | the Scan workflow | the append-only point-in-time observations |
| `journal-data` | the Scan workflow | journals |

## Rules that hold in every session

- **Never fake confidence.**
  - A TRADE must come from governed evidence.
  - Zero trades is a valid answer.
  - Never write "guaranteed", "risk-free", "certain", "proven profit" or "guaranteed edge". Funding spreads are not
    risk-free.
- **Never merge to `main` and never mark a PR ready without the owner's explicit approval.** Work on a branch named
  `v9/...` and open a draft PR.
- **Never add wallet keys, exchange credentials, order placement or secrets.** API keys for free data sources live
  only in repository secrets.
- **Published-page or engine output changes need a pinned delta manifest and a new legacy-parity golden.** See
  `tools/v8/legacy_parity.py` and `tools/v8/delta_parity.py`. Never update a golden to hide unexplained drift.
  - v9 uses `tests/fixtures/v8/legacy_parity_golden_v9b.json` and `tests/fixtures/v8/v9b_expected_deltas.json`, with
    main `fe68203` as the base.
  - `tests/test_v9_scope.py` lists every file and function v9 may change.
- **The probation tier is bound to `quant.py`'s bytes.** Any `quant.py` edit invalidates it (fail closed) until you run
  `python tools/v9/confirm.py --from-branch evidence-results` and put the new evidence `sha256` into
  `v8/quant_strategy_policy.json`.
  - Never edit a shadow-ledger record. A changed forward test is a new registration
    (`tools/v9/register_forward_test.py`).
  - Do not edit the research files the evidence is bound to (`confirm.RESEARCH_CODE`: `tools/v9/evidence.py`,
    `archive_fetch.py`, `tools/research/qsim.py`, `qstrat.py`, `qdata.py`, `qind.py`). New studies go in new files
    that import them, as `tools/v9/d1.py` does.
- **New research is pre-registered** (HANDOVER phase D): the definitions are committed before any run on market data,
  tested once, and recorded as they come out. Strategy names must not collide with the legacy catalogue.
- **The local clone is shallow.** `tests.test_accuracy_invariants...test_trial_census_and_candidate_count_unchanged`
  walks git history and fails here only. CI runs it on a full clone.
- **Run the suites before every push:** `python -m unittest discover -s tests`. The CI research-checks job runs the
  numba tests.
- **Commit and PR attribution:** follow the session's system instructions.
