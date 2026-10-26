"""Guarded hosted-runner entry point; no workflow is activated by this module."""
import argparse
from functools import partial
import json
import os
from pathlib import Path
import re
import sys
import time

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from tools.v9 import control_outcome_job as J,control_input_prepare as I,control_resource_gate as G
from tools.v9.control_reservation_api import GitHubReservationAPI

PROFILE='ubuntu-24.04-x64-github-hosted'


def validate(env,deadline,now):
    expected=dict(GITHUB_ACTIONS='true',GITHUB_REPOSITORY='blazebrt/perp-dex-radar',
        GITHUB_REF='refs/heads/v9/census-evidence',GITHUB_RUN_ATTEMPT='1',
        RUNNER_ENVIRONMENT='github-hosted',RUNNER_OS='Linux',RUNNER_ARCH='X64',ImageOS='ubuntu24')
    if not sys.platform.startswith('linux') or any(env.get(k)!=v for k,v in expected.items()):
        raise ValueError('expected hosted research runner environment required')
    if env.get('GITHUB_EVENT_NAME') not in ('workflow_dispatch','push'):
        raise ValueError('unsupported research trigger')
    if not re.fullmatch('[0-9a-f]{40}',env.get('GITHUB_SHA','')) or not re.fullmatch('[1-9][0-9]*',env.get('GITHUB_RUN_ID','')):
        raise ValueError('pinned source and run identity required')
    if type(deadline) is not int or not 0<deadline-now<=21600:
        raise ValueError('positive deadline within six hours required')
    if not env.get('GITHUB_TOKEN'):raise ValueError('runner token required')
    if not env.get('RUNNER_TEMP') or not Path(env['RUNNER_TEMP']).is_dir():raise ValueError('runner scratch directory required')


def run(env,qualification,qualification_hash,deadline):
    validate(env,deadline,time.time())
    if not re.fullmatch('[0-9a-f]{64}',qualification_hash):raise ValueError('reviewed qualification hash required')
    qualification=Path(qualification).resolve()
    if not qualification.is_file():raise ValueError('qualification report required')
    api=GitHubReservationAPI(env['GITHUB_TOKEN'])
    scratch=Path(env['RUNNER_TEMP']).resolve()/('a6-outcome-'+env['GITHUB_RUN_ID']+'-1')
    scratch.mkdir(exist_ok=False)
    def capacity():
        remaining=int(deadline-time.time())
        if remaining<=0:raise ValueError('job deadline exhausted')
        return G.live_capacity(scratch,PROFILE,remaining)
    return J.run(ROOT,scratch/'job',scratch/'archive',scratch/'phase-b.json',scratch/'signals',
        env['GITHUB_SHA'],env['GITHUB_RUN_ID'],'1',qualification,qualification_hash,api,capacity,
        ('perp-dex-radar','actions@users.noreply.github.com'),partial(I.prepare,ROOT))


def exit_code(report):
    return 0 if report.get('status')=='RETAINED_DIAGNOSTICS' and report.get('reservation_verified') is True and report.get('publication_verified') is True and report.get('promotion_authority') is False else 1


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--qualification',required=True)
    parser.add_argument('--qualification-sha256',required=True)
    parser.add_argument('--deadline-epoch',type=int,required=True)
    args=parser.parse_args(argv)
    try:report=run(os.environ,args.qualification,args.qualification_sha256,args.deadline_epoch)
    except Exception as error:
        # Avoid printing exception bodies that may contain request or credential data.
        print(json.dumps(dict(status='RUNNER_FAILED_INSPECT_RETAINED_STATE',error_type=type(error).__name__)))
        return 1
    print(json.dumps(report,sort_keys=True));return exit_code(report)


if __name__=='__main__':raise SystemExit(main())
