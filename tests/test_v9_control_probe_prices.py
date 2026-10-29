import unittest
from tools.v9 import control_probe_prices as P


class PricesTest(unittest.TestCase):
    def test_baseline_exact_and_diverse_valid_deterministic(self):
        returns=set();volumes=set();wicks=set()
        for asset in (0,7,60,780):
            for index in range(400):
                price=100+asset*.25+(index%11)*.03
                self.assertEqual(P.bar(asset,index),(price,price+1,price-1,price+.02,2e6))
                row=P.bar(asset,index,'diverse')
                self.assertEqual(row,P.bar(asset,index,'diverse'))
                o,h,l,c,v=row
                self.assertTrue(0<l<=min(o,c)<=max(o,c)<=h)
                self.assertTrue(1600000<=v<=2400000)
                returns.add(round(c/o-1,5));volumes.add(v);wicks.add(round(h/max(o,c)-1,5))
        self.assertGreater(len(returns),500)
        self.assertGreater(len(volumes),1000)
        self.assertGreater(len(wicks),20)
        self.assertLess(min(returns),0)
        self.assertGreater(max(returns),0)

    def test_unknown_profile_rejected_before_work(self):
        from unittest.mock import patch
        from tools.v9 import control_pipeline_probe as pipeline
        from tools.v9 import control_resource_measure as resource
        for module,call in ((pipeline,lambda:pipeline.scenario('full',price_profile='bad')),
                            (resource,lambda:resource.measure('full',3,400,price_profile='bad'))):
            with patch.object(module.tempfile,'TemporaryDirectory',side_effect=AssertionError('started work')):
                with self.assertRaisesRegex(ValueError,'price profile'):call()
