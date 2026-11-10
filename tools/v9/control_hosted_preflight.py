"""Hosted qualification prerequisites only; never authorizes a market study."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from tools.v9 import control_runner_identity as Identity,control_resource_gate as Gate


def inspect(env):
    expected={'GITHUB_ACTIONS':'true','GITHUB_REPOSITORY':'blazebrt/perp-dex-radar',
              'GITHUB_REF':'refs/heads/v9/census-evidence','RUNNER_ENVIRONMENT':'github-hosted',
              'RUNNER_OS':'Linux','RUNNER_ARCH':'X64','ImageOS':'ubuntu24'}
    if any(env.get(k)!=v for k,v in expected.items()):raise ValueError('unexpected hosted environment')
    if not re.fullmatch('[0-9a-f]{40}',env.get('GITHUB_SHA','')):raise ValueError('source commit required')
    report=dict(schema='v9.a6-hosted-preflight/1',source_commit=env['GITHUB_SHA'],
                run_id=env.get('GITHUB_RUN_ID'),run_attempt=env.get('GITHUB_RUN_ATTEMPT'),
                identity=Identity.collect(env),capacity=None,blockers=[],
                required_workload=dict(signals=4263580,definitions=199,assets=781),
                resource_qualified=False,market_data_loaded=False,promotion_authority=False)
    if report['identity'].get('status')!='CONSISTENT_CLAIMS_NOT_ATTESTED':
        report['blockers'].append('RUNNER_IDENTITY_UNAVAILABLE_OR_CONFLICTING')
    try:
        scratch=env.get('RUNNER_TEMP')
        if not scratch or not Path(scratch).is_dir():raise ValueError('runner scratch unavailable')
        report['capacity']=dict(**Gate.memory_capacity(),free_disk_bytes=shutil.disk_usage(scratch).free)
        if any(type(report['capacity'].get(k)) is not int or report['capacity'][k]<=0
               for k in ('available_memory_bytes','free_disk_bytes')):raise ValueError('capacity unavailable')
    except (OSError,ValueError) as error:
        report['capacity_error_type']=type(error).__name__
        report['blockers'].append('LIVE_CAPACITY_UNAVAILABLE')
    report['status']='BLOCKED_PREREQUISITES' if report['blockers'] else 'PREREQUISITES_OBSERVED_NOT_QUALIFIED'
    report['remaining_requirements']=['REPRESENTATIVE_FULL_VOLUME_AND_HISTORY',
        'COMBINED_MEMORY_ALLOCATED_DISK_AND_RUNTIME_BOUNDS','REMOTE_PUBLICATION_AND_FAILURE_RETENTION',
        'REVIEWED_LOCK_AND_ENVIRONMENT','INDEPENDENT_QUALIFICATION_REVIEW']
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--out',required=True)
    args=parser.parse_args();out=Path(args.out)
    if out.exists():raise FileExistsError('preserve prior preflight')
    report=inspect(os.environ)
    raw=json.dumps(report,sort_keys=True,indent=2,allow_nan=False)+'\n'
    with out.open('x',encoding='utf8',newline='\n') as stream:stream.write(raw)
    print(raw)
    return 1 if report['blockers'] else 0


if __name__=='__main__':raise SystemExit(main())
