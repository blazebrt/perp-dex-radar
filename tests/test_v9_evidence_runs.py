"""HANDOVER A8: research/v9/evidence_runs.jsonl keeps every evidence run, hash-chained and pinned to its dataset
(tools/v9/record_run.py).
- The committed history is intact.
- The phase A/B run is the one the probation tier is bound to.
- Every study ran on phase B's candles and funding.
- No pre-registration document changed after its run.
- Tampering is detected.

Run from the repository root:  python -m unittest tests.test_v9_evidence_runs -v"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "v9"))
import record_run as RR  # noqa: E402

HISTORY = ROOT / RR.HISTORY


def records():
    return [json.loads(x) for x in RR.read(str(HISTORY))]


class CommittedHistory(unittest.TestCase):
    def test_the_history_is_intact(self):
        lines = RR.read(str(HISTORY))
        self.assertGreaterEqual(len(lines), 3)
        self.assertEqual(RR.verify(lines), [])

    def test_the_phase_b_run_is_the_one_the_probation_tier_is_bound_to(self):
        ab = [r for r in records() if r["study"] == "A/B"]
        bound = json.loads((ROOT / "research" / "v9" / "probation_evidence.json").read_text())["inputs"]
        self.assertTrue(ab)
        cur = ab[-1]
        self.assertEqual(cur["files"]["evidence"], bound["evidence_sha256"])
        self.assertEqual(cur["files"]["trades"], bound["trades_sha256"])
        self.assertEqual(cur["dataset_sha256"], bound["dataset_sha256"])
        self.assertEqual(cur["source_commit"], bound["evidence_commit"])
        self.assertEqual(cur["bound_by"], "research/v9/probation_evidence.json")
        self.assertIn("XSMOM:long", cur["confirmed"])

    def test_every_study_ran_on_phase_b_candles_and_funding(self):
        rs = records()
        ab = [r for r in rs if r["study"] == "A/B"][-1]
        for r in rs:
            self.assertEqual(r["dataset_sha256"], ab["dataset_sha256"], r["study"])
            self.assertEqual(len(r["files"]["report"]), 64)

    def test_no_preregistration_changed_after_its_run(self):
        for r in records():
            if r["study"] == "A/B":
                continue
            doc = ROOT / r["preregistration"]
            self.assertEqual(hashlib.sha256(doc.read_bytes()).hexdigest(), r["preregistration_sha256"],
                             f"{r['preregistration']} changed after run {r['seq']}: a changed definition is a new study")


class Chain(unittest.TestCase):
    def setUp(self):
        self.lines = RR.read(str(HISTORY))

    def test_an_edited_record_breaks_the_chain(self):
        first = json.loads(self.lines[0])
        first["confirmed"] = ["SOMETHING:long"]
        edited = [RR.canonical(first)] + self.lines[1:]
        self.assertTrue(any("chain is broken" in p for p in RR.verify(edited)))

    def test_a_removed_record_breaks_the_chain(self):
        problems = RR.verify(self.lines[1:])
        self.assertTrue(any("seq" in p for p in problems) and any("chain" in p for p in problems))

    def test_duplicates_and_non_canonical_lines_are_refused(self):
        dup = json.loads(self.lines[-1])
        dup.update(seq=len(self.lines) + 1, prev_sha256=hashlib.sha256(self.lines[-1].encode()).hexdigest())
        self.assertTrue(any("twice" in p for p in RR.verify(self.lines + [RR.canonical(dup)])))
        loose = json.dumps(json.loads(self.lines[0]), indent=1).replace("\n", " ")
        self.assertTrue(any("canonical" in p for p in RR.verify([loose] + self.lines[1:])))


class BuildAndAppend(unittest.TestCase):
    """build() against a throwaway repository holding a fake D1 results branch, then append() to a fresh history."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.repo = os.path.join(self.tmp, "repo")
        os.makedirs(os.path.join(self.repo, "docs"))
        git = lambda *a: subprocess.run(["git", "-C", self.repo, *a], check=True, capture_output=True)  # noqa: E731
        git("init", "-q")
        git("config", "user.email", "t@example.com")
        git("config", "user.name", "t")
        files = {"evidence_d1.json": json.dumps({"schema": "v9.d1-evidence/1", "confirmed": [],
                                                  "preregistration": {"preregistration": "docs/p.md",
                                                                      "preregistration_sha256": "ab" * 32},
                                                  "data": {"dataset_sha256": "cd" * 32, "d1_inputs_sha256": "ef" * 32}}),
                 "REPORT_D1.md": "# report\n",
                 "run_meta.txt": "v9/research-d1 " + "1" * 40 + " 2026-10-14T15:27Z\n",
                 "dataset_ref.txt": "archive-data " + "2" * 40 + "\nevidence-results " + "3" * 40 + "\n"}
        for name, body in files.items():
            Path(self.repo, name).write_text(body)
        import gzip
        Path(self.repo, "trades_d1.json.gz").write_bytes(gzip.compress(b'{"XS_FUND_FADE":[]}'))
        git("add", ".")
        git("commit", "-q", "-m", "results")
        git("branch", "results")
        self.files = files

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_a_record_pins_files_dataset_inputs_and_source(self):
        rec = RR.build("D1", repo=self.repo, ref="results")
        self.assertEqual(rec["files"]["evidence"], hashlib.sha256(self.files["evidence_d1.json"].encode()).hexdigest())
        self.assertEqual(rec["files"]["report"], hashlib.sha256(b"# report\n").hexdigest())
        self.assertEqual(rec["files"]["trades"], hashlib.sha256(b'{"XS_FUND_FADE":[]}').hexdigest())   # decompressed
        self.assertEqual((rec["source_commit"], rec["ran_at"]), ("1" * 40, "2026-10-14T15:27Z"))
        self.assertEqual(rec["datasets"], {"archive-data": "2" * 40, "evidence-results": "3" * 40})
        self.assertEqual((rec["dataset_sha256"], rec["extra_inputs"]), ("cd" * 32, {"d1_inputs_sha256": "ef" * 32}))
        self.assertEqual((rec["preregistration"], rec["confirmed"]), ("docs/p.md", []))
        path = os.path.join(self.tmp, "h.jsonl")
        one = RR.append(rec, path)
        self.assertEqual((one["seq"], one["prev_sha256"]), (1, RR.ZERO))
        with self.assertRaises(SystemExit):
            RR.append(rec, path)                                        # the same run twice
        other = dict(rec, results_commit="f" * 40)
        two = RR.append(other, path)
        self.assertEqual(two["prev_sha256"], hashlib.sha256(RR.read(path)[0].encode()).hexdigest())
        self.assertEqual(RR.verify(RR.read(path)), [])
        with open(path, "a") as fh:
            fh.write("not json\n")
        with self.assertRaises(SystemExit):
            RR.append(dict(rec, results_commit="e" * 40), path)          # never appends to a broken history


