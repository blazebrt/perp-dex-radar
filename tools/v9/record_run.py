"""The history of evidence runs (HANDOVER A8): research/v9/evidence_runs.jsonl, one hash-chained record per run.

    git fetch origin +refs/heads/evidence-d2-results:refs/remotes/origin/evidence-d2-results
    python tools/v9/record_run.py --study D2            # append the run now on that results branch
    python tools/v9/record_run.py --verify              # check the whole history

The results branches are force-pushed single commits, so a re-run replaces the previous run. This file keeps every run
instead. A record pins:
- the run to the code commit that produced it and to its dataset (the phase B digest of candles and funding, the
  data branches it read, and the extra inputs of a study);
- the sha256 of its evidence, report and trades files;
- what it confirmed.

Each record carries the sha256 of the previous line, so an edited or removed record breaks the chain. Records are
appended and never changed. A study's pre-registration hash is in its record: tests/test_v9_evidence_runs.py fails if
the committed document no longer matches it."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import subprocess
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, ROOT)
HISTORY = os.path.join("research", "v9", "evidence_runs.jsonl")
SCHEMA = "v9.evidence-runs/1"
ZERO = "0" * 64
STUDIES = {
    "A6": {"branch": "evidence-a6-outcome-results"},
    "A5": {"branch": "evidence-a5-results", "evidence": "replay_run.json", "report": "REPORT_A5.md",
           "trades": "attempts_a5.json"},
    "A4": {"branch": "evidence-a4-results", "evidence": "evidence_a4.json", "report": "REPORT_A4.md",
           "trades": "trades_a4.json"},
    "A/B": {"branch": "evidence-results", "evidence": "evidence.json", "report": "REPORT.md", "trades": "trades.json.gz"},
    "D1": {"branch": "evidence-d1-results", "evidence": "evidence_d1.json", "report": "REPORT_D1.md",
           "trades": "trades_d1.json.gz"},
    "D2": {"branch": "evidence-d2-results", "evidence": "evidence_d2.json", "report": "REPORT_D2.md",
           "trades": "trades_d2.json.gz"},
}
REQUIRED = ("schema", "seq", "prev_sha256", "study", "results_branch", "results_commit", "source_commit", "ran_at",
            "evidence_schema", "dataset_sha256", "files", "confirmed")


def _git(repo, *args):
    return subprocess.run(["git", "-C", repo, *args], check=True, capture_output=True).stdout


def canonical(rec):
    return json.dumps(rec, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def read(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf8") as fh:
        return [line.rstrip("\n") for line in fh if line.strip()]


def verify(lines):
    """Problems with the history (empty when it is intact): sequence, chain, fields, duplicate runs."""
    problems, prev, seen = [], ZERO, set()
    for k, line in enumerate(lines, 1):
        try:
            rec = json.loads(line)
        except ValueError:
            problems.append(f"line {k}: not JSON")
            break
        missing = [f for f in REQUIRED if f not in rec]
        if missing:
            problems.append(f"line {k}: missing {missing}")
        if rec.get("schema") != SCHEMA:
            problems.append(f"line {k}: schema {rec.get('schema')!r}")
        if rec.get("seq") != k:
            problems.append(f"line {k}: seq {rec.get('seq')}")
        if rec.get("prev_sha256") != prev:
            problems.append(f"line {k}: the chain is broken (an earlier record changed or was removed)")
        if canonical(rec) != line:
            problems.append(f"line {k}: not in canonical form")
        if rec.get("results_commit") in seen:
            problems.append(f"line {k}: run {rec.get('results_commit')} recorded twice")
        seen.add(rec.get("results_commit"))
        prev = hashlib.sha256(line.encode("utf8")).hexdigest()
    return problems


def build(study, repo=ROOT, ref=None):
    """The record of the run now on the study's results branch (ref defaults to origin/<branch>)."""
    if study == 'A6':
        from tools.v9.record_control_outcome import build as build_a6
        return build_a6(repo, ref or 'origin/evidence-a6-outcome-results')
    spec = STUDIES[study]
    ref = ref or f"origin/{spec['branch']}"
    show = lambda f: _git(repo, "show", f"{ref}:{f}")  # noqa: E731
    # A gzip file is hashed decompressed, as tools/v9/confirm.py binds the trades (load_trades), so both pins agree.
    body = lambda f: gzip.decompress(show(f)) if f.endswith(".gz") else show(f)  # noqa: E731
    files = {k: hashlib.sha256(body(spec[k])).hexdigest() for k in ("evidence", "report", "trades")}
    ev = json.loads(show(spec["evidence"]))
    meta = show("run_meta.txt").decode().split()
    datasets = {}
    try:
        for line in show("dataset_ref.txt").decode().splitlines():
            if line.strip():
                name, sha = line.split()[:2]
                datasets[name] = sha
    except subprocess.CalledProcessError:
        pass
    data = ev.get("data") or {}
    rec = {"schema": SCHEMA, "study": study, "results_branch": spec["branch"],
           "results_commit": _git(repo, "rev-parse", ref).decode().strip(),
           "source_branch": meta[0] if meta else None, "source_commit": meta[1] if len(meta) > 1 else None,
           "ran_at": meta[2] if len(meta) > 2 else None, "evidence_schema": ev.get("schema"),
           "dataset_sha256": data.get("dataset_sha256") or (ev.get("provenance") or {}).get("dataset_sha256"),
           "datasets": datasets, "files": files}
    if study == "A/B":
        bound = json.load(open(os.path.join(repo, "research", "v9", "probation_evidence.json")))
        same = (bound.get("inputs") or {}).get("evidence_sha256") == files["evidence"]
        rec["confirmed"] = bound.get("confirmed") if same else None
        rec["bound_by"] = "research/v9/probation_evidence.json" if same else None
    elif study == 'A5':
        from tools.v9.hourly_replay import MANIFEST_SHA, DATA_COMMIT
        if (ev['schema'] != 'v9.a5-replay-run/1' or ev['dataset_sha256'] != MANIFEST_SHA or
                ev['data_commit'] != DATA_COMMIT or ev['confirmed'] != [] or
                ev['promotion_authority'] is not False or
                ev['known_trial_return_matrix_complete'] is not False or
                ev['historical_trial_census_complete'] is not False or
                ev['status'] not in ('FAILED', 'PARTIAL_FAILURE', 'COMPLETED_WITH_UNAVAILABLE_RESULTS') or
                ev['preregistration'] != 'docs/v9/phase-a5-replay-publication.md'):
            raise ValueError('invalid A5 evidence binding or authority')
        if ev['status'] != 'FAILED' and (ev['actual_manifest_sha256'] != MANIFEST_SHA or
                ev['driver_manifest_retained'] is not True or 'evidence_a5.json' not in ev['artifacts_sha256']):
            raise ValueError('A5 completed attempt lacks verified driver evidence')
        artifacts = ev['artifacts_sha256']
        for path, digest in artifacts.items():
            if '/' in path or '\\' in path or ':' in path or path in ('.', '..'):
                raise ValueError('invalid A5 artifact path')
            if hashlib.sha256(show(path)).hexdigest() != digest:
                raise ValueError('A5 artifact hash mismatch: ' + path)
        attempts = json.loads(show(spec['trades']))
        if attempts != {p:d for p,d in artifacts.items() if p.endswith('.jsonl.gz')}:
            raise ValueError('A5 attempt inventory mismatch')
        if artifacts.get(spec['trades']) != files['trades']:
            raise ValueError('A5 attempt manifest binding missing')
        rec.update(dataset_sha256=MANIFEST_SHA, confirmed=[],
                   preregistration=ev['preregistration'],
                   preregistration_sha256=ev['preregistration_sha256'],
                   preregistrations_sha256=ev['preregistrations_sha256'],
                   status=ev['status'], known_trial_return_matrix_complete=False,
                   historical_trial_census_complete=False,
                   extra_inputs={'data_commit':DATA_COMMIT, 'publisher_sha256':ev['publisher_sha256']})
    elif study == 'A4':
        rec['confirmed'] = []
        rec['preregistration'] = 'docs/v9/phase-a4-replay-protocol.md'
        rec['preregistration_sha256'] = ev['provenance']['protocol_sha256']
        rec['extra_inputs'] = {k: ev['provenance'][k] for k in
                              ('plan_sha256', 'replay_code_hash', 'runner_sha256', 'universe_sha256')}
        rec['known_trial_return_matrix_complete'] = ev['known_trial_return_matrix_complete']
        rec['historical_trial_census_complete'] = ev['historical_trial_census_complete']
        # Verify every shard before recording the manifest as evidence.
        manifest = json.loads(show(spec['trades']))
        for path, sha in ev['artifacts'].items():
            if '/' in path or hashlib.sha256(show(path)).hexdigest() != sha:
                raise ValueError('A4 artifact hash mismatch: ' + path)
        for path, item in manifest.items():
            if not path.startswith('trades/') or '..' in path.split('/'):
                raise ValueError('invalid A4 trade shard path')
            if hashlib.sha256(show(path)).hexdigest() != item['sha256']:
                raise ValueError('A4 trade shard hash mismatch: ' + path)
    else:
        rec["confirmed"] = ev.get("confirmed") or []
        rec["preregistration"] = (ev.get("preregistration") or {}).get("preregistration")
        rec["preregistration_sha256"] = (ev.get("preregistration") or {}).get("preregistration_sha256")
        rec["extra_inputs"] = {k: data[k] for k in ("d1_inputs_sha256", "metrics_sha256", "metrics_provenance_sha256")
                               if data.get(k)}
    return rec


