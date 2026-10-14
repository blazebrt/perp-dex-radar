"""Adversarial production/review channel isolation and informational Research UX."""
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from tools.research import production_publication as P

ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which('node')


def context(a):
    return {'ref': 'refs/heads/main', 'sha': a['main_sha'], 'event': 'schedule', 'default_branch': 'main',
            'workflow_ref': 'blazebrt/perp-dex-radar/.github/workflows/research.yml@refs/heads/main',
            'run_id': '1234', 'run_attempt': '1'}


def results(folder, a):
    """Synthetic publication input: no computation or promotion; the reviewed baseline is explicitly updated
    with current code bindings so the transport invariants can be exercised without live market requests."""
    docs = {n: json.loads((ROOT / 'research/phase9' / n).read_text()) for n in P.FILES}
    ad = docs[P.FILES[1]]
    ad['runtime_implementation_hash'] = a['runtime_implementation_hash']
    ad['runtime_policy_hash'] = a['strategy_policy_hash']
    ad['provenance']['method_code_hash'] = a['method_code_hash']
    for n in P.FILES[3:5]:
        docs[n]['provenance'] = copy.deepcopy(ad['provenance'])
    for r in ad['strategies']:
        r['multiple_testing_hash'] = P.file_hash(docs[P.FILES[3]])
        r['matched_control_hash'] = P.file_hash(docs[P.FILES[4]])
    docs[P.FILES[0]]['adjudication_hash'] = P.file_hash(ad)
    for n, v in docs.items():
        (folder / n).write_bytes(P.canonical(v))
    for phase in (9, 10, 11, 12):
        (folder / f'research_phase{phase}_exit.json').write_bytes(P.canonical({'head': a['main_sha'], 'exit_code': 0}))
    (folder / 'research_phase9_run_provenance.json').write_bytes(P.canonical({'head': a['main_sha'], 'tree': a['tree_sha'], 'history_verify': {'ok': True}, 'cutoff': ad['provenance']['cutoff']}))


def render(a=None, snapshot=None, baseline=True, now=1792000000):
    base = {k: json.loads((ROOT / 'research/phase9' / n).read_text()) for k, n in
            [('sum', P.FILES[0]), ('adj', P.FILES[1]), ('mt', P.FILES[3]), ('mc', P.FILES[4]), ('reg', P.FILES[5])]} if baseline else None
    payload = json.dumps({'authority': a, 'snapshot': snapshot, 'baseline': base, 'now': now})
    script = 'const D=require(process.argv[1]);let s="";process.stdin.on("data",x=>s+=x);process.stdin.on("end",()=>process.stdout.write(JSON.stringify(D.views.researchPublication(JSON.parse(s)))));'
    return json.loads(subprocess.check_output([NODE, '-e', script, str(ROOT / 'desk.js')], input=payload.encode()))


