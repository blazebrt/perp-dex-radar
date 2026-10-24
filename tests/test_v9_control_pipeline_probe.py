import unittest
from tools.v9 import control_pipeline_probe as P


class PipelineProbe(unittest.TestCase):
    def test_complete_pipeline_scenarios_and_failure_retention(self):
        result=P.probe(3,400)
        self.assertEqual(result['status'],'NOT_RESOURCE_QUALIFIED')
        self.assertFalse(result['market_data_loaded'])
        cases={c['scenario']:c for c in result['cases']}
        for name in ('full','mixed','sparse'):
            c=cases[name]
            self.assertEqual(c['processed_signals'],6)
            self.assertEqual(c['audit_status'],'VERIFIED_REGISTERED_PRICE_DIAGNOSTICS')
            self.assertTrue(c['statistics']['descriptive_statistics_verified'])
            self.assertTrue(c['statistics']['control_reuse_verified'])
            self.assertGreater(c['summary_database_bytes'],0)
            self.assertGreater(c['reuse_bytes'],0)
            self.assertGreater(c['outcome_bytes'],c['pair_bytes'])
            self.assertFalse(c['failure_retained'])
            self.assertEqual(set(c['audit_files']),{'audit.json'})
        self.assertEqual(cases['full']['control_paths'],300)
        self.assertEqual(cases['sparse']['control_paths'],42)
        reasons={key for d in cases['mixed']['dispositions'] for key in d}
        self.assertIn('candidate:reason:ENTRY_INELIGIBLE',reasons)
        self.assertIn('control:reason:ARCHIVE_END',reasons)
        failed=cases['interrupted']
        self.assertEqual(failed['processed_signals'],3)
        self.assertEqual(failed['outcome_status'],'FAILED_OR_PARTIAL')
        self.assertEqual(failed['audit_status'],'FAILED')
        self.assertTrue(failed['failure_retained']);self.assertGreater(failed['pair_bytes'],0)
        self.assertIsNone(failed['statistics'])

    def test_unbounded_inputs_rejected_before_synthetic_creation(self):
        for kind,n,bars in [('bad',3,400),('full',True,400),('full',101,400),('full',3,399),('full',3,4001)]:
            with self.subTest(kind=kind,n=n,bars=bars),self.assertRaises(ValueError):P.scenario(kind,n,bars)
