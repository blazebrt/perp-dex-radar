import copy
import json
import random
import unittest
from tools.v9 import control_storage as W, verify_control_storage as R


class Storage(unittest.TestCase):
    def pair(self,n):
        return dict(signal_id='s',candidate=dict(net_R=None,known=False,value=-0.0,geometry={'hold':6}),
                    controls=[dict(asset=str(i),outcome=dict(net_R=None,known=False,value=i/3,geometry={'hold':6})) for i in range(n)],
                    cohort=dict(controls=[dict(asset=str(i),rank_sha256=str(i),features=dict(t=14400,eligible=True,v=i)) for i in range(n)]))

    def test_empty_sparse_and_fifty_controls_roundtrip_and_input_isolation(self):
        for n in (0,1,49,50):
            original=self.pair(n);before=W.canonical(original)
            packed=W.pack(original);decoded=R.unpack(json.loads(W.canonical(packed)))
            self.assertEqual(W.canonical(decoded),before)
            decoded['candidate']['geometry']['hold']=99
            self.assertEqual(W.canonical(original),before)
            self.assertEqual(W.canonical(R.unpack(packed)),before)

    def test_types_nulls_signed_zero_and_varied_dispositions_are_preserved(self):
        rng=random.Random(934)
        for _ in range(80):
            pair=self.pair(rng.randrange(51))
            for outcome in [pair['candidate']]+[r['outcome'] for r in pair['controls']]:
                outcome.update(value=rng.choice([False,0,0.0,-0.0,None,1,1.0,-2.5]),
                               status=rng.choice(['UNEXECUTED','UNRESOLVED_PRICE','PRICE_OBSERVED_FUNDING_UNKNOWN']))
            self.assertEqual(W.canonical(R.unpack(W.pack(pair))),W.canonical(pair))

    def test_ambiguous_truncated_extra_or_nonfinite_storage_rejected(self):
        base=W.pack(self.pair(2))
        def mutations(p):
            p['outcomes']['columns'].append(p['outcomes']['columns'][0])
        cases=[mutations,lambda p:p['outcomes']['rows'].pop(),lambda p:p['outcomes']['rows'][0].append(1),
               lambda p:p['base'].update(candidate={}),lambda p:p.update(schema='unknown'),
               lambda p:p['outcomes']['shared'].update(value=2),lambda p:p.update(extra=True),
               lambda p:p['features']['shared'].update(bad=float('nan'))]
        for mutate in cases:
            packed=copy.deepcopy(base);mutate(packed)
            with self.assertRaises(ValueError):R.unpack(packed)

    def test_encoder_refuses_nonfinite_and_inconsistent_fields(self):
        pair=self.pair(1);pair['candidate']['value']=float('inf')
        with self.assertRaises(ValueError):W.pack(pair)
        pair=self.pair(1);pair['candidate']['extra']=False
        with self.assertRaises(ValueError):W.pack(pair)
