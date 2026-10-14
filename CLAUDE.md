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
  run in GitHub Actions. Read their results by fetching the results branches, for example
  `git fetch origin probe-results evidence-results archive-data` and then `git show origin/<branch>:<file>`.
  Actions job logs and artifacts cannot be downloaded from here (blob storage is blocked), so each job commits its
  results to a branch.
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
- **Run the suites before every push:** `python -m unittest discover -s tests`. The CI research-checks job runs the
  numba tests.
- **Commit and PR attribution:** follow the session's system instructions.
