"""Reproduce an independently verified candidate for durable publication.

This is byte-for-byte replication, not a fresh evidence audit or acceptance.
Every output must match the committed independently verified inventory.
"""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.v9 import hourly_quality as Q
from tools.v9 import hourly_quality_build as B

RECORD_SHA256 = '57ef72c68b91ff81f9704a9b7e21fa7a676f292a65f8761739ca4468eaea5b7a'


def reproduce(source, out, record):
    source, out = Path(source), Path(out)
    if B.sha(record) != RECORD_SHA256:
        raise ValueError('verified candidate record changed')
    record = json.loads(Path(record).read_bytes())
    expected = record['candidate_manifest']
    verification = record['independent_verification']
    if (record['status'] != 'LOCAL_CANDIDATE_INDEPENDENTLY_VERIFIED' or
            expected['accepted_dataset'] is not False or
            verification['candidate_manifest_sha256'] != record['candidate_manifest_sha256'] or
            not all(verification[k] is True for k in ('all_artifacts_verified',
                'all_modified_rows_and_masks_verified', 'all_embargo_days_verified',
                'original_schedule_and_funding_preserved'))):
        raise ValueError('candidate lacks independent verification')
    if B.sha(source / 'rejected_manifest.json') != B.MANIFEST:
        raise ValueError('wrong original archive')
    evidence = [Q.bound_json(ROOT / 'research/v9' / name, digest, schema) for name, digest, schema in Q.RECORDS]
    manifest = json.loads((source / 'rejected_manifest.json').read_bytes())
    plan = json.loads((source / 'hourly_plan.json').read_bytes())
    decisions = B.join_evidence(*evidence, plan, manifest)
    result = B.build_archive(source, out, plan, manifest, decisions)
    try:
        if result != expected:
            raise ValueError('replica differs from independently verified candidate')
        B.write_json(out / 'quality_candidate_manifest.json', result)
        if B.sha(out / 'quality_candidate_manifest.json') != record['candidate_manifest_sha256']:
            (out / 'quality_candidate_manifest.json').unlink()
            raise ValueError('candidate manifest bytes differ')
    except Exception as exc:
        B.write_json(out / 'failure.json', dict(error=str(exc), accepted_dataset=False))
        raise
    return result


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('source', 'out', 'record'):
        p.add_argument('--' + name, required=True)
    reproduce(**vars(p.parse_args()))
