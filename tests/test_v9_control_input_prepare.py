import hashlib
import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch
from tools.v9 import control_input_prepare as I
from tests import test_v9_record_control_outcome as fixture


class InputPreparation(unittest.TestCase):
    def setUp(self):
        self.f=fixture.RetainedAncestry();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.root=self.f.repo;self.out=self.root/'export'

    def test_raw_export_preserves_bytes_and_refuses_overwrite(self):
        commit=self.f.commit({'data.bin':b'raw\x00\r\n','manifest.json':b'{}'})
        logs=[];I.export(self.root,commit,'',self.out,logs.append)
        self.assertEqual((self.out/'data.bin').read_bytes(),b'raw\x00\r\n')
        self.assertEqual(logs[0]['sha256'],hashlib.sha256(b'raw\x00\r\n').hexdigest())
        with self.assertRaises(FileExistsError):I.export(self.root,commit,'',self.out,logs.append)

    def test_unsafe_and_nonregular_git_entries_refused(self):
        for name in ('../escape','/absolute','a/../escape','a\\b','.git/config','a:b'):
            with self.subTest(name=name),self.assertRaises(ValueError):I.entries(('100644 blob '+'a'*40+'\t'+name+'\0').encode())
        commit=self.f.commit({'link':b'target'},mode='120000')
        with self.assertRaisesRegex(ValueError,'regular Git blobs'):I.export(self.root,commit,'',self.out,lambda r:None)
        self.assertFalse(self.out.exists())

    def test_full_preparation_uses_pinned_objects_without_network(self):
        archive=self.f.commit({'universe.json':b'{}'});evidence=self.f.commit({'evidence.json':b'{"evidence":true}'})
        extraction=self.f.commit({'manifest.json':b'{"signals":true}'})
        tree=self.f.git('rev-parse',extraction+'^{tree}').decode().strip()
        root_tree=subprocess.run(['git','-C',str(self.root),'mktree'],input=('040000 tree '+tree+'\textraction\n').encode(),env=self.f.env,stdout=subprocess.PIPE,check=True).stdout.decode().strip()
        signal_commit=self.f.git('commit-tree',root_tree,'-m','synthetic extraction').decode().strip()
        original=I.git;fetches=[]
        def local(repo,*args,**kwargs):
            if args[0]=='fetch':fetches.append(args[-1]);return b''
            return original(repo,*args,**kwargs)
        with patch.object(I,'ARCHIVE',archive),patch.object(I,'EVIDENCE',evidence),patch.object(I,'ORIGINAL',self.f.root),patch.object(I.P,'INPUT_COMMIT',signal_commit),patch.object(I,'EVIDENCE_HASH',hashlib.sha256(b'{"evidence":true}').hexdigest()),patch.object(I.P,'INPUT_HASH',hashlib.sha256(b'{"signals":true}').hexdigest()),patch.object(I,'git',side_effect=local):
            I.prepare(self.root,self.root/'md',self.root/'evidence.json',self.root/'signals',self.root/'preparation.log')
        self.assertEqual(fetches,[archive,evidence,signal_commit,self.f.root])
        self.assertEqual((self.root/'signals/manifest.json').read_bytes(),b'{"signals":true}')
        self.assertEqual(json.loads((self.root/'preparation.log').read_text().splitlines()[-1])['stage'],'PREPARED_PINNED_INPUTS')

    def test_failed_fetch_leaves_log_and_blocks_retry(self):
        args=(self.root,self.root/'md',self.root/'evidence.json',self.root/'signals',self.root/'preparation.log')
        with patch.object(I,'git',side_effect=RuntimeError('synthetic fetch failure')):
            with self.assertRaises(RuntimeError):I.prepare(*args)
        self.assertEqual(json.loads(args[-1].read_text().splitlines()[-1])['stage'],'FAILED_PARTIAL_INPUTS_PRESERVED')
        with self.assertRaises(FileExistsError):I.prepare(*args)

    def test_corrupted_blob_export_is_detected_and_preserved(self):
        target=self.root/'corrupted'
        def corrupt(repo,*args,output=None):output.write(b'changed bytes')
        with patch.object(I,'git',side_effect=corrupt):
            with self.assertRaisesRegex(ValueError,'blob mismatch'):I.blob(self.root,'a'*40,target)
        self.assertEqual(target.read_bytes(),b'changed bytes')
