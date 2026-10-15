"""Known-trial replay inventory must neither drop trials nor invent completeness."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from tools.v9 import census_plan as plan


class CensusPlan(unittest.TestCase):
    def test_all_trials_resolved_and_hourly_dependency_explicit(self):
        result = plan.build()
        self.assertEqual(result['known_trials'], 199)
        self.assertEqual(result['ready_4h_trials'], 192)
        self.assertEqual(len(result['hourly_trials_pending_A5']), 7)
        self.assertEqual({r['aliases'][0] for r in result['trials'] if r['timeframe'] == '1h'},
                         {'BTC_LEAD', 'FAIL_BRK', 'FUND_CARRY', 'FUND_FADE', 'LIQ_FLUSH', 'PULLBACK', 'VOL_SPIKE'})
        self.assertFalse(result['historical_trial_census_complete'])
        self.assertFalse(result['known_trial_return_matrix_complete'])
        self.assertFalse(result['promotion_authority'])

    def test_committed_plan_is_reproducible(self):
        saved = json.loads((plan.ROOT / 'research/v9/census_replay_plan.json').read_text())
        self.assertEqual(saved, plan.build())

    def test_corrupt_identity_parameters_or_count_are_rejected(self):
        original = json.loads((plan.ROOT / plan.CENSUS).read_text())
        for corruption in ('duplicate', 'count', 'params', 'identity', 'unknown_function'):
            with self.subTest(corruption=corruption), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                for path in (*plan.census.CODE_FILES, 'tools/research/qexport.py'):
                    target = root / path
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes((plan.ROOT / path).read_bytes())
                doc = copy.deepcopy(original)
                if corruption == 'duplicate':
                    doc['trials'][1] = doc['trials'][0]
                elif corruption == 'count':
                    doc['known_lower_bound'] -= 1
                elif corruption == 'params':
                    doc['trials'][0]['params']['fast'] = 999
                elif corruption == 'identity':
                    doc['trials'][0]['trial_id'] = '0' * 64
                else:
                    doc['trials'][0]['implementation'] = 'unregistered'
                target = root / plan.CENSUS
                target.parent.mkdir(parents=True)
                target.write_text(json.dumps(doc))
                with self.assertRaises(ValueError):
                    plan.build(root)


if __name__ == '__main__':
    unittest.main()
