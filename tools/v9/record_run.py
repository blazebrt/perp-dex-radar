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
HISTORY = os.path.join("research", "v9", "evidence_runs.jsonl")
SCHEMA = "v9.evidence-runs/1"
ZERO = "0" * 64
STUDIES = {
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
