"""Append-only observations of paper records; never infer entry-time authority."""
import argparse
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import zlib

BRANCH = 'v9-market-history'
PREFIX = 'paper-observations/'
MAX_SOURCE_BYTES = 64 * 1024 * 1024


def require(condition, message):
    if not condition:
        raise ValueError(message)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode('utf-8')


def sha(data):
    return hashlib.sha256(data).hexdigest()


def pairs(items):
    result = {}
    for key, value in items:
        require(key not in result, 'duplicate JSON key')
        result[key] = value
    return result


def invalid_constant(_):
    raise ValueError('nonfinite JSON')


def decode(raw):
    return json.loads(raw.decode('utf-8'), object_pairs_hook=pairs, parse_constant=invalid_constant)


def bound(raw, ref, path):
    require(isinstance(ref, dict) and ref.get('path') == path and type(ref.get('bytes')) is int
            and ref['bytes'] == len(raw) and ref.get('sha256') == sha(raw), 'source binding mismatch')


def package(directory):
    """Build deterministic, content-addressed records and one source-bound index."""
    directory = Path(directory)
    paths = ('data/v8/audit_latest.json', 'data/v8/decision.json', 'data/quant_journal.json')
    raw = {}
    for path in paths:
        with (directory / path).open('rb') as stream:
            data = stream.read(MAX_SOURCE_BYTES + 1)
        require(len(data) <= MAX_SOURCE_BYTES, 'source exceeds capture limit')
        raw[path] = data
    return package_sources(raw)


def package_sources(raw):
    """Validate exact public source bytes and build immutable capture objects."""
    paths = ('data/v8/audit_latest.json', 'data/v8/decision.json', 'data/quant_journal.json')
    require(set(raw) == set(paths) and all(isinstance(b, bytes) and len(b) <= MAX_SOURCE_BYTES for b in raw.values()),
            'invalid source inventory or size')
    audit, decision, journal = [decode(raw[path]) for path in paths]
    require(all(isinstance(x, dict) for x in (audit, decision, journal)), 'invalid source document')
    manifest = audit.get('manifest')
    require(isinstance(manifest, dict), 'missing audit manifest')
    dref = manifest.get('decision')
    require(isinstance(dref, dict) and dref.get('status') == 'OK', 'decision audit unavailable')
    bound(raw[paths[1]], dref.get('file'), paths[1])
    refs = audit.get('legacy_output_refs')
    require(isinstance(refs, list), 'missing journal references')
    matches = [r for r in refs if isinstance(r, dict) and r.get('path') == paths[2]]
    require(len(matches) == 1, 'ambiguous journal reference')
    bound(raw[paths[2]], matches[0], paths[2])
    require(decision.get('schema') == 'v8.decision/1' and type(decision.get('as_of')) is int
            and decision['as_of'] > 0, 'invalid decision snapshot')
    require(type(manifest.get('ts')) is int and 0 < manifest['ts'] < 8640000000000, 'invalid audit time')
    require(isinstance(decision.get('strategy_tiers'), dict), 'missing observed authority')
    require(all(isinstance(journal.get(k), list) for k in ('open', 'closed')), 'invalid journal')
    require(sum(len(journal[k]) for k in ('open', 'closed')) <= 20000, 'capture row limit exceeded')
    files, records, identities = {}, [], set()
    for state in ('open', 'closed'):
        for record in journal[state]:
            require(isinstance(record, dict), 'invalid journal record')
            identity = record.get('id')
            require(type(identity) in (str, int) and identity != '', 'missing journal identity')
            key = canonical(identity)
            require(key not in identities, 'duplicate journal identity')
            identities.add(key)
            body = canonical(dict(schema='v9.paper-observation-record/1', journal_state=state, record=record))
            path = PREFIX + 'records/' + sha(body) + '.json.gz'
            files[path] = gzip.compress(body, mtime=0)
            records.append(dict(identity=identity, state=state, path=path, sha256=sha(body)))
    original_sources = {}
    for source_path, source_body in raw.items():
        retained_path = PREFIX + 'sources/' + sha(source_body) + '.json.gz'
        files[retained_path] = gzip.compress(source_body, mtime=0)
        original_sources[source_path] = retained_path
    snapshot = dict(schema='v9.paper-observation-snapshot/1', snapshot_time=manifest['ts'],
                    decision_time=decision['as_of'], decision_valid_until=decision.get('valid_until'),
                    observed_authority=decision['strategy_tiers'], policy_hash=decision.get('policy_hash'),
                    decision_implementation_hash=decision.get('implementation_hash'),
                    recorder_sha256=sha(Path(__file__).read_bytes()),
                    source_files={p: dict(bytes=len(b), sha256=sha(b)) for p, b in raw.items()},
                    source_bindings_verified=True, records=records, original_sources=original_sources,
                    historical_entry_authority='UNRECORDED_NOT_INFERRED', trade_authorization=False,
                    limitations=['This records authority at the snapshot, not at trade entry.',
                                 'Records pruned before capture and scans that never completed cannot be recovered.',
                                 'Original public source bytes are retained; content binding is not upstream authentication.'])
    body = canonical(snapshot)
    path = PREFIX + 'snapshots/' + sha(body) + '.json.gz'
    files[path] = gzip.compress(body, mtime=0)
    view = canonical(dict(schema='v9.paper-observation-view/1', snapshot_path=path,
                          snapshot=body.decode('utf-8'),
                          records={r['path']: unpack(files[r['path']]).decode('utf-8') for r in records}))
    require(len(view) <= MAX_SOURCE_BYTES, 'browse bundle exceeds capture limit')
    view_path = PREFIX + 'views/' + sha(view) + '.json.gz'
    files[view_path] = gzip.compress(view, mtime=0)
    index = canonical(dict(schema='v9.paper-observation-index/1', snapshot_time=manifest['ts'],
                           snapshot_path=path, view_path=view_path, records=len(records)))
    index_path = PREFIX + 'indexes/' + f"{manifest['ts']:020d}-" + sha(body) + '-' + sha(index) + '.json.gz'
    files[index_path] = gzip.compress(index, mtime=0)
    return files, path


