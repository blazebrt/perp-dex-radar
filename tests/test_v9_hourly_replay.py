import csv
import gzip
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
from tools.v9 import hourly_replay as R

try:
    import numpy
    import pandas
    HAVE = True
except ModuleNotFoundError as exc:
    if exc.name not in ('numpy', 'pandas'): raise
    HAVE = False
if HAVE:
    from tools.v9 import hourly_signals as G
    from tests.test_v9_hourly_signals import candles


def zipped(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, 'wt', encoding='utf8', newline='') as fh: fh.write(text)


def schedule(start, end):
    return [dict(new_entries_allowed=True, schedule=dict(known_at=t, valid_until=t+86400,
                 selected=[dict(coin='BTC'), dict(coin='X')])) for t in range(start,end,86400)]


def archive(root, rows):
    start, end = 720*3600, 1200*3600
    days = schedule(start,end)
    for coin in ('BTC','X'):
        f = io.StringIO(); w = csv.writer(f, lineterminator='\n')
        w.writerow(['t','o','h','l','c','qv','tbqv'])
        for t,r in sorted(rows.items()): w.writerow([t]+[r[k] for k in ('o','h','l','c','qv')]+[0])
        zipped(root/f'h1/{coin}.csv.gz', f.getvalue())
        zipped(root/f'fund_bn/{coin}.csv.gz', 't,rate,interval_h\n')
    R.write_json(root/'hourly_plan.json',dict(window=[start,end],days=[d['schedule'] for d in days],
                fetch_coins=[dict(t=c,first_bar=0) for c in ('BTC','X')]))
    R.write_json(root/'quality_schedule.json',days)
    inventory={p.relative_to(root).as_posix():R.sha(p) for p in root.rglob('*') if p.is_file()}
    R.write_json(root/'quality_candidate_manifest.json',dict(artifacts_sha256=inventory))
    return R.sha(root/'quality_candidate_manifest.json')


