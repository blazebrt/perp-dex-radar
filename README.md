# v8-history (v8.history/1)

Append-only point-in-time history written by the production Scan workflow (`python -m v8.snapshot
--history-branch v8-history`). One gzip JSON observation per scan under `obs/<YYYY>/<MM>/<DD>/`, chained by
`prev_hash`. Never force-pushed, never rewritten, never deleted. See docs/v8/phase8-point-in-time-research.md on main.
Verify: `python -m v8.history verify --dir <checkout of this branch>`.
