"""Bound A6 signal extraction, without execution, matching or outcomes."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.v9 import control_signals as signals, control_sources as sources

SOURCE = 'ad2374fa4d25f03c204ce7c0cdbecac95cba6246'
PLAN_SHA = '7910cb5678771db32e2ebfe162a916c5cd7ff209987a598f6be6c4f470551af1'
INVENTORY_SHA = 'bcab567507ccee4e26112f39835bdfe5df6c1248f7e40fd049d5cdbfa04d3ea1'
BOUND_CODE = ('tools/v9/evidence.py', 'tools/v9/archive_fetch.py',
              'tools/research/qstrat.py', 'tools/research/qdata.py',
              'tools/research/qind.py', 'tools/research/qsim.py')


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''):
            digest.update(block)
    return digest.hexdigest()


def write_json(path, value):
    raw = (json.dumps(value, sort_keys=True, indent=2, allow_nan=False)+'\n').encode()
    temporary = path.with_suffix('.tmp')
    with temporary.open('xb') as stream:
        stream.write(raw)
    temporary.replace(path)


class Shards:
    """Bound both records and uncompressed bytes; gzip headers are deterministic."""
    def __init__(self, root, trial_id, max_rows=25000, max_bytes=16*1024*1024):
        sources.require(type(max_rows) is int and max_rows > 0 and
                        type(max_bytes) is int and max_bytes > 0, 'invalid shard limits')
        sources.require(re.fullmatch('[0-9a-f]{64}', trial_id), 'unsafe trial identity')
        self.root, self.tid = Path(root), trial_id
        self.max_rows, self.max_bytes = max_rows, max_bytes
        self.files, self.count, self.size = [], 0, 0
        self.stream = self.raw = None

    def emit(self, row):
        raw = (json.dumps(row, sort_keys=True, separators=(',', ':'), allow_nan=False)+'\n').encode()
        sources.require(len(raw) <= self.max_bytes, 'single record exceeds shard limit')
        if self.stream and (self.count == self.max_rows or self.size+len(raw) > self.max_bytes):
            self.close()
        if self.stream is None:
            self.path = self.root / (self.tid+'-%05d.jsonl.gz' % len(self.files))
            self.raw = self.path.open('xb')
            self.stream = gzip.GzipFile(filename='', mode='wb', fileobj=self.raw, mtime=0)
            self.count = self.size = 0
        self.stream.write(raw)
        self.count += 1
        self.size += len(raw)

    def close(self):
        if self.stream is None:
            return
        try:
            self.stream.close()
        finally:
            self.raw.close()
            self.stream = self.raw = None
        self.files.append(dict(path=self.path.name, sha256=sha(self.path), records=self.count,
                               uncompressed_bytes=self.size, bytes=self.path.stat().st_size))


def extract(out, prepare, max_rows=25000, max_bytes=16*1024*1024):
    """Preparation returns bound inputs; injected only for synthetic tests."""
    out = Path(out)
    sources.require(not out.exists() or not any(out.iterdir()), 'preserve existing output')
    out.mkdir(parents=True, exist_ok=True)
    try:
        context = prepare()
        trials = context['trials']
        ids = [t['trial_id'] for t in trials]
        sources.require(len(ids) == len(set(ids)) and all(re.fullmatch('[0-9a-f]{64}', t) for t in ids),
                        'invalid trial roster')
        sources.require(all(t['archive_requirement'] in ('4h', 'hourly') for t in trials), 'unknown resolution')
        results = []
        for trial in trials:
            row = dict(trial_id=trial['trial_id'], definition=trial, promotion_authority=False)
            if trial['archive_requirement'] == 'hourly':
                row.update(status='UNAVAILABLE_HOURLY_POPULATION', population=None, shards=[])
            else:
                sink = Shards(out, trial['trial_id'], max_rows, max_bytes)
                try:
                    raw = context['generate'](trial)
                    row['population'] = signals.project(trial['trial_id'], raw, context['times'],
                        context['assets'], context['eligibility'], context['segments'],
                        context['start'], context['end'], sink.emit)
                    row['status'] = 'EXTRACTED'
                except (ValueError, TypeError, KeyError, IndexError, RuntimeError) as error:
                    row.update(status='FAILED', population=None,
                               error=dict(type=type(error).__name__, message=str(error)))
                finally:
                    sink.close()
                row['shards'] = sink.files
                row['retained_records'] = sum(f['records'] for f in sink.files)
                if row['status'] == 'EXTRACTED':
                    sources.require(row['retained_records'] == row['population']['retained'], 'sink count mismatch')
            results.append(row)
            write_json(out/(trial['trial_id']+'.json'), row)
        result = dict(schema='v9.a6-extraction/1', status='PARTIAL' if any(r['status']=='FAILED' for r in results)
                      else 'COMPLETED_WITH_UNAVAILABLE_HOURLY_POPULATIONS', trials=results,
                      provenance=context['provenance'], window=[context['start'], context['end']],
                      full_matched_authority=False, promotion_authority=False, outcomes_computed=False)
        write_json(out/'manifest.json', result)
        return result
    except Exception as error:
        write_json(out/'failure.json', dict(status='FAILED', type=type(error).__name__, message=str(error),
                   promotion_authority=False, completion_manifest_written=False))
        raise


def prepare(md, phase_b_evidence):
    # All byte bindings precede scientific imports and generator calls.
    code_hashes = {}
    for name in BOUND_CODE:
        original = subprocess.check_output(['git', '-c', 'safe.directory=*', '-C', str(ROOT), 'show', SOURCE+':'+name])
        sources.bound((ROOT/name).read_bytes(), sources.sha(original))
        code_hashes[name] = sources.sha(original)
    plan = json.loads(sources.bound((ROOT/'research/v9/census_replay_plan.json').read_bytes(), PLAN_SHA))
    inventory = json.loads(sources.bound((ROOT/'research/v9/a6_source_inventory.json').read_bytes(), INVENTORY_SHA))
    from tools.v9 import census_plan
    sources.require(plan == census_plan.build(), 'census/code changed')
    sources.require(len(plan['trials']) == 199 and plan['ready_4h_trials'] == 192, 'census count changed')
    reference_bytes = Path(phase_b_evidence).read_bytes()
    binding = json.loads((ROOT/'research/v9/probation_evidence.json').read_bytes())['inputs']['evidence_sha256']
    reference = json.loads(sources.bound(reference_bytes, binding))
    coins = sources.load_universe(md, inventory)
    segments = {asset: signals.SegmentView(sources.load_segment(md, inventory, row)) for asset,row in coins.items()}
    from tools.v9 import evidence as EV
    from tools.v9.census_replay import digest_panel
    import qstrat
    panel = EV.ArchivePanel(str(md))
    features = qstrat.Feat(panel)
    digest = digest_panel(panel)
    sources.require(digest == reference['provenance']['dataset_sha256'], 'phase B panel digest mismatch')
    start, end = int(panel.t[0])+120*86400, int(panel.t[-1])+14400
    sources.require([start,end] == [1588204800,1790812800], 'study window changed')
    sources.require(set(panel.coins) <= set(segments), 'unknown panel assets')
    provenance = dict(archive_commit=sources.ARCHIVE, source_commit=SOURCE, code_sha256=code_hashes,
                      inventory_sha256=INVENTORY_SHA, plan_sha256=PLAN_SHA, phase_b_evidence_sha256=binding,
                      panel_sha256=digest, verified_candle_files=len(segments),
                      adapter_sha256={p.name:sha(p) for p in (Path(__file__), Path(signals.__file__),
                                      Path(sources.__file__), Path(signals.F.__file__))},
                      protocol_sha256=sha(ROOT/'docs/v9/phase-a6-extraction-driver.md'))
    return dict(trials=plan['trials'], times=panel.t, assets=panel.coins, eligibility=features.elig,
                segments=segments, start=start, end=end, provenance=provenance,
                generate=lambda trial:getattr(qstrat,trial['implementation'])(features, **trial['params']))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--md', required=True)
    parser.add_argument('--phase-b-evidence', required=True)
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    result = extract(args.out, lambda:prepare(args.md, args.phase_b_evidence))
    if result['status'] == 'PARTIAL':
        raise SystemExit(1)