class Publication(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.a = P.authority(ROOT)
        self.c = context(self.a)
        results(self.folder, self.a)
        self.snap = P.build(ROOT, self.folder, self.c, self.a['main_sha'], now=1791999940)

    def test_production_main_result_accepted(self):
        self.assertEqual(P.validate(self.snap), self.snap)
        self.assertEqual(self.snap['source']['promotion_authority'], 'NONE')

    def test_phase_branch_cannot_build_production_snapshot(self):
        c = {**self.c, 'ref': 'refs/heads/v8/phase-12', 'event': 'push'}
        with self.assertRaisesRegex(ValueError, 'MAIN_AUTHORITY'):
            P.build(ROOT, self.folder, c, self.a['main_sha'])

    def test_workflow_ref_and_remote_main_and_default_branch_are_required(self):
        for key, value in [('workflow_ref', 'repo/.github/workflows/research.yml@refs/heads/v8/phase-12'), ('sha', 'a'*40), ('default_branch', 'other')]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                P.build(ROOT, self.folder, {**self.c, key: value}, self.a['main_sha'])
        with self.assertRaises(ValueError):
            P.build(ROOT, self.folder, self.c, 'a'*40)

    def test_phase_result_with_main_ref_spoof_still_rejected(self):
        p = self.folder / 'research_phase9_run_provenance.json'
        v = json.loads(p.read_text()); v['head'] = 'a'*40; p.write_bytes(P.canonical(v))
        with self.assertRaisesRegex(ValueError, 'CHECKOUT'):
            P.build(ROOT, self.folder, self.c, self.a['main_sha'])

    def test_every_required_validation_failure_refuses_new_snapshot(self):
        for phase in (9, 10, 11, 12):
            p = self.folder / f'research_phase{phase}_exit.json'
            previous = p.read_bytes()
            p.write_bytes(P.canonical({'head': self.a['main_sha'], 'exit_code': 1}))
            with self.subTest(phase=phase), self.assertRaises(ValueError):
                P.build(ROOT, self.folder, self.c, self.a['main_sha'])
            p.write_bytes(previous)

    def test_policy_runtime_and_method_hash_tampering_rejected(self):
        for k in ('strategy_policy_hash', 'runtime_implementation_hash', 'method_code_hash'):
            doc = copy.deepcopy(self.snap); doc['authority'][k] = 'a'*64
            with self.subTest(k=k), self.assertRaises(ValueError):
                P.validate(doc)

    def test_file_tampering_and_generic_review_source_rejected(self):
        doc = copy.deepcopy(self.snap); doc['documents'][P.FILES[0]]['requalified_count'] = 24
        with self.assertRaises(ValueError): P.validate(doc)
        for field, value in [('channel', 'research'), ('ref', 'refs/heads/v8/phase-12'), ('sha', 'a'*40)]:
            doc = copy.deepcopy(self.snap); doc['source'][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError): P.validate(doc)

    def test_site_matching_authority_and_mismatch(self):
        out = self.folder / 'site'
        self.assertEqual(P.site(ROOT, out, self.snap, now=1792000000)['evidence_status'], 'CURRENT')
        for k in ('main_sha', 'strategy_policy_hash', 'runtime_implementation_hash'):
            a = {**self.a, k: 'a' * len(self.a[k])}
            with patch.object(P, 'authority', return_value=a):
                self.assertEqual(P.site(ROOT, out, self.snap)['evidence_status'], 'AUTHORITY_MISMATCH')

    def test_missing_or_invalid_evidence_never_uses_review_result(self):
        out = self.folder / 'site'
        self.assertEqual(P.site(ROOT, out, None)['evidence_status'], 'BASELINE_ONLY')
        doc = copy.deepcopy(self.snap); doc['source']['channel'] = 'research'
        self.assertEqual(P.site(ROOT, out, doc)['evidence_status'], 'BASELINE_ONLY')
        self.assertFalse((out / 'current/snapshot.json').exists())

    def test_failed_new_run_preserves_previous_bytes_and_policy(self):
        target = self.folder / 'snapshot.json'
        P.replace_file(target, self.snap)
        before = target.read_bytes()
        policy = (ROOT / 'v8/quant_strategy_policy.json').read_bytes()
        p = self.folder / 'research_phase12_exit.json'
        p.write_bytes(P.canonical({'head': self.a['main_sha'], 'exit_code': 1}))
        with self.assertRaises(ValueError):
            new = P.build(ROOT, self.folder, self.c, self.a['main_sha'])
            P.replace_file(target, new)
        self.assertEqual(target.read_bytes(), before)
        self.assertEqual((ROOT / 'v8/quant_strategy_policy.json').read_bytes(), policy)
        self.assertEqual(P.site(ROOT, self.folder / 'site', self.snap, {'run_id': 1235, 'conclusion': 'failure'}, now=1792000000)['evidence_status'], 'LAST_KNOWN_GOOD')

    def test_daily_schedule_and_structural_production_guard(self):
        src = (ROOT / '.github/workflows/research.yml').read_text()
        self.assertIn('cron: "17 3 * * *"', src)
        prod = src.split('- name: Publish validated production research')[1].split('- name: Save the results')[0]
        self.assertIn("if: success() && github.ref == 'refs/heads/main'", prod)
        self.assertIn("github.event.repository.default_branch == 'main'", prod)
        self.assertIn("github.event_name == 'schedule' || github.event_name == 'workflow_dispatch'", prod)
        self.assertIn("if: always() && github.ref != 'refs/heads/main'", src)
        self.assertNotIn('production_publication.py publish', src.split('- name: Save the results')[1])

    def test_final_phase9_policy_and_adjudication_method_unchanged(self):
        # v9 phase B changes the reviewed strategy policy on purpose (XSMOM's probation row); tests/test_v9_scope.py
        # proves that change against main at the start of the phase. The adjudication methods stay pinned here.
        for name in ('tools/research/strategy_adjudication.py',
                     'tools/research/matched_controls.py', 'tools/research/multiple_testing.py'):
            original = subprocess.check_output(['git','-c','safe.directory=*','-C',str(ROOT),'show','19596979d4d2f2e700f4a405c4a76c667b167f04:'+name])
            self.assertEqual((ROOT / name).read_bytes(), original, name)

    def test_atomic_channel_publication_simulation(self):
        repo, remote, data = self.folder / 'repo', self.folder / 'remote.git', self.folder / 'results'
        repo.mkdir(); data.mkdir()
        names = ['quant.py', 'v8/quant_strategy_policy.json'] + [str(Path('tools/research', n)) if not n.startswith('../../') else n[6:] for n in P.METHOD_FILES]
        for name in names:
            target = repo / name; target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, target)
        P.git(repo, 'init', '-q', '-b', 'main')
        P.git(repo, 'config', 'user.name', 'Publication simulation')
        P.git(repo, 'config', 'user.email', 'simulation@example.invalid')
        P.git(repo, 'config', 'core.autocrlf', 'false')
        P.git(repo, 'add', '.')
        P.git(repo, 'commit', '-q', '-m', 'Synthetic production authority')
        subprocess.check_call(['git','init','-q','--bare',str(remote)])
        P.git(repo, 'remote', 'add', 'origin', str(remote))
        P.git(repo, 'push', '-q', 'origin', 'main')
        a = P.authority(repo); c = context(a); results(data, a)
        snap = P.build(repo, data, c, a['main_sha'], now=1791999940)
        first = P.publish(repo, snap, c)
        published = P.git(repo, 'ls-remote', 'origin', 'refs/heads/' + P.CHANNEL).split()[0]
        self.assertEqual(first, published)
        with self.assertRaisesRegex(ValueError, 'MAIN_AUTHORITY'):
            P.publish(repo, snap, {**c, 'ref':'refs/heads/v8/phase-12', 'event':'push'})
        (data / 'research_phase12_exit.json').write_bytes(P.canonical({'head': a['main_sha'], 'exit_code': 1}))
        with self.assertRaises(ValueError):
            new = P.build(repo, data, c, a['main_sha'])
            P.publish(repo, new, c)
        self.assertEqual(P.git(repo, 'ls-remote', 'origin', 'refs/heads/' + P.CHANNEL).split()[0], first)
        self.assertEqual((repo / 'v8/quant_strategy_policy.json').read_bytes(), (ROOT / 'v8/quant_strategy_policy.json').read_bytes())
        policy_path = repo / 'v8/quant_strategy_policy.json'
        clean = policy_path.read_bytes()
        policy_path.write_bytes(clean + b'\n')
        with self.assertRaisesRegex(ValueError, 'CODE_TREE_MISMATCH'):
            P.authority(repo)
        policy_path.write_bytes(clean)
        report = {'fixture_main_sha': a['main_sha'], 'production_snapshot_accepted': True,
                  'phase_branch_rejected': True, 'failed_new_computation_kept_exact_previous_commit': True,
                  'previous_snapshot_commit': first, 'policy_bytes_unchanged': True,
                  'site_current_status': P.site(repo, self.folder / 'published-site', snap, now=1792000000)['evidence_status']}
        if NODE:
            report['browser_current_status'] = render(a, snap)['status']
            report['browser_baseline_status'] = render(a, None)['status']
            self.assertEqual(report['browser_current_status'], 'CURRENT')
            self.assertEqual(report['browser_baseline_status'], 'BASELINE_ONLY')
        if os.getenv('P12_SIMULATION_REPORT'):
            P.replace_file(os.environ['P12_SIMULATION_REPORT'], report)


