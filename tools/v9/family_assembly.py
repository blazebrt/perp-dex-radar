"""Fixed-input A4/A5 inventory. No simulations, imputation or new statistics."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.v9 import record_run

A4 = '18c14932bcc2ba9e8685f231e1725a786869edd9'
A5 = '84412b14ae8a1dee7299c2ebdbb32a45ac5d0e0e'
SPEC = 'docs/v9/phase-a4-family-assembly.md'
PLAN = 'research/v9/census_replay_plan.json'
VERIFICATION = 'research/v9/a5_replay_verification.json'
RESTRICTIONS = [
    'Broad four-hour/daily universe versus causal top-150 hourly universe.',
    'Legacy four-hour simulator versus explicit gap-aware hourly execution.',
    'Hourly funding completeness is unknown; price exits are not net returns.',
    'FUND_FADE is observed-event conditional; two segments are unavailable.',
    'FUND_CARRY is unavailable for causal quorum mapping, not a zero-return trial.',
    'Hourly retrospective quality exclusions and entry embargoes apply.',
    'Hourly continuity and positive-volume warm-up resets apply.',
    'Historical trial census remains incomplete; no promotion authority.',
]


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def checked(data, expected, name):
    require(digest(data) == expected, 'hash mismatch: ' + name)
    return data


def git_read(repo, commit, path):
    return subprocess.check_output(['git', '-c', 'safe.directory=*', '-C', str(repo),
                                    'show', f'{commit}:{path}'])


def validate(plan, a4, a5, matrix_bytes, verification):
    """Validate decoded evidence independently of transport and output writing."""
    trials = plan['trials']
    ids = [t['trial_id'] for t in trials]
    require(len(ids) == len(set(ids)) == 199, 'expected 199 unique trial IDs')
    hourly = [t for t in trials if t['archive_requirement'] == 'hourly']
    require(len(hourly) == 7 and sum(t['archive_requirement'] == '4h' for t in trials) == 192,
            'expected 192 four-hour and seven hourly definitions')
    require([t['trial_id'] for t in a4['trials']] == ids, 'A4 trial order mismatch')
    require(a4['window'] == a5['window'], 'study window mismatch')
    start, end = a4['window']
    require(all(type(v) is int and v % 86400 == 0 for v in (start, end)) and end >= start,
            'invalid study window')
    with np.load(io.BytesIO(matrix_bytes), allow_pickle=False) as data:
        require(set(data.files) == {'days', 'trial_ids', 'returns'}, 'matrix keys mismatch')
        days, names, values = data['days'], data['trial_ids'], data['returns']
    require(names.tolist() == ids, 'matrix trial order mismatch')
    require(days.dtype.kind in 'iu' and np.array_equal(days, np.arange(start // 86400, end // 86400 + 1)),
            'matrix calendar mismatch')
    require(values.shape == (len(days), 199) and values.dtype.kind == 'f', 'matrix shape/type mismatch')
    for doc in (a4, a5):
        require(all(doc[k] is False for k in ('promotion_authority',
                'historical_trial_census_complete', 'known_trial_return_matrix_complete'))
                and doc['confirmed'] == [], 'unexpected authority or completeness')
    stats = a4['all_known_trials']
    require(all(stats[k]['status'] == 'UNAVAILABLE_INSUFFICIENT_DATA' and stats[k].get('reason')
                for k in ('dsr', 'pbo', 'bootstrap')) and stats['trial_sharpe_variance'] is None,
            'full-family statistic unexpectedly available')
    aliases = {t['aliases'][0]: t for t in hourly}
    require(len(aliases) == 7 and set(a5['trials']) == set(aliases), 'hourly identities mismatch')
    require(verification['result_commit'] == A5 and verification['full_family_complete'] is False
            and verification['promotion_authority'] is False, 'verification identity mismatch')
    reports = verification['reports']
    require(reports['artifact']['all_artifact_hashes_verified'] is True
            and reports['artifact']['trial_accounting_verified'] is True
            and reports['price']['every_retained_attempt_reconciled'] is True
            and reports['signal']['every_successfully_generated_segment_population_reconciled'] is True,
            'independent verification incomplete')
    columns = []
    for k, trial in enumerate(trials):
        item = dict(trial_id=ids[k], aliases=trial['aliases'], definition=trial,
                    matrix_column=k, source_commit=A4)
        if trial['archive_requirement'] == '4h':
            require(a4['trials'][k]['status'] == 'REPLAYED' and np.isfinite(values[:, k]).all(),
                    'non-finite or incomplete four-hour column')
            item.update(status='DIAGNOSTIC_LEGACY_RETURN_SERIES', a4_summary=a4['trials'][k])
        else:
            require(a4['trials'][k]['status'] == 'PENDING_A5_HOURLY_ARCHIVE'
                    and np.isnan(values[:, k]).all(), 'hourly column must be wholly missing')
            alias = trial['aliases'][0]
            h = a5['trials'][alias]
            require(h['trial_id'] == ids[k] and h['params'] == trial['params'], 'hourly definition mismatch')
            expected = ('UNAVAILABLE_CAUSAL_QUORUM_MAPPING' if alias == 'FUND_CARRY' else
                        'UNAVAILABLE_PARTIAL_REPLAY' if alias == 'FUND_FADE' else 'REPLAYED')
            require(h['status'] == expected and h['net_series_available'] is False,
                    'unexpected hourly availability')
            require(h['daily_net_R'] == [dict(day=int(d) * 86400, net_R=None) for d in days],
                    'hourly daily values/calendar mismatch')
            v = reports['artifact']['trials'][alias]
            counts = h['attempt_counts']
            require(all(type(n) is int and n >= 0 for n in counts.values())
                    and counts == v['counts'] and sum(counts.values()) == v['attempts'],
                    'hourly attempt accounting mismatch')
            require(all(h[key] == v[key] for key in ('segments', 'failed_segments', 'unavailable_segments'))
                    and h['failed_segments'] == 0, 'hourly segment accounting mismatch')
            item.update(status='UNAVAILABLE_NET_RETURN_SERIES', hourly_source_commit=A5,
                        hourly_summary={key: value for key, value in h.items() if key != 'daily_net_R'},
                        attempts=v['attempts'], funding_coverage=a5['funding_coverage'])
        columns.append(item)
    return columns, len(days)


def prepare(repo):
    """Load only pinned Git objects, checking history and every used input binding."""
    repo = Path(repo)
    inputs = {}
    def local(name):
        data = (repo / name).read_bytes()
        inputs[name] = digest(data)
        return data
    lines = local(record_run.HISTORY).decode().splitlines()
    require(not record_run.verify(lines) and len(lines) >= 5, 'invalid evidence history')
    records = [json.loads(line) for line in lines]
    four, hour = records[3:5]
    require((four['study'], four['results_commit'], hour['study'], hour['results_commit']) ==
            ('A4', A4, 'A5', A5), 'source identity mismatch')
    def source(commit, name, expected):
        data = checked(git_read(repo, commit, name), expected, name)
        inputs[commit + ':' + name] = digest(data)
        return data
    a4 = json.loads(source(A4, 'evidence_a4.json', four['files']['evidence']))
    outer = json.loads(source(A5, 'replay_run.json', hour['files']['evidence']))
    a5 = json.loads(source(A5, 'evidence_a5.json', outer['artifacts_sha256']['evidence_a5.json']))
    attempts = json.loads(source(A5, 'attempts_a5.json', hour['files']['trades']))
    require(attempts == a5['artifacts_sha256'] and outer['trials'] == a5['trials'],
            'A5 manifests disagree')
    require(outer['artifacts_sha256']['attempts_a5.json'] == hour['files']['trades']
            and outer['status'] == 'COMPLETED_WITH_UNAVAILABLE_RESULTS'
            and outer['data_commit'] == a5['data_commit']
            and outer['dataset_sha256'] == a5['dataset_sha256'] == hour['dataset_sha256'],
            'A5 source/dataset binding mismatch')
    for name, sha in attempts.items():
        require(outer['artifacts_sha256'][name] == sha, 'attempt binding mismatch')
        source(A5, name, sha)
    matrix = source(A4, 'daily_returns.npz', a4['artifacts']['daily_returns.npz'])
    plan_bytes = local(PLAN)
    checked(plan_bytes, a4['provenance']['plan_sha256'], PLAN)
    checked(plan_bytes, a5['source_sha256'][PLAN], PLAN)
    spec = local(SPEC)
    checked(spec, digest(git_read(repo, '8cf208d30c073ec88b7ce3789c3f5bddca694c05', SPEC)), SPEC)
    verification = json.loads(local(VERIFICATION))
    for name, sha in verification['verifier_sha256'].items():
        checked(local(name), sha, name)
    columns, days = validate(json.loads(plan_bytes), a4, a5, matrix, verification)
    return dict(matrix=matrix, columns=columns, days=days, input_sha256=inputs,
                specification_sha256=digest(spec), inherited_statistics=a4['all_known_trials'])


def write_output(prepared, out):
    out = Path(out)
    require(not out.exists() or not any(out.iterdir()), 'output must be empty')
    out.mkdir(parents=True, exist_ok=True)
    def write(name, value):
        (out / name).write_bytes((json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + '\n').encode())
    try:
        (out / 'daily_returns.npz').write_bytes(prepared['matrix'])
        write('columns.json', prepared['columns'])
        report = ('# A4/A5 combined inventory\n\n192 diagnostic return columns; seven hourly columns remain '
                  'unavailable. All 199 identities are retained. This is not a common-universe experiment.\n\n'
                  'Full-family DSR/PBO/bootstrap dispositions are inherited as unavailable from A4; '
                  'no statistic or strategy was rerun. No promotion authority.\n\n' +
                  '\n'.join('- ' + restriction for restriction in RESTRICTIONS) + '\n')
        (out / 'REPORT.md').write_bytes(report.encode())
        manifest = {k: v for k, v in prepared.items() if k not in ('matrix', 'columns')}
        manifest.update(schema='v9.family-assembly/1', sources={'A4': A4, 'A5': A5},
                        evidence_history_entries=[4, 5], columns=199, available_diagnostic_columns=192,
                        unavailable_columns=7, statistics_recomputed=False,
                        diagnostic_subset_reference=A4 + ':evidence_a4.json#diagnostic_4h_subset',
                        common_universe_experiment=False, historical_trial_census_complete=False,
                        known_trial_return_matrix_complete=False, promotion_authority=False, confirmed=[],
                        restrictions=RESTRICTIONS, tool_sha256=digest(Path(__file__).read_bytes()),
                        artifacts_sha256={name: digest((out / name).read_bytes())
                                          for name in ('daily_returns.npz', 'columns.json', 'REPORT.md')})
        write('assembly.json', manifest)
        return manifest
    except Exception as exc:
        (out / 'assembly.json').unlink(missing_ok=True)
        write('failure.json', dict(error=type(exc).__name__, message=str(exc)))
        raise


def run(repo, out):
    # Keep preflight failures as evidence too, without overwriting a prior output.
    out = Path(out)
    require(not out.exists() or not any(out.iterdir()), 'output must be empty')
    try:
        prepared = prepare(repo)
    except Exception as exc:
        out.mkdir(parents=True, exist_ok=True)
        (out / 'failure.json').write_bytes((json.dumps(dict(error=type(exc).__name__, message=str(exc))) + '\n').encode())
        raise
    return write_output(prepared, out)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', default=str(ROOT))
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    run(args.repo, args.out)
