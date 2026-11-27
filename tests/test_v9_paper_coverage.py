"""Retained synthetic observations only; no market data or GitHub writes."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from v9 import paper_coverage as C
from v9 import paper_history as H
from tests.test_v9_paper_history import fixture


class Coverage(unittest.TestCase):
    def captures(self, root):
        files, paths = {}, []
        for stamp, rows in [(1000, [dict(id='old', t_in=10, s='X', c='BTC', d=1)]),
                            (1100, [dict(id='old', t_in=10, s='X', c='BTC', d=1, r=2),
                                    dict(id='new', t_in=None)]),
                            (1500, [dict(id='new', t_in=True), dict(id='future', t_in=1600)])]:
            fixture(root, stamp=stamp, closed=rows)
            objects, path = H.package(root)
            files.update(objects); paths.append(path)
        return files, paths

    def test_union_dedup_pruning_conflicts_and_no_inferred_authority(self):
        with tempfile.TemporaryDirectory() as tmp:
            files, paths = self.captures(Path(tmp))
            result = C.assess(files.__getitem__, paths, revision='a'*40)
            self.assertEqual(result, C.assess(files.__getitem__, paths[::-1], revision='a'*40))
            self.assertEqual(result['unique_identities'], 3)
            self.assertEqual(result['unique_record_versions'], 5)
            self.assertEqual(result['original_sources_reverified'], 3)
            self.assertEqual(result['largest_observed_capture_spacing'], 400)
            self.assertEqual(result['conflicting_entry_identities'], ['new'])
            self.assertEqual(result['identities_with_missing_or_invalid_entry_time'], 1)
            self.assertEqual(result['identities_with_entry_after_capture'], 1)
            self.assertEqual(result['entry_authority_unavailable'], 3)
            self.assertEqual(result['entry_authority_verified'], 0)
            self.assertFalse(result['historical_completeness_verified'])
            self.assertFalse(result['trade_authorization'])

    def test_corruption_missing_objects_and_duplicate_inventory_fail_whole_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            files, paths = self.captures(Path(tmp))
            with self.assertRaisesRegex(ValueError, 'duplicate'):
                C.assess(files.__getitem__, paths+paths[:1], revision='a'*40)
            broken = dict(files); broken[paths[0]] = b'broken'
            with self.assertRaises(ValueError):
                C.assess(broken.__getitem__, paths, revision='a'*40)
            del broken[paths[0]]
            with self.assertRaises(KeyError):
                C.assess(broken.__getitem__, paths, revision='a'*40)
            with patch.object(C, 'MAX_OBSERVATIONS', 1):
                with self.assertRaisesRegex(ValueError, 'observation limit'):
                    C.assess(files.__getitem__, paths, revision='a'*40)

    def test_empty_is_unknown_and_commit_is_required(self):
        result = C.assess(None, [], revision='a'*40)
        self.assertEqual(result['status'], 'NO_RETAINED_CAPTURES')
        self.assertIsNone(result['largest_observed_capture_spacing'])
        self.assertFalse(result['historical_completeness_verified'])
        for revision in ('main', '', 'a'*39):
            with self.assertRaisesRegex(ValueError, 'pin'):
                C.assess(None, [], revision=revision)

    def test_local_git_complete_inventory_pinned_revision_and_exclusive_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); source = root/'source'; source.mkdir()
            files, paths = self.captures(source)
            repo = root/'repo'; repo.mkdir()
            H.git(repo, ['init', '-q'])
            H.git(repo, ['config', 'user.name', 'Synthetic test'])
            H.git(repo, ['config', 'user.email', 'test@example.invalid'])
            for path, raw in files.items():
                if '/indexes/' in path or '/views/' in path:
                    continue  # Browser accelerators are not part of offline verification.
                target = repo/path; target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(raw)
            H.git(repo, ['add', '.']); H.git(repo, ['commit', '-qm', 'synthetic captures'])
            revision = H.git(repo, ['rev-parse', 'HEAD']).decode().strip()
            (repo/paths[0]).write_bytes(b'working copy corruption must not affect pinned read')
            expected = C.assess(files.__getitem__, paths, revision=revision)
            self.assertEqual(C.assess_git(repo, revision), expected)
            output = root/'report.json'
            argv = ['--repo', str(repo), '--revision', revision, '--out', str(output)]
            C.main(argv)
            self.assertEqual(H.decode(output.read_bytes()), expected)
            with self.assertRaises(FileExistsError): C.main(argv)