@unittest.skipUnless(NODE, 'node is not installed')
class Browser(Publication):
    def test_current_and_each_authority_mismatch(self):
        self.assertEqual(render(self.a, self.snap)['status'], 'CURRENT')
        for k in P.BINDINGS:
            a = {**self.a, k:'a'*len(self.a[k])}
            v = render(a, self.snap)
            self.assertEqual(v['status'], 'AUTHORITY_MISMATCH', k)
            self.assertIn('not current evidence', v['html'])

    def test_baseline_missing_failed_and_stale_states(self):
        v = render(self.a, None)
        self.assertEqual(v['status'], 'BASELINE_ONLY')
        self.assertIn('Reviewed Phase 9 baseline', v['html'])
        self.assertNotIn('Latest governed production evaluation', v['html'])
        self.assertEqual(render(self.a, None, baseline=False)['status'], 'UNAVAILABLE')
        self.assertEqual(render({**self.a, 'evidence_status':'LAST_KNOWN_GOOD'}, self.snap)['status'], 'LAST_KNOWN_GOOD')
        self.assertEqual(render(self.a, self.snap, now=1792200000)['status'], 'LAST_KNOWN_GOOD')

    def test_generic_review_and_future_snapshot_refused(self):
        for key, value in [('channel','research'), ('ref','refs/heads/v8/phase-12')]:
            doc = copy.deepcopy(self.snap); doc['source'][key] = value
            self.assertEqual(render(self.a, doc)['status'], 'BASELINE_ONLY')
        doc = copy.deepcopy(self.snap); doc['generated_at'] = 1792000001
        self.assertEqual(render(self.a, doc)['status'], 'BASELINE_ONLY')

    def test_requalified_evidence_cannot_promote_runtime_or_create_trade_label(self):
        doc = copy.deepcopy(self.snap)
        doc['documents'][P.FILES[0]]['requalified_count'] = 24
        for r in doc['documents'][P.FILES[0]]['strategies']: r['research_state'] = 'REQUALIFIED'
        v = render(self.a, doc)
        self.assertIn('Legacy holdover', v['html'])
        self.assertIn('Research evidence never promotes or enables a strategy', v['html'])
        self.assertNotIn('st-trade', v['html'])
        self.assertNotIn('Eligible', v['html'])
        self.assertEqual(self.a['strategy_policy']['strategies'][0]['deployment_state'], 'LEGACY_HOLDOVER')

    def test_strings_and_provenance_are_escaped(self):
        evil = '<img src=x onerror=alert(1)><script>alert(2)</script>'
        a = copy.deepcopy(self.a); a['strategy_policy']['strategies'][0]['strategy_id'] = evil
        doc = copy.deepcopy(self.snap); doc['source']['run_id'] = evil
        doc['documents'][P.FILES[0]]['strategies'][0]['strategy_id'] = evil
        v = render(a, doc)
        self.assertNotIn('<img', v['html']); self.assertNotIn('<script', v['html'])
        self.assertIn('&lt;img', v['html'])

    def test_research_loading_has_no_effect_on_today_or_analyzer(self):
        script = 'const D=require(process.argv[1]),TA=require(process.argv[2]);let s="";process.stdin.on("data",x=>s+=x);process.stdin.on("end",()=>{let x=JSON.parse(s);const run=()=>({today:D.views.today(x.doc,x.now),an:TA.decide({coin:"HI",price:100,now:x.now,account:500,risk:.005,src:{decision:x.doc}})});const before=run();D.views.researchPublication({authority:null,snapshot:null});D.views.researchPublication({snapshot:{schema:"wrong"}});process.stdout.write(JSON.stringify({same:JSON.stringify(before)===JSON.stringify(run()),zero:x.doc.best_trades_now.count}));});'
        from tests.test_v8_phase12 import P as fixture
        from v8 import decision as DE
        doc = DE.build(fixture.snapshot([fixture.rec('HI')], {'HI':[fixture.sig('TSMOM')]}))
        value = json.loads(subprocess.check_output([NODE,'-e',script,str(ROOT/'desk.js'),str(ROOT/'analyze.js')],input=json.dumps({'doc':doc,'now':fixture.AS_OF+1}).encode()))
        self.assertTrue(value['same']); self.assertEqual(value['zero'], 0)


if __name__ == '__main__':
    unittest.main()
