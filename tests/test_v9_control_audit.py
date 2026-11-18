import copy
import gzip
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from tools.v9 import audit_control_extraction as U, control_extract as E
from tests import test_v9_control_extract as fixtures


class Audit(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.Extraction();self.fixture.setUp()
        self.context=self.fixture.context()
        loaded=self.fixture.fixture.loaded
        self.audit_context=dict(self.context,plan={'trials':self.context['trials']},source_commit='a'*40,
            sources={'A':U.P.Source(loaded['segment'],loaded['times'],loaded['volumes'],[],loaded['source_sha256'])})

    def test_complete_and_partial_only_verify_available_trials(self):
        for failed in (False,True):
            if failed:self.fixture.fixture.raw['hold'][-1]=0
            with tempfile.TemporaryDirectory() as directory:
                E.extract(directory,lambda:self.context)
                self.fixture.calls.clear()
                result=U.audit(directory,self.audit_context)
                self.assertEqual(result['verified_trials'],0 if failed else 2)
                self.assertEqual(len(self.fixture.calls),0 if failed else 2)
                self.assertEqual(result['unavailable_or_failed_trials'],3 if failed else 1)
                self.assertFalse(result['complete_family_population_verified'])

    def test_source_change_or_window_change_rejects_audit(self):
        for change in ('source','window','generator'):
            with tempfile.TemporaryDirectory() as directory:
                E.extract(directory,lambda:self.context)
                context=dict(self.audit_context)
                if change=='window':context['end']-=14400
                if change=='source':
                    context['sources']=copy.deepcopy(context['sources'])
                    context['sources']['A'].rows[29*86400]=9e9
                if change=='generator':
                    raw=copy.deepcopy(self.fixture.fixture.raw);raw['target'][1]=99.
                    context['generate']=lambda trial:raw
                with self.assertRaises(ValueError):U.audit(directory,context)

    def test_preserve_extraction_and_prior_audit(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/'source';out=root/'audit'
            E.extract(source,lambda:self.context)
            before={p.name:p.read_bytes() for p in source.iterdir()}
            U.run(source,out,lambda:self.audit_context)
            self.assertEqual(before,{p.name:p.read_bytes() for p in source.iterdir()})
            with self.assertRaises(ValueError):U.run(source,out,lambda:self.audit_context)
            with self.assertRaises(ValueError):U.run(source,source/'audit',lambda:self.audit_context)

    def test_failed_preflight_has_no_success_report(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            def bad():raise ValueError('changed evidence')
            with self.assertRaises(ValueError):U.run(root/'source',root/'audit',bad)
            self.assertTrue((root/'audit/failure.json').exists())
            self.assertFalse((root/'audit/audit.json').exists())

    def test_independent_archive_reader_and_hash_rejection(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'h4').mkdir()
            raw=gzip.compress(b't,qv\n0,7\n14400,0\n',mtime=0)
            (root/'h4/A.csv.gz').write_bytes(raw)
            universe=json.dumps({'coins':[dict(t='A',symbol='AUSDT',first_bar=0,last_bar=14400,bars=2,excluded=False)]}).encode()
            (root/'universe.json').write_bytes(universe)
            inventory=dict(archive_commit=U.ARCHIVE,source_files_sha256={'universe.json':U.A.digest(universe),
                'h4/A.csv.gz':U.A.digest(raw)},disputed_blocks=[dict(asset='A',open=0)])
            sources=U.read_sources(root,inventory)
            self.assertEqual(sources['A'].rows,{0:7.,14400:0.})
            self.assertEqual(sources['A'].disputes,[0])
            # Real archive identities include relistings and non-Latin names.
            for name in ('A~2','币安人生'):
                doc=json.loads(universe);doc['coins'][0]['t']=name
                changed=json.dumps(doc).encode();(root/'universe.json').write_bytes(changed)
                old=next((root/'h4').iterdir());old.rename(root/'h4'/(name+'.csv.gz'))
                inventory['source_files_sha256']={'universe.json':U.A.digest(changed),'h4/'+name+'.csv.gz':U.A.digest(raw)}
                inventory['disputed_blocks']=[]
                self.assertIn(name,U.read_sources(root,inventory))
            # Restore a valid pinned identity before testing corruption.
            next((root/'h4').iterdir()).rename(root/'h4/A.csv.gz')
            (root/'universe.json').write_bytes(universe)
            inventory['source_files_sha256']={'universe.json':U.A.digest(universe),'h4/A.csv.gz':U.A.digest(raw)}
            (root/'h4/A.csv.gz').write_bytes(raw+b'changed')
            with self.assertRaises(ValueError):U.read_sources(root,inventory)

    def test_changed_original_code_rejected_before_scientific_import(self):
        with patch.object(U,'git_bytes',return_value=b'wrong original'):
            with self.assertRaises(ValueError):U.prepare('absent','absent','a'*40)
