import unittest
from tools.v9 import hourly_feature_state as F


def rows(start, hours):
    return {t * F.HOUR: dict(o=10, h=11, l=9, c=10, qv=100)
            for t in range(start, start + hours)}


class FeatureStateTests(unittest.TestCase):
    def test_warmup_and_gap_restart(self):
        data = rows(0, 800)
        self.assertEqual(min(F.readiness(data, 'FAIL_BRK')), 719 * F.HOUR)
        del data[100 * F.HOUR]
        self.assertEqual(F.readiness(data, 'FAIL_BRK'), set())
        data.update(rows(800, 21))
        self.assertEqual(F.readiness(data, 'FAIL_BRK'), {820 * F.HOUR})

    def test_zero_trade_breaks_recursive_session(self):
        data = rows(0, 1441)
        data[720 * F.HOUR]['qv'] = 0
        self.assertEqual([len(s) for s in F.runs(data)], [720, 720])
        self.assertEqual(F.readiness(data, 'VOL_SPIKE'), {719 * F.HOUR, 1440 * F.HOUR})

    def test_pullback_requires_200_complete_utc_four_hour_bars(self):
        data = rows(1, 803)
        self.assertEqual(F.readiness(data, 'PULLBACK'), {803 * F.HOUR})
        del data[803 * F.HOUR]
        self.assertEqual(F.readiness(data, 'PULLBACK'), set())

    def test_btc_context_break_resets_joint_beta_session(self):
        own = rows(0, 1441); btc = rows(0, 1441)
        del btc[720 * F.HOUR]
        self.assertEqual(F.readiness(own, 'BTC_LEAD', btc), {719 * F.HOUR, 1440 * F.HOUR})
        with self.assertRaises(ValueError):
            F.readiness(own, 'BTC_LEAD')

    def test_future_append_never_changes_prior_readiness(self):
        data = rows(0, 900)
        original = F.readiness(data, 'PULLBACK')
        data.update(rows(900, 1000))
        data[1000 * F.HOUR]['qv'] = 0
        self.assertEqual({t for t in F.readiness(data, 'PULLBACK') if t < 900 * F.HOUR}, original)


if __name__ == '__main__':
    unittest.main()
