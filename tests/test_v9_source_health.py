"""Operational alerts do not confer research or trading authority."""
import copy
import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from v9 import source_health as H

NOW = 1800000000


def fixture():
    doc = dict(schema='v9.market/1', as_of=NOW, fresh_until=NOW+7200,
               sources={s: dict(status='OK', fetched_at=NOW) for s in H.SOURCES},
               assets={'BTC': {'gate': {'as_of': NOW}}}, regime={})
    doc['sources']['gate.stats'].update(requested=1, answered=1)
    for path, _ in H.OBSERVATIONS.values():
        item = doc['regime']
        for key in path[:-1]:
            item = item.setdefault(key, {})
        item[path[-1]] = NOW
    return doc


class Health(unittest.TestCase):
    def row(self, doc, sid, now=NOW):
        return next(r for r in H.evaluate(doc, now)['sources'] if r['source'] == sid)

    def test_all_sources_and_read_only(self):
        doc = fixture(); old = copy.deepcopy(doc)
        report = H.evaluate(doc, NOW)
        self.assertEqual(report['status'], 'OK')
        self.assertEqual(len(report['sources']), 16)
        self.assertFalse(report['decision_authority'])
        self.assertEqual(doc, old)
        self.assertEqual(self.row(doc, 'hl.ctx')['coverage'], 'FETCH_ONLY')

    def test_every_source_failure_and_omission_alerts(self):
        for sid in H.SOURCES:
            with self.subTest(source=sid):
                doc = fixture(); doc['sources'][sid]['status'] = 'ERROR'
                self.assertEqual(self.row(doc, sid)['state'], 'ALERT')
                del doc['sources'][sid]
                self.assertIn('MISSING_SOURCE', self.row(doc, sid)['issues'])

    def test_optional_key_is_not_a_false_success_or_failure(self):
        doc = fixture(); doc['sources']['cg.global'] = {'status': 'MISSING_KEY'}
        self.assertEqual(H.evaluate(doc, NOW)['status'], 'OK')
        self.assertEqual(self.row(doc, 'cg.global')['state'], 'NOT_CONFIGURED')

    def test_fetch_age_boundaries_and_future_or_invalid_times(self):
        for stamp, issue in [(NOW-7200, None), (NOW-7201, 'FETCH_STALE'),
                             (NOW+301, 'FETCH_FUTURE_TIME'), (10**1000, 'FETCH_FUTURE_TIME'),
                             (True, 'FETCH_TIME_UNKNOWN'),
                             (float('nan'), 'FETCH_TIME_UNKNOWN'), (None, 'FETCH_TIME_UNKNOWN')]:
            doc = fixture(); doc['sources']['hl.ctx']['fetched_at'] = stamp
            self.assertEqual(self.row(doc, 'hl.ctx')['issues'], [issue] if issue else [])

    def test_fresh_fetch_cannot_hide_stale_observation(self):
        for sid, (path, budget) in H.OBSERVATIONS.items():
            doc = fixture(); item = doc['regime']
            for key in path[:-1]: item = item[key]
            item[path[-1]] = NOW-budget-1
            self.assertIn('OBSERVATION_STALE', self.row(doc, sid)['issues'])
            item[path[-1]] = NOW+301
            self.assertIn('OBSERVATION_FUTURE_TIME', self.row(doc, sid)['issues'])
            del item[path[-1]]
            self.assertIn('OBSERVATION_TIME_UNKNOWN', self.row(doc, sid)['issues'])

    def test_partial_gate_and_old_individual_asset_alert(self):
        doc = fixture(); doc['sources']['gate.stats']['requested'] = 2
        self.assertIn('PARTIAL_COVERAGE', self.row(doc, 'gate.stats')['issues'])
        doc['assets']['BTC']['gate']['as_of'] = NOW-7201
        self.assertIn('OBSERVATION_STALE', self.row(doc, 'gate.stats')['issues'])
        doc['assets'] = {}
        self.assertIn('OBSERVATION_COVERAGE_MISMATCH', self.row(doc, 'gate.stats')['issues'])
        doc['sources']['gate.stats']['answered'] = True
        self.assertIn('INVALID_COVERAGE', self.row(doc, 'gate.stats')['issues'])

    def test_collector_failure_cannot_be_hidden_by_previous_fresh_file(self):
        for outcome in ("failure", "skipped", "cancelled", ""):
            report = H.evaluate(fixture(), NOW, outcome)
            self.assertEqual(report["status"], "ALERT")
            self.assertIn("COLLECTOR_NOT_SUCCESSFUL", report["document_issues"])

    def test_document_clock_schema_expiry_and_unknown_source(self):
        for doc in (None, [], {}, {'schema': 'wrong'}, dict(fixture(), fresh_until=NOW+99999),
                    dict(fixture(), as_of=NOW+301), dict(fixture(), sources=[])):
            self.assertEqual(H.evaluate(doc, NOW)['status'], 'ALERT')
        self.assertIn('DOCUMENT_EXPIRED', H.evaluate(fixture(), NOW+7201)['document_issues'])
        doc = fixture(); doc['sources']['new'] = {'status': 'OK', 'fetched_at': NOW}
        self.assertIn('UNREGISTERED_SOURCE', self.row(doc, 'new')['issues'])

    def test_cli_retains_failure_and_never_echoes_raw_error_secrets(self):
        with tempfile.TemporaryDirectory() as tmp:
            src, out, summary = [Path(tmp)/p for p in ('input', 'report', 'summary')]
            for text in ('bad json SECRET', '{"schema":1,"schema":2}', '{"x":NaN}', None):
                if text is not None: src.write_text(text)
                elif src.exists(): src.unlink()
                capture = io.StringIO()
                with patch.dict(os.environ, {'GITHUB_STEP_SUMMARY': str(summary)}), patch.object(H.time, 'time', return_value=NOW), contextlib.redirect_stdout(capture):
                    self.assertEqual(H.main(['--input', str(src), '--out', str(out)]), 1)
                self.assertEqual(json.loads(out.read_text())['status'], 'ALERT')
                self.assertNotIn('SECRET', capture.getvalue()+out.read_text()+summary.read_text())

    def test_untrusted_source_cannot_inject_workflow_command_or_html(self):
        doc = fixture(); sid = 'bad\n::error::injected|<script>'
        doc['sources'][sid] = {'status': 'ERROR', 'error': 'SECRET'}
        with tempfile.TemporaryDirectory() as tmp:
            summary = Path(tmp)/'summary'; capture = io.StringIO()
            with patch.dict(os.environ, {'GITHUB_STEP_SUMMARY': str(summary)}), contextlib.redirect_stdout(capture):
                H.emit(H.evaluate(doc, NOW))
            self.assertNotIn('\n::error::', capture.getvalue())
            self.assertNotIn('<script>', summary.read_text())
            self.assertNotIn('SECRET', capture.getvalue()+summary.read_text())

    def test_scan_runs_monitor_after_collection_even_on_failure(self):
        text = (Path(__file__).resolve().parents[1]/'.github/workflows/scan.yml').read_text()
        start = text.index('      - name: v9 market context source freshness')
        end = text.index('      - name: v8 audit snapshot', start)
        steps = text[start:end]
        self.assertEqual(steps.count('if: always()'), 2)
        self.assertEqual(steps.count('continue-on-error: true'), 2)
        self.assertIn('python -m v9.source_health', steps)
        self.assertIn('actions/upload-artifact@v4', steps)
        self.assertLess(text.index('run: python -m v9.market'), start)


if __name__ == '__main__':
    unittest.main()
