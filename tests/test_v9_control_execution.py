import unittest
from tools.v9 import control_execution as E


def bar(o=100,h=101,l=99,c=100,qv=1000):return dict(o=o,h=h,l=l,c=c,qv=qv)


class Execution(unittest.TestCase):
    def run_trade(self,rows=None,direction=1,**changes):
        args=dict(rows={E.BAR:bar()} if rows is None else rows,decision=E.BAR,direction=direction,
                  geometry=dict(stop=.02,target=0.,trail=0.,be=0.,hold=1),eligible=True,
                  disputed_opens=[],archive_end=10*E.BAR)
        args.update(changes)
        return E.simulate(**args)

    def geometry(self,**changes):return dict(dict(stop=.02,target=0.,trail=0.,be=0.,hold=1),**changes)

    def test_time_costs_and_unknown_funding_both_directions(self):
        for d in (-1,1):
            result=self.run_trade(rows={E.BAR:bar(h=101.5,c=101)},direction=d)
            self.assertEqual(result['exit_time'],2*E.BAR)
            self.assertAlmostEqual(result['gross_R'],d*.5)
            self.assertAlmostEqual(result['cost_R'],.145)
            self.assertAlmostEqual(result['price_after_cost_R'],d*.5-.145)
            self.assertIsNone(result['net_R']);self.assertFalse(result['funding_path_known'])

    def test_stop_precedes_target_and_time(self):
        for d in (-1,1):
            r=self.run_trade(rows={E.BAR:bar(h=103,l=97)},direction=d,geometry=self.geometry(target=1.))
            self.assertEqual(r['reason'],'STOP');self.assertAlmostEqual(r['gross_R'],-1.)

    def test_target_costs_and_favorable_gap_capped(self):
        cases=[(1,bar(h=103,l=99),102),( -1,bar(h=101,l=97),98)]
        for d,candle,price in cases:
            r=self.run_trade(rows={E.BAR:candle},direction=d,geometry=self.geometry(target=1.))
            self.assertEqual(r['exit_price'],price);self.assertAlmostEqual(r['cost_R'],.08)
        r=self.run_trade(rows={E.BAR:bar(),2*E.BAR:bar(o=105,h=106,l=104,c=105)},geometry=self.geometry(target=1.,hold=2))
        self.assertEqual(r['exit_price'],102);self.assertEqual(r['reason'],'TARGET')

    def test_adverse_opening_gap(self):
        for d,candle,price in ((1,bar(o=95,h=96,l=94,c=95),95),(-1,bar(o=105,h=106,l=104,c=105),105)):
            r=self.run_trade(rows={E.BAR:bar(),2*E.BAR:candle},direction=d,geometry=self.geometry(hold=2))
            self.assertEqual(r['reason'],'GAP_STOP');self.assertEqual(r['exit_price'],price)
            self.assertAlmostEqual(r['gross_R'],-2.5)

    def test_trailing_and_breakeven_apply_next_bar(self):
        for mechanism in ('trail','be'):
            g=self.geometry(hold=2,**({mechanism:.01} if mechanism=='trail' else {mechanism:1.}))
            rows={E.BAR:bar(h=103,l=99,c=102),2*E.BAR:bar(o=102,h=103,l=99,c=100)}
            r=self.run_trade(rows=rows,geometry=g)
            self.assertEqual(r['exit_time'],3*E.BAR)
            self.assertEqual(r['exit_price'],101 if mechanism=='trail' else 100)
            self.assertEqual(r['reason'],'TIGHTENED_STOP')
        r=self.run_trade(rows={E.BAR:bar(h=101,l=97,c=98),2*E.BAR:bar(o=98,h=101,l=97,c=100)},
            direction=-1,geometry=self.geometry(hold=2,trail=.01))
        self.assertEqual(r['exit_price'],99)

    def test_missing_disputed_zero_and_malformed_never_filled(self):
        for rows,disputes,reason in (({},[],'MISSING_BAR'),({E.BAR:bar()},[E.BAR],'DISPUTED_BAR'),
                ({E.BAR:bar(qv=0)},[],'ZERO_VOLUME_BAR'),({E.BAR:bar(h=90)},[],'MALFORMED_BAR'),
                ({E.BAR:bar(c=float('nan'))},[],'MALFORMED_BAR')):
            r=self.run_trade(rows=rows,disputed_opens=disputes)
            self.assertEqual(r['status'],'UNEXECUTED');self.assertEqual(r['reason'],reason)
            rows={2*E.BAR:v for _,v in rows.items()};rows[E.BAR]=bar()
            r=self.run_trade(rows=rows,disputed_opens=[2*E.BAR] if disputes else [],geometry=self.geometry(hold=3))
            self.assertEqual(r['status'],'UNRESOLVED_PRICE');self.assertIsNone(r['gross_R'])

    def test_terminal_censor_eligibility_and_independent_reuse(self):
        r=self.run_trade(archive_end=E.BAR);self.assertEqual(r['status'],'UNEXECUTED')
        r=self.run_trade(archive_end=2*E.BAR,geometry=self.geometry(hold=2))
        self.assertEqual(r['reason'],'ARCHIVE_END');self.assertEqual(r['status'],'UNRESOLVED_PRICE')
        r=self.run_trade(eligible=False);self.assertEqual(r['reason'],'ENTRY_INELIGIBLE')
        rows={E.BAR:bar()};before={t:dict(v) for t,v in rows.items()}
        self.assertEqual(self.run_trade(rows=rows),self.run_trade(rows=rows));self.assertEqual(rows,before)
        future=dict(rows);future[9*E.BAR]=bar(h=1000)
        self.assertEqual(self.run_trade(rows=rows),self.run_trade(rows=future))

    def test_geometry_rejected_and_hold_is_panel_bars(self):
        for g in (self.geometry(hold=True),self.geometry(stop=0),self.geometry(target=-1),self.geometry(trail=float('inf'))):
            with self.assertRaises(ValueError):self.run_trade(geometry=g)
        rows={t:bar() for t in range(E.BAR,4*E.BAR,E.BAR)}
        r=self.run_trade(rows=rows,geometry=self.geometry(hold=3))
        self.assertEqual(r['exit_time'],4*E.BAR)
        with self.assertRaises(ValueError):self.run_trade(disputed_opens=None)
