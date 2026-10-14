"""Production Research publication only. Standard library; never imports or writes an engine/policy.

Review runs use `research`; this module reads/writes only `research-production`.
The workflow guard AND this module require the current main checkout before a write.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time

SCHEMA = 'v8.production-research/1'
CHANNEL = 'research-production'
FILES = ('research_phase9_summary.json', 'research_strategy_adjudication.json',
         'research_strategy_trial_census.json', 'research_multiple_testing.json',
         'research_matched_controls.json', 'research_phase9_registration_plan.json')
METHOD_FILES = ('strategy_adjudication.py', 'multiple_testing.py', 'matched_controls.py',
                'strategy_census.py', '../../v8/strategy_authority.py', '../../v8/strategy_policy.py')
BINDINGS = ('main_sha', 'tree_sha', 'strategy_policy_hash', 'runtime_implementation_hash', 'method_code_hash')


def canonical(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n').encode()


def file_hash(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def digest(value):
    return hashlib.sha256(canonical(value)[:-1]).hexdigest()


def git(root, *args, env=None):
    return subprocess.check_output(['git', '-c', 'safe.directory=*', '-C', str(root), *args], env=env).decode().strip()


def authority(root):
    root = Path(root)
    names = ['quant.py', 'v8/quant_strategy_policy.json'] + [n[6:] if n.startswith('../../') else 'tools/research/' + n for n in METHOD_FILES]
    objects = {line.split('\t', 1)[1]: line.split('\t', 1)[0].split()[2]
               for line in git(root, 'ls-tree', '-r', 'HEAD', '--', *names).splitlines()}
    for name in names:
        raw = (root / name).read_bytes()
        if hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest() != objects.get(name):
            raise ValueError('PRODUCTION_CODE_TREE_MISMATCH: ' + name)
    policy = json.loads((root / 'v8/quant_strategy_policy.json').read_text())
    method = {n: hashlib.sha256((root / 'tools/research' / n).read_text(encoding='utf-8').encode()).hexdigest()
              for n in METHOD_FILES}
    return {'schema': 'v8.production-research-authority/1', 'main_sha': git(root, 'rev-parse', 'HEAD'),
            'tree_sha': git(root, 'rev-parse', 'HEAD^{tree}'), 'strategy_policy_hash': digest(policy),
            'runtime_implementation_hash': digest({'quant.py': hashlib.sha256((root / 'quant.py').read_bytes()).hexdigest()}),
            'method_code_hash': digest(method), 'strategy_policy': policy}


def main_context(root, context, remote_main):
    """No branch-name heuristic: event, exact ref, workflow ref, checkout and live main must all agree."""
    a = authority(root)
    if not (context.get('ref') == 'refs/heads/main' and context.get('default_branch') == 'main'
            and context.get('event') in ('schedule', 'workflow_dispatch')
            and context.get('workflow_ref', '').endswith('/.github/workflows/research.yml@refs/heads/main')
            and context.get('sha') == a['main_sha'] == remote_main):
        raise ValueError('PRODUCTION_MAIN_AUTHORITY_REQUIRED')
    return a


def validate(snapshot):
    if not isinstance(snapshot, dict) or snapshot.get('schema') != SCHEMA:
        raise ValueError('PRODUCTION_RESEARCH_SCHEMA')
    source = snapshot.get('source', {})
    a, docs = snapshot.get('authority', {}), snapshot.get('documents', {})
    if not all(isinstance(v, dict) for v in (source, a, docs)):
        raise ValueError('PRODUCTION_RESEARCH_SHAPE')
    if source.get('ref') != 'refs/heads/main' or source.get('channel') != CHANNEL or source.get('promotion_authority') != 'NONE':
        raise ValueError('PRODUCTION_RESEARCH_SOURCE')
    if any(not isinstance(a.get(k), str) or len(a[k]) != (40 if k in ('main_sha', 'tree_sha') else 64) for k in BINDINGS):
        raise ValueError('PRODUCTION_RESEARCH_BINDINGS')
    if (source.get('sha') != a['main_sha'] or source.get('workflow') != '.github/workflows/research.yml'
            or source.get('event') not in ('schedule', 'workflow_dispatch')):
        raise ValueError('PRODUCTION_RESEARCH_RUN_AUTHORITY')
    if not isinstance(snapshot.get('generated_at'), int) or snapshot['generated_at'] <= 0:
        raise ValueError('PRODUCTION_RESEARCH_TIME')
    if set(docs) != set(FILES) or snapshot.get('file_hashes') != {n: file_hash(docs[n]) for n in FILES}:
        raise ValueError('PRODUCTION_RESEARCH_FILE_BINDING')
    s, ad = docs[FILES[0]], docs[FILES[1]]
    if (not all(isinstance(v, dict) for v in docs.values()) or not isinstance(s.get('strategies'), list)
            or not isinstance(ad.get('strategies'), list)
            or any(not isinstance(r, dict) for r in s['strategies'] + ad['strategies'])):
        raise ValueError('PRODUCTION_RESEARCH_DOCUMENT_SHAPE')
    p = ad.get('provenance', {})
    if not isinstance(p, dict):
        raise ValueError('PRODUCTION_RESEARCH_PROVENANCE')
    if (s.get('schema') != 'v8.phase9-summary/1' or ad.get('schema') != 'v8.strategy-research/1'
            or s.get('adjudication_hash') != file_hash(ad)
            or s.get('trial_census_hash') != file_hash(docs[FILES[2]])
            or ad.get('runtime_policy_hash') != a['strategy_policy_hash']
            or ad.get('runtime_implementation_hash') != a['runtime_implementation_hash']
            or p.get('method_code_hash') != a['method_code_hash']
            or p != snapshot.get('provenance') or not isinstance(p.get('cutoff'), int) or p['cutoff'] > snapshot['generated_at']
            or not all(isinstance(p.get(k), str) and len(p[k]) == 64 for k in ('dataset_sha256', 'history_cutoff_view_hash'))):
        raise ValueError('PRODUCTION_RESEARCH_PROVENANCE')
    for key, name in (('matched_control_hash', FILES[4]), ('multiple_testing_hash', FILES[3])):
        if any(r.get(key) != file_hash(docs[name]) for r in ad.get('strategies', [])):
            raise ValueError('PRODUCTION_RESEARCH_EVIDENCE_BINDING')
    if any(docs[n].get('provenance') != p for n in FILES[3:5]):
        raise ValueError('PRODUCTION_RESEARCH_DATASET_BINDING')
    run = snapshot.get('run_provenance', {})
    if (run.get('head') != a['main_sha'] or run.get('tree') != a['tree_sha']
            or run.get('cutoff') != p['cutoff'] or not run.get('history_verify', {}).get('ok')):
        raise ValueError('PRODUCTION_RESEARCH_CHECKOUT_BINDING')
    return snapshot


def build(root, results, context, remote_main, now=None):
    a = main_context(root, context, remote_main)
    results = Path(results)
    for phase in (9, 10, 11, 12):
        rc = json.loads((results / f'research_phase{phase}_exit.json').read_text())
        if rc.get('head') != a['main_sha'] or rc.get('exit_code') != 0:
            raise ValueError('REQUIRED_RESEARCH_VALIDATION_FAILED')
    run = json.loads((results / 'research_phase9_run_provenance.json').read_text())
    if run.get('head') != a['main_sha'] or run.get('tree') != a['tree_sha'] or not run.get('history_verify', {}).get('ok'):
        raise ValueError('RESEARCH_CHECKOUT_OR_HISTORY_MISMATCH')
    docs = {n: json.loads((results / n).read_text()) for n in FILES}
    snapshot = {'schema': SCHEMA, 'source': {'channel': CHANNEL, 'ref': 'refs/heads/main', 'sha': a['main_sha'],
                'promotion_authority': 'NONE', 'workflow': '.github/workflows/research.yml',
                'run_id': context.get('run_id'), 'run_attempt': context.get('run_attempt'), 'event': context['event']},
                'authority': {k: a[k] for k in BINDINGS}, 'generated_at': int(now if now is not None else time.time()),
                'provenance': docs[FILES[1]]['provenance'], 'run_provenance': run,
                'file_hashes': {n: file_hash(docs[n]) for n in FILES}, 'documents': docs}
    return validate(snapshot)


def replace_file(path, data):
    """Stage complete validated bytes beside the target, then replace atomically; failure leaves prior bytes."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as f:
        tmp = Path(f.name)
        f.write(canonical(data))
    try:
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def publish(root, snapshot, context):
    validate(snapshot)
    live = git(root, 'ls-remote', 'origin', 'refs/heads/main').split()[0]
    a = main_context(root, context, live)
    if any(snapshot['authority'][k] != a[k] for k in BINDINGS):
        raise ValueError('PRODUCTION_RESEARCH_STALE_CHECKOUT')
    previous = git(root, 'ls-remote', 'origin', 'refs/heads/' + CHANNEL)
    parent = previous.split()[0] if previous else None
    if parent:
        git(root, 'fetch', '-q', 'origin', parent)
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / 'snapshot.json'
        path.write_bytes(canonical(snapshot))
        env = {**os.environ, 'GIT_INDEX_FILE': str(Path(temp) / 'index'),
               'GIT_AUTHOR_NAME': 'perp-dex-radar', 'GIT_AUTHOR_EMAIL': 'actions@users.noreply.github.com',
               'GIT_COMMITTER_NAME': 'perp-dex-radar', 'GIT_COMMITTER_EMAIL': 'actions@users.noreply.github.com'}
        git(root, 'read-tree', '--empty', env=env)
        sha = git(root, 'hash-object', '-w', str(path))
        git(root, 'update-index', '--add', '--cacheinfo', '100644,' + sha + ',snapshot.json', env=env)
        tree = git(root, 'write-tree', env=env)
        args = ['commit-tree', tree, '-m', 'Validated production Research ' + a['main_sha'][:12]]
        if parent:
            args += ['-p', parent]
        commit = git(root, *args, env=env)
        # Recheck live main immediately before the atomic, non-force ref update.
        if git(root, 'ls-remote', 'origin', 'refs/heads/main').split()[0] != a['main_sha']:
            raise ValueError('PRODUCTION_MAIN_CHANGED')
        git(root, 'push', 'origin', commit + ':refs/heads/' + CHANNEL)
        return commit


