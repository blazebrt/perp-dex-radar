import copy
import unittest
from tools.v9 import control_cohort as C, verify_control_selection as V
from tests.test_v9_control_cohort import row


class Selection(unittest.TestCase):
    def test_all_registered_bucket_edges(self):
        for age in (29,30,89,90,179,180,364,365,729,730):
            for volume in (4999999,5000000,9999999,10000000,25000000,50000000,100000000):
                s=row(age=age,volume=volume)
                self.assertEqual(V.bucket(s,s['decision_time']),C.features(s,s['decision_time']))

    def test_complete_sparse_unavailable_and_exclusions(self):
        for n in (0,3,49,50,80):
            signal=row();population=[row(str(i)) for i in range(n)]+[row(),row('low',volume=1),row('old',age=800)]
            result=C.select('trial',signal,population)
            self.assertTrue(V.verify('trial',signal,population,result)['selection_verified'])
            self.assertTrue(V.verify('trial',signal,list(reversed(population)),result)['selection_verified'])
        signal=row(eligible=False)
        V.verify('trial',signal,population,C.select('trial',signal,population))

    def test_rank_order_identity_and_count_tampering(self):
        signal=row();population=[row(str(i)) for i in range(70)];result=C.select('trial',signal,population)
        for mutation in ('rank','order','count','feature'):
            bad=copy.deepcopy(result)
            if mutation=='rank':bad['controls'][0]['rank_sha256']='0'*64
            if mutation=='order':bad['controls'].reverse()
            if mutation=='count':bad['matching_candidates']-=1
            if mutation=='feature':bad['controls'][0]['features']['mean_daily_quote_volume']=1
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):V.verify('trial',signal,population,bad)

    def test_population_omission_and_duplicate_rejected(self):
        signal=row();population=[row(str(i)) for i in range(70)];result=C.select('trial',signal,population)
        for changed in (population[:-1],population+[population[0]]):
            with self.assertRaises(ValueError):V.verify('trial',signal,changed,result)

    def test_other_times_directions_and_outcomes_do_not_change_selection(self):
        signal=row();population=[row(str(i)) for i in range(60)];result=C.select('trial',signal,population)
        population += [row('later',decision_time=signal['decision_time']+14400),row('short',direction=-1)]
        for r in population:r['future_return']=999
        audit=V.verify('trial',signal,population,result)
        self.assertFalse(audit['snapshot_provenance_verified'])
