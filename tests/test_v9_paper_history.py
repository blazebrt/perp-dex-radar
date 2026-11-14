"""Synthetic capture and local-Git publication only; no hosted writes."""
import contextlib
import gzip
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from v9 import paper_history as H


def fixture(root, *, closed=None, tiers=None, stamp=1000):
    decision = dict(schema='v8.decision/1', as_of=stamp, valid_until=stamp+100,
                    strategy_tiers=tiers if tiers is not None else {'FULL': [], 'PROBATION': []})
    journal = dict(open=[], closed=closed if closed is not None else [dict(id='old', s='X', c='BTC', d=1, t_in=10, r=None)])
    refs = []
    for path, doc in [('data/v8/decision.json', decision), ('data/quant_journal.json', journal)]:
        raw=H.canonical(doc); p=root/path;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(raw)
        refs.append(dict(path=path,bytes=len(raw),sha256=H.sha(raw)))
    audit=dict(manifest=dict(ts=stamp,decision=dict(status='OK',file=refs[0])),legacy_output_refs=[refs[1]])
    (root/'data/v8/audit_latest.json').write_bytes(H.canonical(audit))


class Capture(unittest.TestCase):
    def test_content_addressed_deterministic_and_no_retroactive_authority(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);fixture(root)
            files,snapshot=H.package(root);self.assertEqual((files,snapshot),H.package(root))
            doc=H.decode(gzip.decompress(files[snapshot]))
            self.assertFalse(doc['trade_authorization'])
            self.assertEqual(doc['historical_entry_authority'],'UNRECORDED_NOT_INFERRED')
            self.assertTrue(doc['source_bindings_verified'])
            record=doc['records'][0];body=gzip.decompress(files[record['path']])
            self.assertEqual(record['sha256'],H.sha(body))
            self.assertIsNone(H.decode(body)['record']['r'])
            self.assertNotIn('entry_tier',H.decode(body)['record'])
            fixture(root,tiers={'FULL':[{'strategy':'X'}],'PROBATION':[]},stamp=1100)
            newer,newpath=H.package(root)
            self.assertNotEqual(snapshot,newpath)
            self.assertEqual(files[record['path']],newer[record['path']])

    def test_mixed_sources_and_ambiguous_reference_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);fixture(root);(root/'data/quant_journal.json').write_bytes(b'{}')
            with self.assertRaisesRegex(ValueError,'binding'):H.package(root)
            fixture(root);p=root/'data/v8/audit_latest.json';audit=H.decode(p.read_bytes());audit['legacy_output_refs']*=2;p.write_bytes(H.canonical(audit))
            with self.assertRaisesRegex(ValueError,'ambiguous'):H.package(root)

    def test_invalid_rows_duplicate_ids_nonfinite_and_duplicate_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for rows in ([{}],[None],[{'id':'a'},{'id':'a'}],[{'id':True}]):
                fixture(root,closed=rows)
                with self.assertRaises(ValueError):H.package(root)
            for raw in (b'{"x":1,"x":2}',b'{"r":NaN}'):
                with self.assertRaises(ValueError):H.decode(raw)

    def test_archive_reader_checks_content_without_granting_source_authority(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);fixture(root);files,path=H.package(root)
            result=H.verify_archive(files.__getitem__,path)
            self.assertEqual(result['status'],'ARCHIVE_CONTENT_VERIFIED')
            self.assertFalse(result['original_source_documents_reverified'])
            recordpath=result['snapshot']['records'][0]['path']
            files[recordpath]=gzip.compress(b'{}')
            with self.assertRaisesRegex(ValueError,'hash'):H.verify_archive(files.__getitem__,path)
            with self.assertRaisesRegex(ValueError,'snapshot path'):H.verify_archive(files.__getitem__,'../outside')

    def test_cli_preserves_failure_report_without_payload_or_git_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);fixture(root);out=root/'report.json';capture=io.StringIO()
            with patch.object(H,'publish',side_effect=RuntimeError('SECRET')),contextlib.redirect_stdout(capture):
                self.assertEqual(H.main(['--site',str(root),'--report',str(out)]),1)
            self.assertEqual(H.decode(out.read_bytes())['status'],'FAILED')
            self.assertNotIn('SECRET',out.read_text()+capture.getvalue())

    def test_workflow_capture_is_after_audit_main_only_and_nonblocking(self):
        text=(Path(__file__).resolve().parents[1]/'.github/workflows/scan.yml').read_text()
        start=text.index('      - name: v9 paper observation history (')
        end=text.index('      - name: v9 trade alerts',start)
        block=text[start:end]
        self.assertLess(text.index('run: python -m v8.snapshot'),start)
        self.assertIn("github.ref == 'refs/heads/main'",block)
        self.assertIn("steps.core_tests.outcome == 'success'",block)
        self.assertEqual(block.count('continue-on-error: true'),2)
        self.assertIn('python -m v9.paper_history --site site',block)
        self.assertIn('actions/upload-artifact@v4',block)


