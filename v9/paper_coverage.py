"""Read-only coverage inventory of pinned paper captures; never infer entry tiers."""
import argparse
from pathlib import Path
import re

from v9 import paper_history as H

MAX_SNAPSHOTS = 10000
MAX_IDENTITIES = 200000
MAX_OBSERVATIONS = 1000000
ENTRY_FIELDS = ('s', 'c', 'd', 't_sig', 't_in')


def assess(read, paths, *, revision):
    """Verify every supplied capture. The caller must supply one complete pinned inventory.

    Missing/corrupt objects fail the entire assessment. Capture spacing is descriptive,
    not proof that a scan was missed. Returns no returns, tier estimates or authority.
    """
    H.require(isinstance(revision, str) and re.fullmatch('[a-f0-9]{40}', revision), 'pin a commit SHA')
    H.require(isinstance(paths, list) and len(paths) <= MAX_SNAPSHOTS
              and all(isinstance(p, str) for p in paths), 'invalid capture inventory')
    H.require(len(paths) == len(set(paths)), 'duplicate capture path')
    identities, captures, versions = {}, [], set()
    strong = observations = 0
    for path in sorted(paths):
        result = H.verify_archive(read, path)
        snapshot = result['snapshot']
        stamp = snapshot.get('snapshot_time')
        H.require(type(stamp) is int and 0 < stamp < 8640000000000, 'invalid capture time')
        strong += result['original_source_documents_reverified']
        captures.append(stamp)
        observations += len(result['records'])
        H.require(observations <= MAX_OBSERVATIONS, 'observation limit exceeded')
        for row in result['records']:
            record = row['record']
            key = H.canonical(record['id'])
            versions.add(H.sha(H.canonical(row)))
            if key not in identities:
                H.require(len(identities) < MAX_IDENTITIES, 'identity limit exceeded')
                identities[key] = dict(identity=record['id'], first=stamp, last=stamp,
                                       entries=set(), states=set(), missing=False, future=False)
            item = identities[key]
            item['first'], item['last'] = min(item['first'], stamp), max(item['last'], stamp)
            # Presence is part of the comparison: a newly filled field is a change,
            # not silent evidence that it was already known at the first capture.
            item['entries'].add(H.canonical({k: [k in record, record.get(k)] for k in ENTRY_FIELDS}))
            item['states'].add(row['journal_state'])
            entry = record.get('t_in')
            valid = type(entry) is int and 0 < entry < 8640000000000
            item['missing'] |= not valid
            item['future'] |= valid and entry > stamp
    times = sorted(set(captures))
    conflicts = [x['identity'] for _, x in sorted(identities.items()) if len(x['entries']) > 1]
    return dict(schema='v9.paper-coverage/1', revision=revision,
                status='VERIFIED_RETAINED_CAPTURE_INVENTORY' if paths else 'NO_RETAINED_CAPTURES',
                captures=len(paths), original_sources_reverified=strong,
                content_only_captures=len(paths)-strong,
                first_capture=min(times) if times else None, last_capture=max(times) if times else None,
                largest_observed_capture_spacing=max((b-a for a, b in zip(times, times[1:])), default=None),
                repeated_capture_timestamps=len(captures)-len(times),
                unique_identities=len(identities), unique_record_versions=len(versions),
                identities_seen_open=sum('open' in x['states'] for x in identities.values()),
                identities_seen_closed=sum('closed' in x['states'] for x in identities.values()),
                identities_with_missing_or_invalid_entry_time=sum(x['missing'] for x in identities.values()),
                identities_with_entry_after_capture=sum(x['future'] for x in identities.values()),
                conflicting_entry_identities=conflicts, entry_authority_verified=0,
                entry_authority_unavailable=len(identities), historical_completeness_verified=False,
                trade_authorization=False,
                limitations=['Counts describe only the supplied pinned archive inventory.',
                             'Capture spacing cannot prove missed scans or continuous coverage.',
                             'Capture-time authority is not entry-time authority.',
                             'Pre-capture pruning and unrecorded trades remain unknown.',
                             'Conflicts are reported without choosing or rewriting a record.'])


def assess_git(repo, revision):
    """Read a complete snapshots subtree from an existing local commit, without fetches."""
    H.require(isinstance(revision, str) and re.fullmatch('[a-f0-9]{40}', revision), 'pin a commit SHA')
    H.require(H.git(repo, ['rev-parse', '--verify', revision+'^{commit}']).decode().strip() == revision,
              'revision is not a commit')
    raw = H.git(repo, ['ls-tree', '-rz', '--name-only', revision, '--', H.PREFIX+'snapshots/'])
    paths = [p.decode('utf-8') for p in raw.split(b'\0') if p]

    def read(path):
        refs = H.entries(repo, revision, [path])
        H.require(path in refs, 'missing history object')
        oid = refs[path]
        size = int(H.git(repo, ['cat-file', '-s', oid]))
        H.require(size <= H.MAX_SOURCE_BYTES + 1024 * 1024, 'compressed object exceeds limit')
        return H.git(repo, ['cat-file', 'blob', oid])

    return assess(read, paths, revision=revision)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', required=True)
    parser.add_argument('--revision', required=True)
    parser.add_argument('--out', required=True)
    args = parser.parse_args(argv)
    report = assess_git(args.repo, args.revision)
    # Exclusive creation: never replace a previously retained assessment.
    with Path(args.out).open('xb') as stream:
        stream.write(H.canonical(report)+b'\n')


if __name__ == '__main__':
    main()
