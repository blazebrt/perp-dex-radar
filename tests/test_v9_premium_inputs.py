"""D4 input safety on synthetic premium-index archives only."""
import copy
import csv
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import zipfile
from tools.v9 import premium_inputs as P

DAY=1577836800
MEMBER='BTCUSDT-4h-2020-01-01.csv'


def row(i=0,o='-0.001',h='0.002',l='-0.003',c='0'):
    t=(DAY+i*P.BAR)*1000
    return [str(t),o,h,l,c,'IGNORED',str(t+P.BAR*1000-1),'IGNORED','IGNORED','IGNORED','IGNORED','IGNORED']


def zipped(rows,member=MEMBER,header=True,extra=False):
    text=io.StringIO();writer=csv.writer(text,lineterminator='\n')
    if header:writer.writerow(P.HEADER)
    writer.writerows(rows)
    out=io.BytesIO()
    with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(member,text.getvalue())
        if extra:archive.writestr('other.csv','x')
    return out.getvalue()


class Premium(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)/'sources';self.root.mkdir()
        self.manifest=dict(schema='v9.premium-input/1',segments=[dict(segment_id='BTC',symbol='BTCUSDT',start=DAY,end=DAY+P.DAY)],files=[])
        self.cutoff=DAY+3*P.DAY

    def source(self,rows,**kwargs):
        raw=zipped(rows,**kwargs);(self.root/'input.zip').write_bytes(raw)
        ref=dict(symbol='BTCUSDT',day='2020-01-01',path='input.zip',bytes=len(raw),sha256=P.sha(raw),
                 retrieved_at=DAY+2*P.DAY,
                 source_key='data/futures/um/daily/premiumIndexKlines/BTCUSDT/4h/BTCUSDT-4h-2020-01-01.zip')
        self.manifest['files']=[ref];return ref

    def audit(self):return P.audit(self.manifest,self.root,self.cutoff)

    def test_negative_and_zero_are_observations_not_missing_or_funding(self):
        self.source([row(0),row(2,c='0.00000000000000000000000001')]);original=copy.deepcopy(self.manifest)
        report=self.audit();seg=report['segments'][0]
        self.assertEqual((seg['observed_bars'],seg['missing_bars']),(2,4))
        self.assertEqual(seg['rows'][0]['premium_close'],'0')
        self.assertEqual(seg['rows'][0]['premium_open'],'-0.001')
        self.assertEqual(seg['rows'][1]['premium_close'],'1E-26')
        self.assertEqual(seg['missing_intervals'],[dict(start=DAY+P.BAR,end=DAY+2*P.BAR),dict(start=DAY+3*P.BAR,end=DAY+P.DAY)])
        self.assertIsNone(seg['rows'][0]['historical_publication_time'])
        self.assertFalse(report['study_eligible']);self.assertFalse(report['trade_authorization'])
        self.assertNotIn('funding',seg['rows'][0]);self.assertNotIn('price',seg['rows'][0])
        self.assertEqual(self.manifest,original);self.assertEqual(report,self.audit())

    def test_closed_bar_does_not_imply_historical_availability(self):
        self.source([row()]);report=self.audit()
        self.assertEqual(P.known_at(report,'BTC',DAY+P.BAR),[])
        self.assertEqual(P.known_at(report,'BTC',DAY+2*P.DAY-1),[])
        known=P.known_at(report,'BTC',DAY+2*P.DAY)
        self.assertEqual(len(known),1);known[0]['premium_close']='999'
        self.assertEqual(report['segments'][0]['rows'][0]['premium_close'],'0')
        with self.assertRaises(ValueError):P.known_at(report,'missing',self.cutoff)

    def test_empty_inputs_keep_the_entire_expected_grid_missing(self):
        report=self.audit();self.assertEqual(report['status'],'NO_SOURCE_FILES')
        self.assertEqual(report['missing_bars'],6);self.assertEqual(report['segments'][0]['rows'],[])
        with self.assertRaises(ValueError):P.known_at(report,'BTC',self.cutoff)
        self.source([])
        with self.assertRaisesRegex(ValueError,'row count'):self.audit()

    def test_segment_gaps_relisting_and_outside_accounting(self):
        self.manifest['segments']=[dict(segment_id='BTC',symbol='BTCUSDT',start=DAY,end=DAY+P.BAR),
                                   dict(segment_id='BTC~2',symbol='BTCUSDT',start=DAY+2*P.BAR,end=DAY+3*P.BAR)]
        self.source([row(0),row(1),row(2)])
        report=self.audit();self.assertEqual([s['observed_bars'] for s in report['segments']],[1,1])
        self.assertEqual(report['sources'][0]['outside_requested_segments'],1)
        self.manifest['segments'][1]['start']=DAY
        with self.assertRaisesRegex(ValueError,'overlapping symbol'):self.audit()

    def test_bad_rows_units_close_time_duplicates_and_ohlc_fail(self):
        bad=[]
        for field,value in [(0,str(DAY)),(0,str(DAY*1000000)),(6,str((DAY+P.BAR)*1000)),(1,'NaN'),(1,'1_0'),(2,'Infinity'),(3,'3')]:
            r=row();r[field]=value;bad.append([r])
        bad += [[row(),row()], [row()[:-1]], [row(6)]]
        for rows in bad:
            with self.subTest(rows=rows):
                with self.assertRaises(ValueError):P.parse_day(zipped(rows),DAY,MEMBER)
        self.assertEqual(P.parse_day(zipped([row()],header=False),DAY,MEMBER),P.parse_day(zipped([row()]),DAY,MEMBER))

    def test_source_bindings_contract_and_capture_cutoff_fail(self):
        ref=self.source([row()]);original=copy.deepcopy(ref)
        for key,value in [('source_key',original['source_key'].replace('premiumIndexKlines','klines')),
                          ('retrieved_at',DAY),('retrieved_at',self.cutoff+1),('bytes',True),
                          ('sha256','f'*64),('symbol','ETHUSDT'),('day','2020-02-30')]:
            ref.clear();ref.update(original);ref[key]=value
            with self.subTest(key=key):
                with self.assertRaises(ValueError):self.audit()
        ref.clear();ref.update(original);self.manifest['files'].append(dict(ref))
        with self.assertRaisesRegex(ValueError,'duplicate premium'):self.audit()

    def test_archive_paths_members_and_resource_limits(self):
        for kwargs in ({'member':'../outside.csv'},{'extra':True}):
            with self.assertRaises(ValueError):P.parse_day(zipped([row()],**kwargs),DAY,MEMBER)
        huge=row();huge[5]='0'*2000
        raw=zipped([huge]);self.assertLess(len(raw),1024)
        with patch.object(P,'MAX_ZIP',1024):
            with self.assertRaisesRegex(ValueError,'expanded'):P.parse_day(raw,DAY,MEMBER)
        ref=self.source([row()])
        for path in ('../outside.zip','/outside','C:/outside','a\\b','./input.zip'):
            ref['path']=path
            with self.assertRaises(ValueError):self.audit()
        ref['path']='input.zip'
        with patch.object(P,'MAX_GRID',1):
            with self.assertRaises(ValueError):self.audit()
        with patch.object(P,'MAX_ZIP',10):
            with self.assertRaises(ValueError):self.audit()
        with patch.object(P,'MAX_FILES',0):
            with self.assertRaises(ValueError):self.audit()

    def test_cli_refuses_overwrite_and_source_destination(self):
        self.source([row()]);path=Path(self.tmp.name)/'manifest.json';path.write_bytes(P.canonical(self.manifest))
        out=Path(self.tmp.name)/'report.json'
        args=['--manifest',str(path),'--root',str(self.root),'--as-of',str(self.cutoff),'--out',str(out)]
        self.assertEqual(P.main(args),0);raw=out.read_bytes()
        with self.assertRaises(FileExistsError):P.main(args)
        self.assertEqual(out.read_bytes(),raw)
        args[-1]=str(self.root/'report.json')
        with self.assertRaises(ValueError):P.main(args)