class LocalPublication(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.repo=self.root/'repo';self.repo.mkdir();self.remote=self.root/'remote.git'
        def cmd(*args,cwd=None):
            return subprocess.check_output(['git','-c','safe.directory=*',*args],cwd=cwd,stderr=subprocess.DEVNULL)
        self.cmd=cmd;cmd('init','--bare',str(self.remote));cmd('init',str(self.repo))
        cmd('config','user.name','Synthetic test',cwd=self.repo);cmd('config','user.email','test@example.invalid',cwd=self.repo)
        (self.repo/'README').write_text('existing market history\n');cmd('add','README',cwd=self.repo);cmd('commit','-m','seed',cwd=self.repo)
        cmd('remote','add','origin',str(self.remote),cwd=self.repo)
        cmd('push','origin','HEAD:refs/heads/'+H.BRANCH,cwd=self.repo)
        self.site=self.root/'site';fixture(self.site)

    def head(self):
        return self.cmd('--git-dir',str(self.remote),'rev-parse','refs/heads/'+H.BRANCH).decode().strip()

    def test_repeated_capture_pruning_and_versions_preserve_all_prior_records(self):
        files,path=H.package(self.site);first=H.publish(self.repo,files,path)
        self.assertEqual(first['status'],'RETAINED_AND_VERIFIED');head=self.head()
        self.assertEqual(H.publish(self.repo,files,path)['status'],'ALREADY_RETAINED');self.assertEqual(head,self.head())
        # The producer drops the old close. The durable record remains reachable.
        fixture(self.site,closed=[{'id':'new','r':0}],stamp=1100);newfiles,newpath=H.package(self.site)
        H.publish(self.repo,newfiles,newpath);allpaths=sorted(set(files)|set(newfiles))
        retained=H.entries(self.repo,self.head(),allpaths);self.assertEqual(set(retained),set(allpaths))
        pinned=self.head()
        recovered=H.verify_archive(lambda p:self.cmd('--git-dir',str(self.remote),'show',pinned+':'+p),path)
        self.assertEqual(recovered['records'][0]['record']['id'],'old')
        self.assertIsNone(recovered['records'][0]['record']['r'])
        self.assertEqual(self.cmd('--git-dir',str(self.remote),'show',self.head()+':README'),b'existing market history\n')
        fixture(self.site,closed=[{'id':'new','r':1}],stamp=1200);versions,versionpath=H.package(self.site)
        H.publish(self.repo,versions,versionpath)
        self.assertEqual(set(H.entries(self.repo,self.head(),allpaths)),set(allpaths))

    def test_equivalent_gzip_preserves_existing_bytes(self):
        files,path=H.package(self.site);H.publish(self.repo,files,path);head=self.head()
        alternative={p:gzip.compress(gzip.decompress(b),compresslevel=1,mtime=0) for p,b in files.items()}
        self.assertEqual(H.publish(self.repo,alternative,path)['status'],'ALREADY_RETAINED')
        self.assertEqual(head,self.head())

    def test_conflicting_existing_object_fails_without_overwrite(self):
        files,path=H.package(self.site);H.publish(self.repo,files,path)
        # Simulate corruption by another writer, never by the publisher under test.
        self.cmd('fetch','origin',H.BRANCH,cwd=self.repo);self.cmd('checkout','-B','corrupt','FETCH_HEAD',cwd=self.repo)
        target=next(p for p in files if '/records/' in p);(self.repo/target).write_bytes(gzip.compress(b'corrupt'))
        self.cmd('add',target,cwd=self.repo);self.cmd('commit','-m','synthetic corruption',cwd=self.repo)
        self.cmd('push','origin','HEAD:refs/heads/'+H.BRANCH,cwd=self.repo);head=self.head()
        with self.assertRaisesRegex(ValueError,'immutable'):H.publish(self.repo,files,path)
        self.assertEqual(head,self.head())

    def test_push_race_retries_without_force(self):
        files,path=H.package(self.site);real=H.git;calls=[];failed=False
        other=self.root/'other';self.cmd('clone','--branch',H.BRANCH,str(self.remote),str(other))
        self.cmd('config','user.name','Other synthetic writer',cwd=other)
        self.cmd('config','user.email','other@example.invalid',cwd=other)
        def race(repo,args,**kwargs):
            nonlocal failed
            calls.append(args)
            if args[0]=='push' and not failed:
                failed=True
                (other/'concurrent-market-record').write_text('preserve me')
                self.cmd('add','concurrent-market-record',cwd=other)
                self.cmd('commit','-m','concurrent synthetic market record',cwd=other)
                self.cmd('push','origin','HEAD:refs/heads/'+H.BRANCH,cwd=other)
            return real(repo,args,**kwargs)
        with patch.object(H,'git',side_effect=race):result=H.publish(self.repo,files,path)
        self.assertEqual(result['status'],'RETAINED_AND_VERIFIED')
        pushes=[args for args in calls if args[0]=='push'];self.assertEqual(len(pushes),2)
        self.assertTrue(all('--force' not in a and not a[-1].startswith('+') for a in pushes))
        self.assertEqual(self.cmd('--git-dir',str(self.remote),'show',self.head()+':concurrent-market-record'),b'preserve me')

    def test_missing_branch_not_created_and_unsafe_paths_rejected(self):
        files,path=H.package(self.site);self.cmd('--git-dir',str(self.remote),'update-ref','-d','refs/heads/'+H.BRANCH)
        with self.assertRaisesRegex(ValueError,'existing history branch'):H.publish(self.repo,files,path)
        self.assertEqual(self.cmd('ls-remote','--heads',str(self.remote)),b'')
        with self.assertRaisesRegex(ValueError,'invalid capture path'):H.publish(self.repo,{**files,'../bad':b'x'},path)


if __name__=='__main__':unittest.main()
