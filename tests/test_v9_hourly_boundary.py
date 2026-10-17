import copy
import csv
import io
import unittest
import zipfile
from datetime import datetime, timedelta

from tools.v9 import hourly_boundary as B
from tools.v9 import hourly_trades as T
from tests.test_v9_hourly_trades import DAY, START


def source(rows, day):
    filename='TESTUSDT-trades-'+day+'.zip'
    s=io.StringIO();csv.writer(s).writerows([T.HEADER]+rows)
    b=io.BytesIO()
    with zipfile.ZipFile(b,'w') as z:z.writestr('trades.csv',s.getvalue())
    raw=b.getvalue()
    return raw,(T.sha(raw)+'  '+filename+'\n').encode(),filename,day


def row(i,t):
    return [str(i),'10','1','10',str(t*1000),'false']


def fixture(side='before', gap=False):
    t=START if side=='before' else START+20*3600
    rows=[row(101+i+(1 if gap and i>=2 else 0),t+i*3600) for i in range(4)]
    if side=='before':rows.append(row(106 if gap else 105,t+14400))
    else:rows.insert(0,row(100,t-1))
    raw,checksum,name,day=source(rows,DAY)
    refs={t:dict(o='10',h='10',l='10',c='10',qv='40',tbqv='40')}
    previous=T.audit(raw,checksum,name,day,refs);previous['coin']='TEST'
    adjacent_day=(datetime.strptime(DAY,'%Y-%m-%d')+timedelta(days=-1 if side=='before' else 1)).strftime('%Y-%m-%d')
    adjacent=source([row(100,START-1)] if side=='before' else [row(106 if gap else 105,START+86400)],adjacent_day)
    return raw,checksum,name,previous,previous['blocks'][0],{side:adjacent}


class BoundaryContinuity(unittest.TestCase):
    def test_both_day_edges_reproduce_and_extend_without_changing_prior(self):
        for side in ('before','after'):
            args=fixture(side);original=copy.deepcopy(args[3])
            d=B.audit(*args)
            self.assertTrue(d['bracketed']);self.assertTrue(d['continuity_checked'])
            self.assertIsNone(d['original'][side]);self.assertIsNotNone(d['extended'][side])
            self.assertEqual(args[3],original)
            self.assertFalse(d['accepted_dataset'])

    def test_internal_gap_is_preserved(self):
        args=fixture(gap=True);d=B.audit(*args)
        self.assertTrue(d['bracketed']);self.assertFalse(d['continuity_checked'])
        self.assertEqual(d['extended_id_gaps'],[[103,104]])

    def test_boundary_gap_reported_and_overlap_rejected(self):
        for ident,raises in [(99,False),(101,True)]:
            args=list(fixture());day=args[-1]['before'][3]
            args[-1]={'before':source([row(ident,START-1)],day)}
            if raises:
                with self.assertRaises(ValueError):B.audit(*args)
            else:
                d=B.audit(*args);self.assertEqual(d['extended_id_gaps'],[[100,101]])
                self.assertFalse(d['continuity_checked'])

    def test_wrong_symbol_day_extra_side_and_checksum_fail(self):
        for change in ('symbol','day','extra','checksum'):
            args=list(fixture());adj=list(args[-1]['before'])
            if change=='symbol':adj[2]=adj[2].replace('TEST','OTHER')
            elif change=='day':adj[3]='2021-12-30'
            elif change=='checksum':adj[1]=b'bad checksum'
            args[-1]={'before':tuple(adj)}
            if change=='extra':args[-1]['after']=tuple(adj)
            with self.subTest(change=change),self.assertRaises(ValueError):B.audit(*args)

    def test_original_hash_and_diagnostic_changes_fail(self):
        for change in ('hash','count','gaps','bracket'):
            args=list(fixture())
            if change=='hash':args[0]+=b'x'
            elif change=='count':args[3]['source_records']+=1
            elif change=='gaps':args[4]['id_gaps']=[[1,2]]
            else:args[4]['bracketed']=True
            with self.subTest(change=change),self.assertRaises(ValueError):B.audit(*args)

    def test_empty_or_malformed_adjacent_source_fails(self):
        for rows in ([],[row(100,START-1),row(100,START-1)],[row(100,START)]):
            args=list(fixture());day=args[-1]['before'][3]
            args[-1]={'before':source(rows,day)}
            with self.assertRaises(ValueError):B.audit(*args)


if __name__=='__main__':unittest.main()
