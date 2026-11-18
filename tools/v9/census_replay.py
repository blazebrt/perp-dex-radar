"""A4 known-definition replay; diagnostic only, never deployment authority.

python tools/v9/census_replay.py --md md_bn --out census-results --phase-b-evidence phase_b.json
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tools/research'))
from tools.v9 import census_plan
import multiple_testing as MT

DAY = 86400
PLAN = ROOT / 'research/v9/census_replay_plan.json'
PROTOCOL = ROOT / 'docs/v9/phase-a4-replay-protocol.md'
BINDING = ROOT / 'research/v9/probation_evidence.json'


def digest_panel(panel):
    """Phase B's exact array digest, including its column ordering."""
    sha = hashlib.sha256()
    for arr in (panel.t, panel.o, panel.h, panel.l, panel.c, panel.v, panel.fund):
        sha.update(np.ascontiguousarray(arr).tobytes())
    return sha.hexdigest()


def daily_returns(rows, start, end):
    """Realize R on exit day, including an exit exactly at the archive's end.

    Zero means a successfully replayed trial had no exit that day. Missing
    trials are handled separately, never passed here as an empty substitute.
    """
    if end <= start:
        raise ValueError('empty replay window')
    result = np.zeros(end // DAY - start // DAY + 1)
    for row in rows:
        decision, exit_time, net = row['decision_time'], row['exit_time'], row['net_R']
        if (not isinstance(decision, int) or isinstance(decision, bool)
                or not isinstance(exit_time, int) or isinstance(exit_time, bool)
                or not start <= decision <= exit_time <= end or not np.isfinite(net)):
            raise ValueError('invalid trade time or return')
        result[exit_time // DAY - start // DAY] += net
    return result


def family_statistics(matrix, names, provenance, replications=5000):
    """Never silently drop missing or constant columns to obtain a statistic."""
    matrix = np.asarray(matrix, dtype=float)
    if matrix.ndim != 2 or matrix.shape[1] != len(names) or len(set(names)) != len(names):
        raise ValueError('unique names must match matrix columns')
    unavailable = MT.unavailable('every planned trial needs a finite common daily series')
    if len(matrix) < 3 or len(names) < 2 or not np.isfinite(matrix).all():
        return dict(dsr=unavailable, pbo=unavailable, bootstrap=unavailable,
                    trial_sharpe_variance=None)
    deviations = matrix.std(axis=0, ddof=1)
    variance = None
    if (deviations > 0).all():
        variance = float(np.var(matrix.mean(axis=0) / deviations, ddof=1))
    dsr = {name: MT.dsr(matrix[:, k], len(names), variance, complete=False)
           for k, name in enumerate(names)}
    return dict(dsr=dsr, trial_sharpe_variance=variance,
                pbo=MT.pbo(matrix, names, 16, 14),
                bootstrap=MT.bootstrap_tests(matrix, provenance, replications, 7))


def replay(panel, features, universe, plan, start, end, simulate, trade_sink):
    """Run every 4h/daily definition, retaining all hourly columns as missing.

    The injected simulator and sink allow small, independent accounting tests.
    Any exception aborts; no failed trial is turned into a zero-return series.
    """
    trials = plan['trials']
    matrix = np.full((end // DAY - start // DAY + 1, len(trials)), np.nan)
    summaries = []
    for k, trial in enumerate(trials):
        tid = trial['trial_id']
        if trial['archive_requirement'] == 'hourly':
            summaries.append(dict(trial_id=tid, status='PENDING_A5_HOURLY_ARCHIVE', trades=None))
            continue
        if trial['archive_requirement'] != '4h':
            raise ValueError('unsupported archive requirement')
        signals, raw_rows = simulate(panel, features, trial, universe)
        # Same warm-up rule as phase B; do not silently remove late or invalid exits.
        rows = [r for r in raw_rows if r['decision_time'] >= start]
        matrix[:, k] = daily_returns(rows, start, end)
        trade_sink(tid, rows)
        summaries.append(dict(trial_id=tid, status='REPLAYED', signals=signals, trades=len(rows),
                              total_net_R=float(matrix[:, k].sum())))
        print(f'{k+1}/{len(trials)} {tid[:12]} replayed: {len(rows)} trades', flush=True)
    return matrix, summaries


def run(md, out, phase_b_evidence, replications=5000):
    from tools.v9 import evidence as EV
    import qstrat

    plan = json.loads(PLAN.read_text(encoding='utf8'))
    if plan != census_plan.build():
        raise ValueError('committed replay plan no longer matches code or census')
    reference_bytes = Path(phase_b_evidence).read_bytes()
    binding = json.loads(BINDING.read_text(encoding='utf8'))['inputs']['evidence_sha256']
    if hashlib.sha256(reference_bytes).hexdigest() != binding:
        raise ValueError('phase B reference does not match committed evidence binding')
    reference = json.loads(reference_bytes)
    expected = (reference.get('provenance') or {}).get('dataset_sha256')
    if not isinstance(expected, str) or len(expected) != 64:
        raise ValueError('phase B dataset digest required')
    panel = EV.ArchivePanel(str(md))
    # Phase B fingerprints AFTER Feat: resample marks incomplete daily opens
    # through numpy views of the panel. Match that existing construction order.
    features = qstrat.Feat(panel)
    dataset = digest_panel(panel)
    if dataset != expected:
        raise ValueError(f'dataset does not match phase B; replay refused ({dataset} != {expected})')
    with (Path(md) / 'universe.json').open(encoding='utf8') as fh:
        universe = {row['t']: row for row in json.load(fh)['coins']}
    if not set(panel.coins) <= set(universe):
        raise ValueError('panel coins missing from universe')
    start, end = int(panel.t[0]) + EV.WARMUP_DAYS * DAY, int(panel.t[-1]) + EV.BAR
    if end <= start:
        raise ValueError('archive shorter than warm-up')
    destination = Path(out)
    if destination.exists() and any(destination.iterdir()):
        raise ValueError('output directory must be empty; preserve prior evidence')
    destination.mkdir(parents=True, exist_ok=True)

    def simulate(p, f, trial, uni):
        return EV.trades_of(p, f, trial['trial_id'], getattr(qstrat, trial['implementation']),
                            trial['params'], uni)

    # One file per trial keeps artifacts below GitHub's per-file size limit.
    # A small hashed manifest binds all files without loading all trades at once.
    (destination / 'trades').mkdir()
    trade_files = {}
    def sink(tid, rows):
        name = f'trades/{tid}.jsonl.gz'
        with gzip.open(destination / name, 'wt', encoding='utf8', newline='\n') as fh:
            for row in rows:
                fh.write(json.dumps(dict(row, trial_id=tid), sort_keys=True, allow_nan=False) + '\n')
        trade_files[name] = dict(sha256=hashlib.sha256((destination / name).read_bytes()).hexdigest(),
                                trades=len(rows))
    matrix, summaries = replay(panel, features, universe, plan, start, end, simulate, sink)
    (destination / 'trades_a4.json').write_text(json.dumps(trade_files, sort_keys=True), encoding='utf8')

    names = [r['trial_id'] for r in plan['trials']]
    done = [k for k, s in enumerate(summaries) if s['status'] == 'REPLAYED']
    provenance = dict(dataset_sha256=dataset, plan_sha256=hashlib.sha256(PLAN.read_bytes()).hexdigest(),
                      protocol_sha256=hashlib.sha256(PROTOCOL.read_bytes()).hexdigest(),
                      replay_code_hash=plan['replay_code_hash'],
                      runner_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                      dependencies_sha256={name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                          for name in ('tools/v9/evidence.py', 'tools/v9/census_plan.py',
                                       'tools/research/multiple_testing.py')},
                      universe_sha256=hashlib.sha256((Path(md) / 'universe.json').read_bytes()).hexdigest())
    np.savez_compressed(destination / 'daily_returns.npz',
                        days=np.arange(start // DAY, end // DAY + 1),
                        trial_ids=np.asarray(names), returns=matrix)
    print('Computing diagnostic family statistics', flush=True)
    doc = dict(schema='v9.census-replay/1', provenance=provenance, window=[start, end],
               historical_trial_census_complete=False, known_trial_return_matrix_complete=False,
               promotion_authority=False, confirmed=[], trials=summaries,
               all_known_trials=family_statistics(matrix, names, provenance, replications),
               diagnostic_4h_subset=dict(trial_ids=[names[k] for k in done],
                   statistics=family_statistics(matrix[:, done], [names[k] for k in done],
                                                provenance, replications)))
    report = ('# A4 known-definition replay\n\n'
              f'{len(done)} of {len(names)} trials replayed. '
              f'{len(names)-len(done)} hourly trials remain pending A5.\n\n'
              'The full-family statistics are unavailable while hourly columns are missing. '
              'The 4h/daily subset statistics are diagnostic only. No trial is promoted. '
              'Unknown historical trials remain unknown.\n')
    (destination / 'REPORT_A4.md').write_text(report, encoding='utf8')
    doc['artifacts'] = {name: hashlib.sha256((destination / name).read_bytes()).hexdigest()
                        for name in ('daily_returns.npz', 'trades_a4.json', 'REPORT_A4.md')}
    # Written last: interrupted/failed runs never have a completed evidence document.
    (destination / 'evidence_a4.json').write_text(
        json.dumps(doc, sort_keys=True, indent=2, allow_nan=False) + '\n', encoding='utf8')
    return doc


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--md', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--phase-b-evidence', required=True)
    ap.add_argument('--replications', type=int, default=5000)
    args = ap.parse_args(argv)
    if args.replications < 2:
        ap.error('at least two replications required')
    run(args.md, args.out, args.phase_b_evidence, args.replications)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
