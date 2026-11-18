import copy
import hashlib
import json
import unittest
from tools.v9 import control_partition_plan as P


def fixture():
    tid='a'*64;missing='b'*64
    shards=[dict(path=f'{tid}-{i:05d}.jsonl.gz',records=n,bytes=50,uncompressed_bytes=100,sha256=str(i)*64) for i,n in enumerate([3,2])]
    return dict(schema='v9.a6-extraction/1',status='COMPLETED_WITH_UNAVAILABLE_HOURLY_POPULATIONS',
                promotion_authority=False,outcomes_computed=False,full_matched_authority=False,
                trials=[dict(trial_id=tid,definition={'trial_id':tid},promotion_authority=False,
                             status='EXTRACTED',retained_records=5,shards=shards),
                        dict(trial_id=missing,definition={'trial_id':missing},promotion_authority=False,
                             status='UNAVAILABLE_HOURLY_POPULATION',shards=[])])


def run(doc):
    raw=json.dumps(doc).encode();return P.build(raw,hashlib.sha256(raw).hexdigest())


class PartitionPlan(unittest.TestCase):
    def test_every_source_row_once_in_original_order_and_unavailable_retained(self):
        doc=fixture();before=copy.deepcopy(doc);plan=run(doc)
        self.assertEqual(doc,before)
        self.assertEqual(plan['signals'],5);self.assertEqual(plan['trial_count'],2)
        self.assertEqual([(u['retained_row_start'],u['retained_row_end']) for u in plan['units']],[(0,3),(3,5)])
        self.assertEqual([u['source'] for u in plan['units']],doc['trials'][0]['shards'])
        self.assertEqual(plan['trials'][1]['status'],'UNAVAILABLE_HOURLY_POPULATION')
        self.assertEqual(plan['trials'][1]['units'],0)
        for key in ('source_shards_reverified','resource_qualified','execution_authorized','promotion_authority'):
            self.assertIs(plan[key],False)
        self.assertIsNone(plan['input_commit'])

    def test_omitted_reordered_duplicated_wrong_count_and_invented_population_rejected(self):
        cases=[]
        for transform in [lambda d:d['trials'][0]['shards'].reverse(),
                          lambda d:d['trials'][0]['shards'].pop(),
                          lambda d:d['trials'].append(d['trials'][0]),
                          lambda d:d['trials'][0].update(retained_records=True),
                          lambda d:d['trials'][0]['shards'][0].update(records=True),
                          lambda d:d['trials'][0]['shards'][0].update(path='../outside'),
                          lambda d:d['trials'][1].update(shards=d['trials'][0]['shards']),
                          lambda d:d.update(outcomes_computed=True)]:
            d=fixture();transform(d);cases.append(d)
        for doc in cases:
            with self.assertRaises(ValueError):run(doc)

    def test_pinned_input_binding_and_duplicate_json(self):
        raw=json.dumps(fixture()).encode()
        with self.assertRaisesRegex(ValueError,'binding'):P.build(raw)
        raw=b'{"trials":[],"trials":[]}'
        with self.assertRaisesRegex(ValueError,'duplicate'):P.build(raw,hashlib.sha256(raw).hexdigest())

    def test_empty_available_trial_still_has_inventory_slot(self):
        d=fixture();d['trials'][0].update(shards=[],retained_records=0)
        p=run(d);self.assertEqual(p['signals'],0);self.assertEqual(p['unit_count'],0)
        self.assertEqual(p['trial_count'],2)
