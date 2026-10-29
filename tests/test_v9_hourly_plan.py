import csv
import gzip
import json
from pathlib import Path
import tempfile
import unittest

from tools.v9 import hourly_plan as H


class CausalVolume(unittest.TestCase):
    def setUp(self):
        self.times = list(range(0, 40 * H.DAY, H.BAR))
        self.volumes = [1e6] * len(self.times)

    def test_cutoff_is_exclusive_and_future_cannot_change_membership(self):
        cutoff = 35 * H.DAY
        before = list(H.daily_candidates(self.times, self.volumes, 0, [cutoff]))
        changed = [v if t < cutoff else 1e15 for t, v in zip(self.times, self.volumes)]
        self.assertEqual(before, [(cutoff, 6e6)])
        self.assertEqual(before, list(H.daily_candidates(self.times, changed, 0, [cutoff])))
        changed[self.times.index(cutoff - H.BAR)] = 8e6
        self.assertEqual(list(H.daily_candidates(self.times, changed, 0, [cutoff])), [(cutoff, 7e6)])

    def test_missing_is_not_zero_and_old_gap_does_not_leak_forward(self):
        cutoff = 35 * H.DAY
        i = self.times.index(cutoff - H.BAR)
        self.assertEqual(list(H.daily_candidates(self.times[:i] + self.times[i+1:],
            self.volumes[:i] + self.volumes[i+1:], 0, [cutoff])), [])
        v = self.volumes.copy()
        v[i] = 0
        self.assertEqual(len(list(H.daily_candidates(self.times, v, 0, [cutoff]))), 1)
        self.assertEqual(list(H.daily_candidates(self.times[:2]+self.times[3:],
            self.volumes[:2]+self.volumes[3:], 0, [cutoff])), [(cutoff, 6e6)])

    def test_age_and_minimum_volume_are_not_relaxed(self):
        self.assertEqual(list(H.daily_candidates(self.times, self.volumes, 0, [29*H.DAY])), [])
        self.assertEqual(list(H.daily_candidates(self.times, [1]*len(self.times), 0, [35*H.DAY])), [])
        self.assertEqual(len(list(H.daily_candidates(self.times, self.volumes, 0, [30*H.DAY]))), 1)

    def test_malformed_inputs_fail(self):
        cases = [(self.times[::-1], self.volumes), (self.times+[self.times[-1]], self.volumes+[1e6]),
                 ([1]+self.times[1:], self.volumes), (self.times, [float('nan')]+self.volumes[1:]),
                 (self.times, [-1]+self.volumes[1:]), (self.times, [True]+self.volumes[1:]),
                 (self.times, self.volumes[:-1])]
        for t, v in cases:
            with self.subTest(t=t[:2], v=v[:2]), self.assertRaises(ValueError):
                list(H.daily_candidates(t, v, 0, [35*H.DAY]))
        with self.assertRaises(ValueError):
            list(H.daily_candidates(self.times, self.volumes, 0, [35*H.DAY+1]))


def archive(root, count=2):
    (root/'h4').mkdir()
    coins = []
    for name in ['BTC']+[f'C{i:03}' for i in range(count-1)]:
        times = range(0, 122*H.DAY, H.BAR)
        with gzip.open(root/'h4'/f'{name}.csv.gz', 'wt', newline='') as f:
            w = csv.writer(f)
            w.writerow(['t', 'o', 'h', 'l', 'c', 'qv', 'tbqv'])
            w.writerows((t, 10, 12, 9, 11, 1e6, 5e5) for t in times)
        coins.append(dict(t=name, symbol=name+'USDT', excluded=None, first_bar=0,
                          last_bar=122*H.DAY-H.BAR, delisted=True, trade_vol=0))
    (root/'universe.json').write_text(json.dumps(dict(coins=coins, archive_end_bar=122*H.DAY-H.BAR)))
    return coins


class Plan(unittest.TestCase):
    def test_top_150_ties_order_and_present_listing_metadata_do_not_select(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            coins = archive(p, 152)
            a = H.build(p)
            self.assertEqual(len(a['days']), 2)
            self.assertEqual(a['days'][0]['eligible_count'], 152)
            self.assertEqual([r['coin'] for r in a['days'][0]['selected']], ['BTC']+[f'C{i:03}' for i in range(149)])
            for c in coins:
                c.update(delisted=False, trade_vol=1e20)
            (p/'universe.json').write_text(json.dumps(dict(coins=coins[::-1], archive_end_bar=122*H.DAY-H.BAR)))
            b = H.build(p)
            self.assertEqual(a['days'], b['days'])
            self.assertFalse(b['promotion_authority'])

    def test_empty_days_context_and_relisting_age(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            coins = archive(p)
            # Both original segments ended before the research window; relisting
            # has a fresh clock and cannot inherit the first segment's age.
            for c in coins:
                with gzip.open(p/'h4'/f"{c['t']}.csv.gz", 'wt') as f:
                    f.write('t,qv\n')
                    for t in range(0, 110*H.DAY, H.BAR):
                        f.write(f'{t},1000000\n')
                c['last_bar'] = 110*H.DAY-H.BAR
            name = 'C000~2'
            with gzip.open(p/'h4'/f'{name}.csv.gz', 'wt') as f:
                f.write('t,qv\n')
                for t in range(115*H.DAY, 122*H.DAY, H.BAR):
                    f.write(f'{t},100000000\n')
            coins.append(dict(t=name, symbol='C000USDT', excluded=None, first_bar=115*H.DAY,
                              last_bar=122*H.DAY-H.BAR))
            (p/'universe.json').write_text(json.dumps(dict(coins=coins, archive_end_bar=122*H.DAY-H.BAR)))
            a = H.build(p)
            self.assertTrue(all(not r['selected'] for r in a['days']))
            self.assertEqual(a['context_only'], ['BTC'])
            self.assertEqual([r['t'] for r in a['fetch_coins']], ['BTC'])

    def test_missing_file_and_bad_bounds_abort(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            archive(p)
            (p/'h4'/'C000.csv.gz').unlink()
            with self.assertRaisesRegex(ValueError, 'complete research universe'):
                H.build(p)


if __name__ == '__main__':
    unittest.main()
