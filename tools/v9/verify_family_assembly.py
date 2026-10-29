"""Independent read-only comparison of a retained assembly with original Git objects."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import subprocess

import numpy as np


def verify(repo, directory):
    repo, directory = Path(repo), Path(directory)
    def show(commit, name):
        return subprocess.check_output(['git', '-c', 'safe.directory=*', '-C', str(repo),
                                        'show', commit + ':' + name])
    def sha(data):
        return hashlib.sha256(data).hexdigest()
    def check(ok, label):
        if not ok:
            raise ValueError('independent comparison failed: ' + label)
    a4 = '18c14932bcc2ba9e8685f231e1725a786869edd9'
    a5 = '84412b14ae8a1dee7299c2ebdbb32a45ac5d0e0e'
    manifest_bytes = (directory/'assembly.json').read_bytes()
    manifest = json.loads(manifest_bytes)
    check(manifest['sources'] == {'A4': a4, 'A5': a5}, 'sources')
    for name, expected in manifest['artifacts_sha256'].items():
        check(sha((directory/name).read_bytes()) == expected, name + ' hash')
    for name, expected in manifest['input_sha256'].items():
        if ':' in name:
            commit, path = name.split(':', 1)
            data = show(commit, path)
        else:
            data = (repo/name).read_bytes()
        check(sha(data) == expected, name + ' input hash')
    source_matrix = show(a4, 'daily_returns.npz')
    result_matrix = (directory/'daily_returns.npz').read_bytes()
    check(source_matrix == result_matrix, 'exact matrix bytes')
    with np.load(io.BytesIO(source_matrix), allow_pickle=False) as source, np.load(io.BytesIO(result_matrix), allow_pickle=False) as result:
        for name in ('days', 'trial_ids', 'returns'):
            np.testing.assert_array_equal(source[name], result[name])
        shape = result['returns'].shape
        ids = result['trial_ids'].tolist()
        missing = np.isnan(result['returns']).all(axis=0)
        check(shape == (2346, 199) and missing.sum() == 7, 'matrix dimensions/missing columns')
        check(np.isfinite(result['returns'][:, ~missing]).all(), 'finite diagnostic columns')
    columns = json.loads((directory/'columns.json').read_bytes())
    plan = json.loads((repo/'research/v9/census_replay_plan.json').read_bytes())
    four = json.loads(show(a4, 'evidence_a4.json'))
    hour = json.loads(show(a5, 'evidence_a5.json'))
    check([c['trial_id'] for c in columns] == ids, 'all column identities')
    for k, (column, trial) in enumerate(zip(columns, plan['trials'])):
        check(column['definition'] == trial and column['matrix_column'] == k
              and column['source_commit'] == a4, 'definition/order/source')
        if trial['archive_requirement'] == '4h':
            check(column['a4_summary'] == four['trials'][k] and not missing[k]
                  and column['status'] == 'DIAGNOSTIC_LEGACY_RETURN_SERIES', 'four-hour summary')
        else:
            original = hour['trials'][trial['aliases'][0]]
            check(column['hourly_summary'] == {key:value for key,value in original.items() if key != 'daily_net_R'},
                  'complete hourly metadata')
            check(column['attempts'] == sum(original['attempt_counts'].values()) and missing[k]
                  and column['hourly_source_commit'] == a5
                  and column['status'] == 'UNAVAILABLE_NET_RETURN_SERIES', 'hourly disposition')
    check(manifest['inherited_statistics'] == four['all_known_trials'], 'inherited statistics')
    check(all(manifest[k] is False for k in ('statistics_recomputed', 'promotion_authority',
              'common_universe_experiment', 'historical_trial_census_complete',
              'known_trial_return_matrix_complete')) and manifest['confirmed'] == [], 'authority')
    return dict(schema='v9.family-assembly-verification/1', sources=manifest['sources'],
                assembly_sha256=sha(manifest_bytes), matrix_bytes_identical=True,
                compared_cells=shape[0]*shape[1], days=shape[0], columns=shape[1],
                unavailable_columns=7, every_column_metadata_reconciled=True,
                inherited_statistics_unchanged=True, promotion_authority=False,
                verifier_sha256=sha(Path(__file__).read_bytes()))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', required=True)
    parser.add_argument('--directory', required=True)
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    result = verify(args.repo, args.directory)
    with Path(args.out).open('x', encoding='utf8', newline='\n') as output:
        output.write(json.dumps(result, indent=2, sort_keys=True) + '\n')