class ArchiveValidation(unittest.TestCase):
    def test_corrupt_missing_and_extra_artifacts_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); digest=archive(root,{0:dict(o=1,h=1,l=1,c=1,qv=1)})
            with mock.patch.object(R,'MANIFEST_SHA',digest):
                R.verify_archive(root)
                extra=root/'extra';extra.write_text('extra')
                with self.assertRaisesRegex(ValueError,'inventory'):R.verify_archive(root)
                extra.unlink(); p=root/'fund_bn/X.csv.gz';p.write_bytes(b'bad')
                with self.assertRaisesRegex(ValueError,'changed'):R.verify_archive(root)
                p.unlink()
                with self.assertRaises(FileNotFoundError):R.verify_archive(root)

    def test_candles_reject_duplicates_and_invalid_observations(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'c.gz'; header='t,o,h,l,c,qv,tbqv\n'
            for text in ('0,1,1,1,1,1,0\n0,1,1,1,1,1,0\n',
                         '1,1,1,1,1,1,0\n','0,1,1,1,nan,1,0\n'):
                zipped(p,header+text)
                with self.assertRaises(ValueError):R.read_candles(p)


@unittest.skipUnless(HAVE,'scientific libraries required; research CI')
class ReplayIntegration(unittest.TestCase):
    def test_all_trials_artifacts_unknown_net_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'archive';root.mkdir(); out=Path(tmp)/'out'
            digest=archive(root,candles())
            with mock.patch.object(R,'MANIFEST_SHA',digest): result=R.run(root,out)
            self.assertEqual(len(result['trials']),7)
            liq=result['trials']['LIQ_FLUSH']
            self.assertGreater(liq['attempt_counts']['UNRESOLVED_FUNDING'],0)
            self.assertFalse(liq['net_series_available'])
            self.assertTrue(all(x['net_R'] is None for x in liq['daily_net_R']))
            self.assertFalse(result['known_trial_return_matrix_complete'])
            for name,digest in result['artifacts_sha256'].items():self.assertEqual(R.sha(out/name),digest)
            with gzip.open(out/'FUND_CARRY.jsonl.gz','rt') as fh:carry=json.loads(fh.readline())
            self.assertTrue(all(x['net_R'] is None for x in carry['daily_net_R']))
            with self.assertRaises(FileExistsError):R.run(root,out)

    def test_segment_projection_equals_joint_batch(self):
        rows=candles(); start,end=720*3600,1200*3600; days=schedule(start,end)
        days[5]['new_entries_allowed']=False
        days[9]['schedule']['selected']=[dict(coin='BTC')]
        funding=R.F.prepare([]); separate=[]; signals=[]
        for coin in ('BTC','X'):
            result=R.segment_replay('LIQ_FLUSH',coin,rows,0,rows,funding,days,start,end)
            separate+=result['attempts']
            signals += [s for s in G.generate('LIQ_FLUSH',coin,rows,0)['signals'] if s['signal_time']>=start-3600]
        joint=R.B.replay(signals,{'BTC':rows,'X':rows},days,start,end)['attempts']
        def normalized(items):
            return sorted([{k:v for k,v in x.items() if k!='signal_ordinal'} for x in items],
                          key=lambda x:(x['coin'],x['signal_time'],x['parameters']['direction']))
        self.assertTrue(joint)
        self.assertEqual(normalized(separate),normalized(joint))

    def test_off_grid_funding_and_failed_segment_remain_unavailable(self):
        rows=candles(); start,end=720*3600,1200*3600; days=schedule(start,end)
        funding=R.F.prepare([dict(t=start+1,rate=.001)])
        result=R.segment_replay('FUND_FADE','X',rows,0,rows,funding,days,start,end)
        self.assertEqual(result['status'],'UNAVAILABLE_OFF_GRID_FUNDING')
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'a';root.mkdir();out=Path(tmp)/'out';digest=archive(root,rows)
            original=R.segment_replay
            def fail(alias,coin,*args,**kwargs):
                if alias=='LIQ_FLUSH' and coin=='X':raise RuntimeError('injected segment failure')
                return original(alias,coin,*args,**kwargs)
            with mock.patch.object(R,'MANIFEST_SHA',digest),mock.patch.object(R,'segment_replay',side_effect=fail):
                result=R.run(root,out)
            trial=result['trials']['LIQ_FLUSH']
            self.assertEqual(trial['failed_segments'],1)
            self.assertEqual(trial['status'],'FAILED_PARTIAL_REPLAY')
            self.assertTrue(all(d['net_R'] is None for d in trial['daily_net_R']))
            with gzip.open(out/'LIQ_FLUSH.jsonl.gz','rt') as fh:
                self.assertIn('injected segment failure',fh.read())

    def test_writer_failure_has_no_completion_marker(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'a';root.mkdir();out=Path(tmp)/'out';digest=archive(root,candles())
            original=R.gzip.open
            def fail(path,mode='rb',*args,**kwargs):
                if str(path).endswith('LIQ_FLUSH.jsonl.gz') and 'w' in mode:
                    raise OSError('injected writer failure')
                return original(path,mode,*args,**kwargs)
            with mock.patch.object(R,'MANIFEST_SHA',digest),mock.patch.object(R.gzip,'open',side_effect=fail):
                with self.assertRaisesRegex(OSError,'writer'):R.run(root,out)
            self.assertTrue((out/'failure.json').exists())
            self.assertFalse((out/'evidence_a5.json').exists())

    def test_fatal_preflight_preserves_failure_without_completion_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'a';root.mkdir();out=Path(tmp)/'out';archive(root,candles())
            with self.assertRaisesRegex(ValueError,'unaccepted'):R.run(root,out)
            self.assertTrue((out/'failure.json').exists())
            self.assertFalse((out/'evidence_a5.json').exists())


if __name__=='__main__':unittest.main()
