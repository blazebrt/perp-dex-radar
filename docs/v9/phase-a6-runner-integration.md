# A6 runner integration: inactive pending qualification

`control_outcome_runner.py` connects the authenticated reservation API, the job
coordinator and the immutable input adapter. The inactive template
`docs/v9/a6-outcome.workflow.yaml` references it; GitHub does not execute files
from this documentation directory.
Do not activate it until independently reviewed representative hosted resource
and publication qualification exists and matches the exact source commit.
Environment checks prevent accidental misuse; they are not authentication or
proof that a qualification report is truthful.

The intended job uses ubuntu-24.04, hosted Linux/X64, a clean full checkout of
`v9/census-evidence`, attempt one, and the fixed repository. Its Actions token
needs contents-write access. Pass the reviewed report file and its independently
pinned SHA-256, never a hash computed from an unreviewed report at launch.
The report must be supplied separately from the source commit it qualifies.

Capture an absolute deadline at job start, before checkout/install/preflight,
within the actual configured timeout (at most 360 minutes). Pass that same
Unix timestamp as `--deadline-epoch`; do not refresh it for later steps.
The capacity callback subtracts current time on each check. Qualification must
cover preparation, study, audits and retention. The existing preflight reserves
40% of remaining time, but is not an enforced process deadline or resource cap.

The CLI accepts `--qualification`, `--qualification-sha256` and
`--deadline-epoch`. Source/run identity and token come from the runner environment.
It creates a fresh `$RUNNER_TEMP/a6-outcome-<run_id>-1/`, with inputs separate from
`job/`. Reuse is refused. It exits successfully only for retained diagnostics
with reservation and publication verification; that status grants no strategy
or net-return authority.

The future workflow must always back up `job/` after failures, including when
reservation creation may have succeeded but read-back failed. Preserve local
commit objects if publication failed. A killed runner may leave only the remote
reservation; recovery inspects it and never silently repeats the study. Evidence
history recording and independent retained-result reconciliation remain required
after the single application. No market attempt or hosted qualification is
established by the mocked runner tests.

## Inactive workflow and recovery bundle

The template is manual-only, with branch/repository/attempt guards and serialized
non-cancelling concurrency. It captures a 350-minute deadline before setup inside
a 360-minute job, leaving ten minutes beyond that deadline for recovery steps.
Always-run backup steps preserve job files and a self-contained bundle of the
recorded result (or reservation). The bundle helper verifies ancestry and removes
its temporary local ref; it neither pushes nor changes a persistent branch.
An uploaded artifact is not a replacement for verified result-branch publication.

The reviewed qualification commit must contain
`research/v9/a6-resource/qualification.json` and `requirements.lock`.
The template independently checks both supplied hashes and requires the report
to bind the dependency-lock hash, exact Python version and runner image version.
Installation uses pip's hash-required mode. Neither a qualifying report nor a
reviewed lock currently exists. Pin action revisions and verify the final hosted
image/dependencies during qualification before installing/activating the template.
Moving the template changes the source commit; qualification must cover the exact
final source used for the single attempt. Activation and source-pinning review
remain unresolved until that sequence is established.

## Entry-point runtime binding

The runner itself now checks the independently supplied qualification hash before
constructing its reservation API client or creating the fresh workspace. It parses
the reviewed JSON strictly (duplicate keys and nonfinite values refused), then
requires the supported qualification schema, exact source commit, hosted runner
profile, current Python version and nonempty matching ImageVersion. Direct calls
cannot bypass these checks by skipping the inactive workflow's setup step.

This does not attest the image independently or verify installed-file integrity.
The workflow's reviewed hash-locked installation and full resource preflight remain
required. The observed setup-log/environment image discrepancy is unresolved; no
qualifying report is created by this change. Mismatch tests verify refusal before
API construction, job execution and workspace creation.

## Installed package version inventory

The reviewed qualification report must also include `installed_distributions`, a
nonempty object mapping normalized package names to exact installed version strings.
Capture the complete visible environment during qualification, including installer
and tooling distributions. Names use lowercase with runs of dots, underscores and
hyphens normalized to a single hyphen. The runner compares this inventory with
`importlib.metadata.distributions()` before reservation setup. Missing, extra,
changed, duplicate and ambiguous metadata refuse execution; there is no subset or
best-effort acceptance. The map is covered by the independently reviewed report hash.

This detects version drift, not tampered package files or import-path shadowing.
Hash-required installation and an independently reviewed environment remain required.
Do not invent an approved inventory from the current pilot: transitive dependency
locking and image reconciliation are still incomplete. Synthetic tests alone do not
qualify the environment or authorize a study.
