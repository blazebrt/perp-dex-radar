"""B9: unsupported signals cannot masquerade as positive Emerging evidence."""
import copy
import ast
import subprocess
from pathlib import Path
from unittest.mock import patch
import unittest
from tests import test_v9_decision as V
from tests import test_v8_phase11 as P
from v8 import decision as DE


def emerging(doc):
    return [c for c in doc['candidates'] if c['type']==DE.EMERGING]


class Authority(unittest.TestCase):
    def test_legacy_paper_and_rejected_signals_do_not_seed_emerging(self):
        for sid in ('TSMOM','PAPER','DIS','REJ'):
            with self.subTest(strategy=sid):
                doc=DE.build(P.snapshot([P.rec('HI')],{'HI':[P.sig(sid)]}))
                self.assertFalse(emerging(doc))
                directional=[c for c in doc['candidates'] if c['type']==DE.DIRECTIONAL]
                self.assertEqual(len(directional),1)
                self.assertIn(directional[0]['state'],(DE.WATCH,DE.AVOID))

    def test_independent_observation_survives_without_unsupported_signal_boost(self):
        rec=P.rec('HI',flags=['NEW_LISTING','MULTI_VENUE'])
        doc=DE.build(P.snapshot([rec],{'HI':[P.sig('TSMOM')]}))
        row=emerging(doc)[0]
        self.assertEqual({e['type'] for e in row['positive_evidence']},{'RECENTLY_OBSERVED_BY_DESK','MULTI_VENUE_PRESENCE'})
        self.assertEqual(row['ranking_inputs']['primary_evidence_count'],1)
        self.assertEqual(row['ranking_inputs']['evidence_count'],2)
        self.assertEqual(row['state'],DE.WATCH)

    def test_authorized_watch_survives_but_trade_is_not_recast_as_watch(self):
        for sid in ('REQ','PROB'):
            snap=V.snap({'HI':[P.sig(sid)]},recs=[P.rec('HI',liq=('KNOWN',3e4,False))])
            doc=DE.build(snap);row=emerging(doc)[0]
            self.assertEqual([e['type'] for e in row['positive_evidence']],['CURRENT_STRATEGY_SIGNAL'])
            self.assertEqual(V.gate(V.cand(doc,'HI',sid),'STRATEGY_AUTHORITY')['result'],DE.PASS)
        doc=DE.build(V.snap({'HI':[P.sig('PROB')]}))
        self.assertEqual(V.cand(doc,'HI')['state'],DE.TRADE)
        self.assertFalse(emerging(doc))

    def test_unconfirmed_missing_failed_and_not_yet_effective_probation_do_not_boost(self):
        cases=[V.snap({'HI':[P.sig('PROB',d=-1)]}),
               V.snap({'HI':[P.sig('PROB')]},ft={}),
               V.snap({'HI':[P.sig('PROB')]},ft=V.forward(30,-100)),
               V.snap({'HI':[P.sig('PROB')]},strategies=V.strats(effective=P.AS_OF+86400)),
               V.snap({'HI':[P.sig('PROB',age=7200)]},strategies=V.strats(window=3600))]
        missing=V.snap({'HI':[P.sig('PROB')]});missing['strategies']['PROB']['probation']={};cases.append(missing)
        for snap in cases:
            with self.subTest(snapshot=snap['forward_tests']):
                before=copy.deepcopy(snap);doc=DE.build(snap)
                self.assertFalse(emerging(doc));self.assertEqual(snap,before)
                self.assertNotEqual(V.gate(next(c for c in doc['candidates'] if c['type']==DE.DIRECTIONAL),'STRATEGY_AUTHORITY')['result'],DE.PASS)

    def test_rejected_authority_does_not_boost_independent_observations(self):
        snap=V.snap({'HI':[P.sig('PROB')]},ft=V.forward(30,-100),recs=[P.rec('HI',flags=['STAGE1_EXTREME'])])
        row=emerging(DE.build(snap))[0]
        self.assertEqual([e['type'] for e in row['positive_evidence']],['LARGE_24H_MOVE'])
        self.assertEqual(row['ranking_inputs']['primary_evidence_count'],1)

    def test_parent_comparison_preserves_directional_gates_portfolio_and_sources(self):
        root=Path(__file__).resolve().parents[1]
        source=subprocess.check_output(['git','-c','safe.directory=*','show','cb785719cf8719d8513d70baa6fd7807c1ea65ff:v8/decision.py'],cwd=root).decode()
        node=next(n for n in ast.parse(source).body if isinstance(n,ast.FunctionDef) and n.name=='_emerging')
        namespace=dict(DE.__dict__);exec(compile(ast.Module(body=[node],type_ignores=[]),'parent-emerging','exec'),namespace)
        snap=V.snap({'HI':[P.sig('TSMOM')],'LO':[P.sig('PROB')],'NEG':[P.sig('REQ')]},
                    recs=[P.rec('HI'),P.rec('LO',liq=('KNOWN',3e4,False)),P.rec('NEG')])
        original=copy.deepcopy(snap)
        with patch.object(DE,'_emerging',namespace['_emerging']):before=DE.build(snap)
        after=DE.build(snap)
        for key in ('portfolio','best_trades_now','funding_opportunities','strategy_tiers'):
            self.assertEqual(before[key],after[key],key)
        self.assertEqual([c for c in before['candidates'] if c['type']!=DE.EMERGING],
                         [c for c in after['candidates'] if c['type']!=DE.EMERGING])
        self.assertEqual([r['asset'] for r in emerging(before)],['HI','LO'])
        self.assertEqual([r['asset'] for r in emerging(after)],['LO'])
        self.assertEqual(snap,original)