def append(rec, path):
    lines = read(path)
    problems = verify(lines)
    if problems:
        raise SystemExit("the history is not intact: " + "; ".join(problems))
    if any(json.loads(x)["results_commit"] == rec["results_commit"] for x in lines):
        raise SystemExit(f"run {rec['results_commit']} is already recorded")
    rec = dict(rec, seq=len(lines) + 1,
               prev_sha256=hashlib.sha256(lines[-1].encode("utf8")).hexdigest() if lines else ZERO)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf8") as fh:
        fh.write(canonical(rec) + "\n")
    return rec


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--study", choices=sorted(STUDIES))
    ap.add_argument("--ref", default=None, help="results ref (default origin/<branch>)")
    ap.add_argument("--repo", default=ROOT)
    ap.add_argument("--verify", action="store_true")
    a = ap.parse_args(argv)
    path = os.path.join(a.repo, HISTORY)
    if a.verify or not a.study:
        problems = verify(read(path))
        print("evidence runs: " + ("intact, " + str(len(read(path))) + " records" if not problems else "; ".join(problems)))
        return 1 if problems else 0
    rec = append(build(a.study, a.repo, a.ref), path)
    print(f"recorded run {rec['seq']}: {rec['study']} {rec['results_commit'][:7]} (source {str(rec['source_commit'])[:7]})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