def site(root, out, snapshot=None, failed_attempt=None, now=None):
    a = authority(root)
    state = 'BASELINE_ONLY'
    if snapshot is not None:
        try:
            validate(snapshot)
            state = 'CURRENT' if all(snapshot['authority'][k] == a[k] for k in BINDINGS) else 'AUTHORITY_MISMATCH'
            if state == 'CURRENT' and (failed_attempt or int(now or time.time()) - snapshot['generated_at'] > 36 * 3600):
                state = 'LAST_KNOWN_GOOD'
            replace_file(Path(out) / 'current/snapshot.json', snapshot)
        except (ValueError, KeyError, TypeError):
            state = 'BASELINE_ONLY'
    a.update(evidence_status=state, failed_attempt=failed_attempt, generated_at=int(now or time.time()))
    replace_file(Path(out) / 'authority.json', a)
    return a


def context():
    return {'ref': os.getenv('GITHUB_REF'), 'sha': os.getenv('GITHUB_SHA'), 'event': os.getenv('GITHUB_EVENT_NAME'),
            'workflow_ref': os.getenv('GITHUB_WORKFLOW_REF', ''), 'default_branch': os.getenv('PRODUCTION_DEFAULT_BRANCH'),
            'run_id': os.getenv('GITHUB_RUN_ID'), 'run_attempt': os.getenv('GITHUB_RUN_ATTEMPT')}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=('build', 'publish', 'site'))
    p.add_argument('--root', default='.')
    p.add_argument('--results', default='.')
    p.add_argument('--snapshot', default='production_research_snapshot.json')
    p.add_argument('--out', default='site/data/v8/research')
    args = p.parse_args()
    if args.action == 'build':
        live = git(args.root, 'ls-remote', 'origin', 'refs/heads/main').split()[0]
        replace_file(args.snapshot, build(args.root, args.results, context(), live))
    elif args.action == 'publish':
        print(publish(args.root, json.loads(Path(args.snapshot).read_text()), context()))
    else:
        doc = None
        try:
            # Only this explicit channel is read; no generic review branch fallback exists.
            git(args.root, 'fetch', '-q', 'origin', 'refs/heads/' + CHANNEL)
            doc = json.loads(git(args.root, 'show', 'FETCH_HEAD:snapshot.json'))
        except (subprocess.CalledProcessError, ValueError):
            pass
        attempt = None
        try:
            raw = subprocess.check_output(['gh', 'api', 'repos/' + os.environ['GITHUB_REPOSITORY'] +
                '/actions/workflows/research.yml/runs?branch=main&status=completed&per_page=10'])
            runs = json.loads(raw)['workflow_runs']
            for run in runs:
                if (doc and run['head_sha'] == authority(args.root)['main_sha'] and run['head_branch'] == 'main'
                        and run['event'] in ('schedule', 'workflow_dispatch') and run['conclusion'] != 'success'
                        and int(run['id']) > int(doc['source']['run_id'])):
                    attempt = {'run_id': run['id'], 'conclusion': run['conclusion']}
                    break
        except (KeyError, ValueError, OSError, subprocess.CalledProcessError):
            pass
        print(json.dumps(site(args.root, args.out, doc, attempt)))


if __name__ == '__main__':
    main()
