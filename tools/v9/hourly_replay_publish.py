"""Retain an A5 replay attempt, including fatal failures, for durable recording."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.v9 import hourly_replay as R

PROTOCOL = 'docs/v9/phase-a5-replay-publication.md'


def retain(archive, out):
    archive, out = Path(archive), Path(out)
    if out.exists(): raise FileExistsError('refuse to replace a previous replay attempt')
    error = None
    try:
        evidence = R.run(archive, out)
    except Exception as exc:
        out.mkdir(parents=True, exist_ok=True)
        evidence = None
        error = f'{type(exc).__name__}: {exc}'
        if not (out/'failure.json').exists():
            R.write_json(out/'failure.json', dict(error=error, replay_complete=False, promotion_authority=False))
    artifacts = {p.name:R.sha(p) for p in sorted(out.iterdir()) if p.is_file()}
    attempts = {name:digest for name,digest in artifacts.items() if name.endswith('.jsonl.gz')}
    R.write_json(out/'attempts_a5.json', attempts)
    artifacts['attempts_a5.json'] = R.sha(out/'attempts_a5.json')
    protocols = [PROTOCOL, R.PROTOCOL, 'docs/v9/phase-a5-execution-contract.md',
                 'docs/v9/phase-a5-feature-state.md', 'docs/v9/phase-a5-signal-integration.md',
                 'docs/v9/phase-a5-funding-disposition.md']
    failed_segments = sum(t['failed_segments'] for t in evidence['trials'].values()) if evidence else None
    status = 'FAILED' if error else ('PARTIAL_FAILURE' if failed_segments else 'COMPLETED_WITH_UNAVAILABLE_RESULTS')
    result = dict(schema='v9.a5-replay-run/1', status=status, error=error,
                  dataset_sha256=R.MANIFEST_SHA, data_commit=R.DATA_COMMIT,
                  actual_manifest_sha256=R.sha(archive/'quality_candidate_manifest.json')
                    if (archive/'quality_candidate_manifest.json').is_file() else None,
                  preregistration=PROTOCOL, preregistration_sha256=R.sha(ROOT/PROTOCOL),
                  preregistrations_sha256={p:R.sha(ROOT/p) for p in protocols},
                  publisher_sha256=R.sha(Path(__file__)), driver_manifest_retained=evidence is not None,
                  artifacts_sha256=artifacts, confirmed=[], promotion_authority=False,
                  known_trial_return_matrix_complete=False, historical_trial_census_complete=False,
                  trials=evidence['trials'] if evidence else None)
    lines=['# A5 hourly replay attempt', '', 'Status: '+status, '',
           'Dataset: `'+R.DATA_COMMIT+'`', '',
           'Research diagnostics only. No strategy is confirmed; no promotion authority.',
           'Full-family return evidence remains incomplete. Funding coverage is unknown.',
           'Retrospective quality, continuous-volume warm-up and entry observability restrictions apply.',
           'FUND_FADE is conditional on observed events; FUND_CARRY remains unavailable.', '']
    if error: lines += ['Failure: '+error, '']
    if evidence:
        lines += ['| Trial | Status | Attempts | Failed segments | Net series |', '|---|---|---:|---:|---|']
        for alias,t in sorted(evidence['trials'].items()):
            lines.append(f"| {alias} | {t['status']} | {sum(t['attempt_counts'].values())} | {t['failed_segments']} | {'available within restrictions' if t['net_series_available'] else 'unavailable'} |")
    (out/'REPORT_A5.md').write_text('\n'.join(lines)+'\n',encoding='utf8')
    R.write_json(out/'replay_run.json', result)
    return result


if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--archive',required=True);p.add_argument('--out',required=True)
    result=retain(**vars(p.parse_args()))
    print(result['status'])  # publish failures before the workflow reports failure