def git(repo, args, *, data=None, env=None):
    result = subprocess.run(['git', '-c', 'safe.directory=*', *args], cwd=repo, input=data,
                            capture_output=True, env=env, timeout=120)
    if result.returncode:
        raise RuntimeError('Git ' + args[0] + ' failed (' + str(result.returncode) + ')')
    return result.stdout


def entries(repo, head, paths):
    result = {}
    for offset in range(0, len(paths), 100):
        raw = git(repo, ['ls-tree', '-z', head, '--', *paths[offset:offset+100]])
        for entry in raw.split(b'\0'):
            if not entry:
                continue
            info, path = entry.split(b'\t', 1)
            mode, kind, oid = info.decode().split()
            require(mode == '100644' and kind == 'blob', 'unexpected history object type')
            result[path.decode()] = oid
    return result


def unpack(data):
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(data), mode='rb') as stream:
            body = stream.read(MAX_SOURCE_BYTES + 1)
    except (OSError, EOFError, zlib.error) as error:
        raise ValueError('invalid compressed history object') from error
    require(len(body) <= MAX_SOURCE_BYTES, 'history object exceeds capture limit')
    return body


def verify_archive(read, snapshot_path):
    """Recover retained rows with content checks, not renewed source authority.

    `read` must read from one pinned archive revision. New captures retain original
    source bytes for replay; older captures remain content-only verification.
    """
    require(re.fullmatch(PREFIX + r'snapshots/[a-f0-9]{64}\.json\.gz', snapshot_path), 'invalid snapshot path')
    body = unpack(read(snapshot_path))
    require(sha(body) == snapshot_path.rsplit('/', 1)[1][:-8], 'snapshot hash mismatch')
    snapshot = decode(body)
    require(isinstance(snapshot, dict) and snapshot.get('schema') == 'v9.paper-observation-snapshot/1', 'invalid archive schema')
    refs = snapshot.get('records')
    require(isinstance(refs, list) and len(refs) <= 20000, 'invalid archive inventory')
    records, identities = [], set()
    for ref in refs:
        require(isinstance(ref, dict), 'invalid archive reference')
        path = ref.get('path')
        require(isinstance(path, str) and re.fullmatch(PREFIX + r'records/[a-f0-9]{64}\.json\.gz', path), 'invalid record path')
        raw = unpack(read(path))
        require(sha(raw) == ref.get('sha256') == path.rsplit('/', 1)[1][:-8], 'record hash mismatch')
        record = decode(raw)
        require(isinstance(record, dict) and record.get('schema') == 'v9.paper-observation-record/1'
                and record.get('journal_state') in ('open', 'closed') and record['journal_state'] == ref.get('state')
                and isinstance(record.get('record'), dict), 'invalid archived record')
        identity = record['record'].get('id')
        require(type(identity) in (str, int) and identity != '' and canonical(identity) == canonical(ref.get('identity')), 'archive identity mismatch')
        key = canonical(identity)
        require(key not in identities, 'duplicate archived identity')
        identities.add(key)
        records.append(record)
    require(snapshot.get('trade_authorization') is False and snapshot.get('historical_entry_authority') == 'UNRECORDED_NOT_INFERRED', 'unsupported archive authority')
    reverified = False
    if 'original_sources' in snapshot:
        original = snapshot['original_sources']
        expected = {'data/v8/audit_latest.json', 'data/v8/decision.json', 'data/quant_journal.json'}
        require(isinstance(original, dict) and set(original) == expected, 'invalid original source inventory')
        raw_sources = {}
        for source, path in original.items():
            require(isinstance(path, str) and re.fullmatch(PREFIX + r'sources/[a-f0-9]{64}\.json\.gz', path),
                    'invalid original source path')
            source_body = unpack(read(path))
            require(sha(source_body) == path.rsplit('/', 1)[1][:-8], 'original source hash mismatch')
            raw_sources[source] = source_body
        replay_files, replay_path = package_sources(raw_sources)
        replay = decode(unpack(replay_files[replay_path]))
        fields = ('snapshot_time', 'decision_time', 'decision_valid_until', 'observed_authority',
                  'policy_hash', 'decision_implementation_hash', 'source_files', 'records', 'original_sources')
        require(snapshot.get('source_bindings_verified') is True and
                all(k in snapshot and canonical(snapshot[k]) == canonical(replay[k]) for k in fields),
                'original source replay mismatch')
        reverified = True
    return dict(status='ARCHIVE_CONTENT_VERIFIED', snapshot=snapshot, records=records,
                original_source_documents_reverified=reverified, trade_authorization=False)


