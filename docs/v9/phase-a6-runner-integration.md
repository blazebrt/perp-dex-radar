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

## Candidate lock generation and hosted validation

The read-only `a6_dependency_probe.yml` workflow resolves wheel-only candidates for
the existing numerical stack plus explicitly selected pip/setuptools/wheel versions.
`control_dependency_lock.py` reads bounded wheel metadata and records SHA-256 for
every wheel, emitting a fully pinned `requirements.lock` and manifest. These hashes
bind downloaded bytes; they do not establish publisher trust or independent approval.

The hosted probe installs from the retained local wheels into a fresh virtual
environment using `--no-index --require-hashes --only-binary=:all:` and forced
reinstallation. It checks dependencies, exact complete package inventory and numerical
imports, then runs the eight synthetic scenarios. Wheel and diagnostic artifacts are
retained separately for review, including on failure. No source distributions are built.
This follows [pip's hash-checking installation requirements](https://pip.pypa.io/en/stable/topics/secure-installs/).

The candidate remains separate from the inactive market workflow. Hosted success,
independent review, image reconciliation and full resource/publication qualification
are still needed; no approved lock or market authorization is implied by preparation.

### Verified candidate run

[Run 40497702104](https://github.com/blazebrt/perp-dex-radar/actions/runs/40497702104)
at `a843e92abe81bd5a498e258617166f24472b16fa` passed the fresh offline install,
complete 11-package inventory, dependency consistency, numerical imports and eight
synthetic pipeline cases. Both artifact ZIP digests and every wheel size/hash were
independently checked after download. The lock's SHA-256 is
`07a46148d00b0416c05539451ec2fb7deca0e99f9c846ad3ccbb4c9e49a34475`.
Original candidate files and measurement/provenance records are under
`research/v9/a6_dependency_candidate*`. The 79 MB wheel artifact is retained by
Actions until 2027-01-25; it is not committed as a binary payload in the source PR.

This is a candidate for independent review, not the approved lock used by the
inactive market workflow. Image metadata remains inconsistent between setup logs
and runtime. Durable wheel storage, reviewed reuse and representative resource and
remote-publication qualification remain open. The synthetic result grants no market
study or promotion authority.
