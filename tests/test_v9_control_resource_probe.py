import unittest
from tools.v9 import control_resource_probe as P


class ResourceProbe(unittest.TestCase):
    def test_real_adapter_probe_is_synthetic_and_avoids_repeated_source_reads(self):
        result=P.probe(2)
        self.assertEqual(result['observed_price_pairs'],2)
        self.assertLessEqual(result['price_file_reads'],result['distinct_available_price_files'])
        self.assertEqual(result['independently_verified_price_paths'],102)
        self.assertEqual(result['independently_reconstructed_pairs'],2)
        self.assertLess(result['packed_json_bytes'],result['pair_json_bytes'])
        self.assertFalse(result['packed_driver_enabled'])
        self.assertLessEqual(result['audit_price_file_reads'],61)
        self.assertGreater(result['audit_elapsed_seconds'],0)
        self.assertGreater(result['pair_json_bytes'],result['pair_gzip_bytes'])
        self.assertGreater(result['elapsed_seconds'],0)
        self.assertFalse(result['market_data_loaded']);self.assertEqual(result['status'],'NOT_RESOURCE_QUALIFIED')

    def test_unbounded_or_empty_probe_rejected(self):
        for n in (0,101,True,1.5):
            with self.subTest(n=n),self.assertRaises(ValueError):P.probe(n)
