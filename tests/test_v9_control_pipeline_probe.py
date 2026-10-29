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
        for kind,n,bars in [('bad',3,400),('full',True,400),('full',25001,400),('full',3,399),('full',3,32769)]:
            with self.subTest(kind=kind,n=n,bars=bars),self.assertRaises(ValueError):P.scenario(kind,n,bars)


    def test_expanded_population_runs_and_audits_every_available_definition(self):
        result=P.scenario('full',3,400,assets=62,definitions=5,unavailable=2)
        self.assertEqual(result['assets'],62)
        self.assertEqual(result['definitions'],5)
        self.assertEqual(result['unavailable_definitions'],2)
        self.assertEqual(result['expected_signals'],9)
        self.assertEqual(result['processed_signals'],9)
        self.assertEqual(result['audit_status'],'VERIFIED_REGISTERED_PRICE_DIAGNOSTICS')
        self.assertFalse(result['promotion_authority'])

    def test_population_bounds_and_full_roster_without_large_execution(self):
        from tools.v9 import control_probe_shape as S
        from unittest.mock import patch
        shape=S.validate(100,4000,781,199,7)
        self.assertEqual(shape['definitions'],199)
        roster=S.trials(199,7)
        self.assertEqual(len({r['trial_id'] for r in roster}),199)
        self.assertEqual(sum(r['archive_requirement']=='4h' for r in roster),192)
        self.assertEqual(S.trials(3,1),[dict(trial_id=str(i)*64,archive_requirement='hourly' if i==2 else '4h') for i in range(3)])
        with patch.object(P.tempfile,'TemporaryDirectory') as temporary:
            for kwargs in (dict(assets=60),dict(assets=782),dict(assets=True),dict(definitions=200),dict(definitions=2),dict(unavailable=0),dict(unavailable=2),dict(unavailable=True)):
                with self.subTest(kwargs=kwargs),self.assertRaises(ValueError):P.scenario('full',3,400,**kwargs)
        temporary.assert_not_called()


    def test_signal_coordinates_cover_study_count_without_repetition(self):
        from tools.v9 import control_probe_shape as S
        for n in (3,8,32,100):
            indices,columns=S.signal_coordinates(n,400,61)
            self.assertEqual(indices,list(range(180,180+n-1))+[399])
            self.assertEqual(columns,[0]*n)
        n=22207
        S.validate(n,4000,781,199,7)
        self.assertGreaterEqual(n*192,4263580)
        for assets in (8,781):
            indices,columns=S.signal_coordinates(n,4000,assets)
            self.assertEqual(len(set(zip(indices,columns))),n)
            self.assertTrue(all(180<=i<4000 and 0<=j<assets for i,j in zip(indices,columns)))
            self.assertEqual((indices[-1],columns[-1]),(3999,0))
            self.assertEqual(sum(i==3999 for i in indices),1)
        with self.assertRaises(ValueError):S.validate(1754,400,61,3,1)
        with self.assertRaises(ValueError):S.signal_coordinates(1754,400,8)
        indices,columns=S.signal_coordinates(1753,400,8)
        self.assertEqual(len(set(zip(indices,columns))),1753)

    def test_expanded_signal_count_crosses_asset_boundary_and_audits(self):
        result=P.scenario('sparse',221,400)
        self.assertEqual(result['expected_signals'],442)
        self.assertEqual(result['processed_signals'],442)
        self.assertEqual(result['audit_status'],'VERIFIED_REGISTERED_PRICE_DIAGNOSTICS')
        self.assertTrue(result['statistics']['descriptive_statistics_verified'])
        self.assertFalse(result['promotion_authority'])


    def test_shard_limit_changes_layout_without_changing_retained_records(self):
        import gzip,json,inspect
        from tools.v9 import control_outcomes as O
        self.assertEqual(inspect.signature(O.run).parameters['max_rows'].default,25000)
        def capture(root):
            rows={}
            for category in ('pairs','days','reuse'):
                directory=root/'outcomes' if category=='pairs' else root/'outcomes'/category
                rows[category]=sorted(line for path in sorted(directory.glob('*.jsonl.gz')) for line in gzip.decompress(path.read_bytes()).splitlines())
            rows['sides']=json.loads((root/'outcomes/sides.json').read_text())
            return rows
        tiny=P.scenario('sparse',8,400,retain=capture,shard_rows=4)
        large=P.scenario('sparse',8,400,retain=capture,shard_rows=25000)
        self.assertEqual(tiny['publication'],large['publication'])
        self.assertEqual(tiny['dispositions'],large['dispositions'])
        self.assertEqual(tiny['statistics'],large['statistics'])
        self.assertEqual(tiny['pair_shards'],4)
        self.assertEqual(large['pair_shards'],2)
        self.assertLess(large['outcome_files'],tiny['outcome_files'])
        self.assertEqual(large['outcome_shard_max_uncompressed_bytes'],16*1024*1024)
        self.assertEqual(large['audit_status'],'VERIFIED_REGISTERED_PRICE_DIAGNOSTICS')

    def test_shard_limit_rejected_before_work(self):
        from unittest.mock import patch
        from tools.v9 import control_resource_measure as M
        with patch.object(P.tempfile,'TemporaryDirectory') as temporary,patch.object(M,'measure') as measure:
            for value in (0,-1,25001,True,4.5,'4'):
                with self.subTest(value=value):
                    with self.assertRaises(ValueError):P.scenario('full',3,400,shard_rows=value)
                    with self.assertRaises(ValueError):M.probe(3,400,shard_rows=value)
        temporary.assert_not_called();measure.assert_not_called()


    def test_long_history_spread_coordinates_are_unique_and_in_range(self):
        from tools.v9 import control_probe_shape as S
        S.validate(25000,32768,781,199,7)
        for bars,assets,n in ((8192,8,8),(32768,781,25000),(400,8,1753)):
            indices,columns=S.signal_coordinates(n,bars,assets,'spread')
            self.assertEqual(len(set(zip(indices,columns))),n)
            self.assertEqual((indices[0],columns[0]),(180,0))
            self.assertEqual((indices[-2],columns[-2]),(bars-2,assets-1))
            self.assertEqual((indices[-1],columns[-1]),(bars-1,0))
            self.assertTrue(all(180<=i<bars and 0<=j<assets for i,j in zip(indices,columns)))
        from unittest.mock import patch
        with patch.object(P.tempfile,'TemporaryDirectory') as temporary:
            with self.assertRaises(ValueError):P.scenario('sparse',8,8192,placement='invalid')
        temporary.assert_not_called()

    def test_long_history_spread_case_passes_independent_audit(self):
        result=P.scenario('sparse',8,8192,placement='spread',shard_rows=25000)
        self.assertEqual(result['bars_per_asset'],8192)
        self.assertEqual(result['signal_placement'],'spread')
        self.assertEqual(result['processed_signals'],16)
        self.assertEqual(result['audit_status'],'VERIFIED_REGISTERED_PRICE_DIAGNOSTICS')
        self.assertFalse(result['promotion_authority'])