def publish(repo, files, snapshot_path, *, remote='origin', attempts=3):
    """Add only, to an existing history branch. Retry non-fast-forward races."""
    require(snapshot_path in files and snapshot_path.startswith(PREFIX + 'snapshots/'), 'missing snapshot')
    require(all(re.fullmatch(PREFIX + r'(?:(?:records|snapshots|views|sources)/[a-f0-9]{64}|indexes/[0-9]{20}-[a-f0-9]{64}-[a-f0-9]{64})\.json\.gz', p) for p in files), 'invalid capture path')
    paths = sorted(files)
    bodies = {p: unpack(files[p]) for p in paths}
    require(all(sha(bodies[p]) == p.rsplit('/', 1)[1][:-8].rsplit('-', 1)[-1] for p in paths), 'content-address mismatch')
    blobs = {p: git(repo, ['hash-object', '-w', '--stdin'], data=files[p]).decode().strip() for p in paths}
    ref = 'refs/v9-paper-observation/base'
    require(git(repo, ['ls-remote', '--heads', remote, 'refs/heads/' + BRANCH]).strip(), 'existing history branch required')
    for attempt in range(attempts):
        git(repo, ['fetch', '--no-tags', '--depth=1', '--filter=blob:none', remote, '+refs/heads/' + BRANCH + ':' + ref])
        head = git(repo, ['rev-parse', ref]).decode().strip()
        existing = entries(repo, head, paths)
        for path, oid in existing.items():
            if oid != blobs[path]:
                # Gzip encoders may differ across Python/zlib versions. Preserve
                # the old bytes if and only if the decompressed record is exact.
                require(unpack(git(repo, ['cat-file', 'blob', oid])) == bodies[path], 'immutable history conflict')
                blobs[path] = oid
        missing = [p for p in paths if p not in existing]
        if not missing:
            return dict(status='ALREADY_RETAINED', commit=head, snapshot=snapshot_path, added=0)
        with tempfile.TemporaryDirectory(prefix='paper-history-index-') as tmp:
            env = dict(os.environ, GIT_INDEX_FILE=str(Path(tmp)/'index'),
                       GIT_AUTHOR_NAME='perp-dex-radar', GIT_AUTHOR_EMAIL='actions@users.noreply.github.com',
                       GIT_COMMITTER_NAME='perp-dex-radar', GIT_COMMITTER_EMAIL='actions@users.noreply.github.com')
            git(repo, ['read-tree', head], env=env)
            for path in missing:
                git(repo, ['update-index', '--add', '--cacheinfo', '100644,' + blobs[path] + ',' + path], env=env)
            tree = git(repo, ['write-tree', '--missing-ok'], env=env).decode().strip()
            commit = git(repo, ['commit-tree', tree, '-p', head, '-m', 'Retain paper observations ' + snapshot_path], env=env).decode().strip()
        try:
            git(repo, ['push', '--no-verify', remote, commit + ':refs/heads/' + BRANCH])
        except RuntimeError:
            if attempt + 1 == attempts:
                raise
            continue
        git(repo, ['fetch', '--no-tags', '--depth=1', '--filter=blob:none', remote, '+refs/heads/' + BRANCH + ':' + ref])
        remote_head = git(repo, ['rev-parse', ref]).decode().strip()
        require(entries(repo, remote_head, paths) == blobs, 'remote retention verification failed')
        return dict(status='RETAINED_AND_VERIFIED', commit=commit, snapshot=snapshot_path, added=len(missing))
    raise RuntimeError('capture publication attempts exhausted')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--site', required=True)
    parser.add_argument('--repo', default='.')
    parser.add_argument('--report', required=True)
    args = parser.parse_args(argv)
    try:
        files, path = package(args.site)
        report = publish(args.repo, files, path)
        report.update(schema='v9.paper-retention-report/1', branch=BRANCH, trade_authorization=False)
        code = 0
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
        # Do not echo source payloads, credentials, or git remote errors.
        report = dict(schema='v9.paper-retention-report/1', status='FAILED', error_type=type(error).__name__,
                      branch=BRANCH, trade_authorization=False)
        print('::warning title=Paper history retention::Capture was not verified; inspect the retained diagnostic report.')
        code = 1
    Path(args.report).write_bytes(canonical(report) + b'\n')
    print('Paper history retention: ' + report['status'])
    return code


if __name__ == '__main__':
    raise SystemExit(main())
