"""Plan the complete known-trial replay without importing/executing qgrid or reading market data."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools' / 'research'))
import strategy_census as census

CENSUS = 'research/phase9/research_strategy_trial_census.json'


def build(root=ROOT):
    root = Path(root)
    raw = (root / CENSUS).read_bytes()
    doc = json.loads(raw)
    rows = doc['trials']
    if len(rows) != doc['known_lower_bound'] or len({r['trial_id'] for r in rows}) != len(rows):
        raise ValueError('census count or unique trial IDs disagree')
    source = (root / 'tools/research/qstrat.py').read_text(encoding='utf8')
    defs = census.defaults(source)
    # The exported catalogue declares the data resolution. Do not guess from a
    # parameter name: daily rotations also have no explicit tf parameter.
    export = census.assignment((root / 'tools/research/qexport.py').read_text(encoding='utf8'), 'TESTED')
    resolutions = {}
    for value in export.values:
        fn = value.elts[0].attr
        kw = census.static(value.elts[1])
        tf = census.static(value.elts[4])
        resolutions.setdefault((fn, kw.get('tf', defs[fn].get('tf'))), set()).add(tf)
    current_hash = census.digest({p: hashlib.sha256((root / p).read_bytes()).hexdigest()
                                  for p in census.CODE_FILES})
    planned = []
    for row in rows:
        fn, params = row['implementation'], row['params']
        if fn not in defs or set(params) != set(defs[fn]):
            raise ValueError('unknown implementation or parameter schema: ' + fn)
        if census.digest(params) != row['parameter_hash']:
            raise ValueError('parameter hash mismatch')
        expected_id = census.digest(dict(implementation=fn, parameter_hash=row['parameter_hash'],
                                        code_hash=row['code_hash']))
        if row['trial_id'] != expected_id:
            raise ValueError('trial identity mismatch')
        possible = resolutions.get((fn, params.get('tf')), set())
        if len(possible) != 1:
            raise ValueError('ambiguous or missing timeframe: ' + fn)
        timeframe = next(iter(possible))
        if timeframe not in ('1h', '4h', '1d'):
            raise ValueError('unsupported timeframe: ' + timeframe)
        planned.append(dict(row, timeframe=timeframe,
                            archive_requirement='hourly' if timeframe == '1h' else '4h',
                            replay_code_hash=current_hash,
                            historical_code_matches_replay=row['code_hash'] == current_hash))
    planned.sort(key=lambda r: r['trial_id'])
    hourly = [r['trial_id'] for r in planned if r['archive_requirement'] == 'hourly']
    return dict(schema='v9.census-replay-plan/1', census_sha256=hashlib.sha256(raw).hexdigest(),
                known_trials=len(planned), historical_trial_census_complete=False,
                known_trial_return_matrix_complete=False, replay_code_hash=current_hash,
                ready_4h_trials=len(planned)-len(hourly), hourly_trials_pending_A5=hourly,
                trials=planned,
                interpretation='Replay of known definitions under the pinned current simulator; '
                'not recovered historical returns and not evidence of unknown trial completeness.',
                promotion_authority=False)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out', required=True)
    args = ap.parse_args()
    plan = build()
    path = Path(args.out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(plan, sort_keys=True, indent=2) + '\n', encoding='utf8')
    print(f"{plan['known_trials']} known trials: {plan['ready_4h_trials']} ready for 4h replay; "
          f"{len(plan['hourly_trials_pending_A5'])} require A5 hourly data")


if __name__ == '__main__':
    main()
