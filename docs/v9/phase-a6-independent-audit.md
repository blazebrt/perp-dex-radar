# A6 independent extraction audit

Registered before the first market extraction. `audit_control_extraction.py`
checks a retained extraction; it does not run execution, matching or outcomes.

The caller supplies the full extraction source commit, original broad archive,
phase-B evidence, retained extraction directory and a separate empty audit
directory. The audit compares the six unchanged research files against A4's
original source commit and verifies that the extraction commit contains those
same files. Its census and dispute inventory must have the frozen hashes.
The phase-B evidence must match the extraction source's retained binding.

An independent reader verifies every original candle file and universe hash,
segment identity, bounds and row count, then constructs source indexes without
using the A6 extraction, feature or source-loading helpers. The unchanged legacy
panel and feature constructor recreate the phase-B array fingerprint and exact
study window. Expected extraction provenance is reconstructed from these inputs
and the extraction commit's adapter/protocol bytes, never accepted from the
result's self-description.

Artifact accounting runs first. For each successfully extracted four-hour/daily
trial, the audit invokes the unchanged original generator once with its exact
registered parameters and independently reconciles every retained ordinal,
geometry, eligibility, source feature and history annotation. This is a repeat
calculation for verification, not another strategy test: no outcomes, selection,
inference, or changed parameters are introduced. Failed trials and seven hourly
populations are explicitly not population-verified. The original generator
mathematics are reused, not independently validated.

The audit preserves extraction bytes and refuses to overwrite previous audit
output. Failures retain a separate failure record where storage permits, and
successful reports are installed only after the complete report is written.
Partial temporary files are not success markers. Even an audit of all available
trials cannot establish complete family evidence or promotion authority.

The durable Actions publisher and duplicate-attempt guard remain prerequisites
to the first extraction. Extraction and audit outputs must both be retained,
including failures, and independently inspected before A6.2 is marked complete.
