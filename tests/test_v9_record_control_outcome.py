import json
from unittest.mock import patch
import unittest
from tests import test_v9_control_outcome_publish as fixture
from tools.v9 import record_control_outcome as R, record_run as H


class History(unittest.TestCase):
    def setUp(self):
        self.f=fixture.Publish();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.f.retain()
        self.files={p.relative_to(self.f.out).as_posix():p.read_bytes() for p in self.f.out.rglob('*') if p.is_file()}
        self.original=self.files['reservation.json']

    def inspect(self):
        with patch.object(R,'INPUT_HASH',self.f.digest):
            return R.inspect(self.files.__getitem__,lambda p:R.sha(self.files[p]),list(self.files),
                lambda p:(fixture.P.ROOT/p).read_bytes(),'b'*40,'c'*40,self.original,'2026-10-24T00:00:00Z')

    def test_verified_attempt_still_has_no_strategy_authority(self):
        record=self.inspect()
        self.assertEqual(record['study'],'A6');self.assertEqual(record['confirmed'],[])
        self.assertFalse(record['retained_result_independently_verified'])
        self.assertEqual(record['file_paths']['report'],'audit/audit.json')
        self.assertEqual(record['retained_files_sha256']['reservation.json'],R.sha(self.original))

    def test_reservation_only_and_started_are_recordable(self):
        files=self.files;self.files={'reservation.json':self.original}
        record=self.inspect();self.assertEqual(record['status'],'INCOMPLETE_RESERVED');self.assertIsNone(record['files']['trades'])
        self.files=files;attempt=json.loads(self.files['attempt.json']);attempt['status']='STARTED';attempt.pop('artifacts_sha256')
        self.files['attempt.json']=json.dumps(attempt).encode()
        self.assertEqual(self.inspect()['status'],'STARTED')

    def test_partial_failure_retained_without_confirmation(self):
        attempt=json.loads(self.files['attempt.json']);attempt['status']='FAILED_OR_PARTIAL';attempt['audit_exit']=1
        self.files['attempt.json']=json.dumps(attempt).encode()
        record=self.inspect();self.assertEqual(record['status'],'FAILED_OR_PARTIAL');self.assertEqual(record['confirmed'],[])

    def test_changed_reservation_artifact_and_authority_rejected(self):
        original=dict(self.files)
        for target in ('reservation','artifact','authority'):
            self.files=dict(original)
            if target=='reservation':self.files['reservation.json']+=b' '
            if target=='artifact':self.files['outcomes.log']+=b'changed'
            if target=='authority':
                attempt=json.loads(self.files['attempt.json']);attempt['promotion_authority']=True
                self.files['attempt.json']=json.dumps(attempt).encode()
            with self.subTest(target=target),self.assertRaises(ValueError):self.inspect()

    def test_append_preserves_chain_and_refuses_duplicate(self):
        record=self.inspect();path=str(self.f.root/'history.jsonl')
        H.append(record,path);self.assertEqual(H.verify(H.read(path)),[])
        before=(self.f.root/'history.jsonl').read_bytes()
        with self.assertRaises(SystemExit):H.append(record,path)
        self.assertEqual(before,(self.f.root/'history.jsonl').read_bytes())

    def test_record_run_routes_a6_to_its_builder(self):
        with patch.object(R,'build',return_value={'synthetic':True}) as build:
            self.assertEqual(H.build('A6','repo'),{'synthetic':True})
            build.assert_called_once_with('repo','origin/evidence-a6-outcome-results')


class RetainedAncestry(unittest.TestCase):
    def setUp(self):
        import os
        import subprocess
        import tempfile
        from pathlib import Path
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.repo=Path(self.temp.name)
        self.env={k:v for k,v in os.environ.items() if not k.startswith('GIT_')}
        self.env.update(GIT_CONFIG_GLOBAL=os.devnull,GIT_CONFIG_SYSTEM=os.devnull,
            GIT_AUTHOR_NAME='Synthetic',GIT_AUTHOR_EMAIL='synthetic@example.invalid',
            GIT_COMMITTER_NAME='Synthetic',GIT_COMMITTER_EMAIL='synthetic@example.invalid')
        self.git=lambda *args:subprocess.check_output(['git','-c','safe.directory=*','-c',
            'core.hooksPath='+os.devnull,'-c','commit.gpgsign=false','-C',str(self.repo),*args],env=self.env,stderr=subprocess.PIPE)
        self.git('init','--quiet','--template=')
        self.raw=b'{"status":"RESERVED"}'
        self.root=self.commit({'reservation.json':self.raw})

    def commit(self,files,parents=(),mode='100644'):
        import subprocess
        entries=[]
        for name,raw in sorted(files.items()):
            path=self.repo/'blob';path.write_bytes(raw)
            blob=self.git('hash-object','-w',str(path)).decode().strip()
            entries.append(f'{mode} blob {blob}\t{name}\n')
        process=subprocess.run(['git','-C',str(self.repo),'mktree'],input=''.join(entries).encode(),
            env=self.env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=True)
        args=['commit-tree',process.stdout.decode().strip(),'-m','synthetic']
        for parent in parents:args+=['-p',parent]
        return self.git(*args).decode().strip()

    def test_reservation_and_interrupted_partial_descendants(self):
        self.assertEqual(R.verify_ancestry(self.git,self.root),(self.root,self.raw))
        partial=self.commit({'reservation.json':self.raw,'partial.log':b'interrupted'},[self.root])
        self.assertEqual(R.verify_ancestry(self.git,partial),(self.root,self.raw))

    def test_changed_then_restored_reservation_rejected(self):
        changed=self.commit({'reservation.json':b'changed'},[self.root])
        restored=self.commit({'reservation.json':self.raw},[changed])
        with self.assertRaisesRegex(ValueError,'changed within'):R.verify_ancestry(self.git,restored)

    def test_result_payload_in_reservation_root_rejected(self):
        root=self.commit({'reservation.json':self.raw,'outcome.json':b'{}'})
        with self.assertRaisesRegex(ValueError,'root must contain only'):R.verify_ancestry(self.git,root)

    def test_merge_and_nonregular_files_rejected(self):
        left=self.commit({'reservation.json':self.raw,'left':b'a'},[self.root])
        right=self.commit({'reservation.json':self.raw,'right':b'b'},[self.root])
        merged=self.commit({'reservation.json':self.raw},[left,right])
        with self.assertRaisesRegex(ValueError,'linear'):R.verify_ancestry(self.git,merged)
        link=self.commit({'reservation.json':self.raw},[self.root],mode='120000')
        with self.assertRaisesRegex(ValueError,'regular'):R.verify_ancestry(self.git,link)

    def test_shallow_history_rejected(self):
        (self.repo/'.git/shallow').write_text(self.root+'\n')
        with self.assertRaisesRegex(ValueError,'complete reservation'):R.verify_ancestry(self.git,self.root)