class A4Artifacts(unittest.TestCase):
    def test_shards_and_matrix_are_verified_before_recording(self):
        import gzip
        shard = gzip.compress(b'{"trial_id":"x","net_R":1}\n')
        files = {'trades/x.jsonl.gz': shard, 'daily_returns.npz': b'matrix',
                 'REPORT_A4.md': b'# diagnostic',
                 'run_meta.txt': b'v9/census-evidence aaaaa 2026-10-15T00:00Z',
                 'dataset_ref.txt': b'archive-data bbbbb\n'}
        files['trades_a4.json'] = json.dumps({'trades/x.jsonl.gz':
            {'sha256': hashlib.sha256(shard).hexdigest(), 'trades': 1}}).encode()
        evidence = dict(schema='v9.census-replay/1', provenance=dict(
            dataset_sha256='c'*64, protocol_sha256='d'*64, plan_sha256='e'*64,
            replay_code_hash='f'*64, runner_sha256='a'*64, universe_sha256='b'*64),
            known_trial_return_matrix_complete=False, historical_trial_census_complete=False,
            artifacts={p: hashlib.sha256(files[p]).hexdigest()
                       for p in ('daily_returns.npz', 'REPORT_A4.md', 'trades_a4.json')})
        files['evidence_a4.json'] = json.dumps(evidence).encode()
        def git(repo, *args):
            return b'1'*40 if args[0] == 'rev-parse' else files[args[1].split(':', 1)[1]]
        with mock.patch.object(RR, '_git', side_effect=git):
            result = RR.build('A4', repo='unused', ref='results')
            self.assertEqual(result['confirmed'], [])
            self.assertFalse(result['known_trial_return_matrix_complete'])
            self.assertEqual(result['preregistration_sha256'], 'd'*64)
            for path in ('daily_returns.npz', 'trades/x.jsonl.gz'):
                with self.subTest(path=path):
                    original = files[path]
                    files[path] = b'corrupted'
                    with self.assertRaises(ValueError):
                        RR.build('A4', repo='unused', ref='results')
                    files[path] = original


if __name__ == "__main__":
    unittest.main()
