import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from tools.v9 import hourly_quality as Q


def evidence():
    fields = dict(o='2', h='3', l='1', c='2.5', qv='12', tbqv='5')
    old = dict(t=0, id_gaps=[], bracketed=True, continuity_checked=True, conflicts=[],
               hours=[dict(t=t, trades=2, fields=dict(fields)) for t in range(0, Q.BLOCK, Q.HOUR)])
    new = dict(t=0, id_gaps=[], bracketed=True, continuity_checked=True,
               price_conflicts=[], product_aggregate_matches=True,
               volume_comparisons=[dict(field=f, product_matches=True) for f in ('qv', 'tbqv')],
               hours=[dict(t=t, trades=2, observed=True, product_qv='12.01', product_tbqv='5.01')
                      for t in range(0, Q.BLOCK, Q.HOUR)])
    return old, new


def rows():
    return [dict(t=str(t), o='2.000', h='3', l='1', c='2.5', qv='12', tbqv='5')
            for t in range(0, 3 * Q.BLOCK, Q.HOUR)]


class QualityTests(unittest.TestCase):
    def test_complete_replacement_preserves_other_rows_and_inputs(self):
        old, new = evidence()
        source = rows()
        source[-1].update(qv='0', tbqv='0')
        before = copy.deepcopy((source, old, new))
        result, ledger, coverage = Q.overlay(source, [Q.decision(old, new)], 0, 3 * Q.BLOCK)
        self.assertEqual(result[4:], source[4:])
        self.assertEqual([r['o'] for r in result[:4]], ['2'] * 4)
        self.assertEqual([r['qv'] for r in result[:4]], ['12.01'] * 4)
        self.assertEqual(ledger[0]['before'], source[:4])
        self.assertEqual(ledger[0]['after'], result[:4])
        self.assertEqual(coverage['reconstructed_hours'], 4)
        self.assertEqual((source, old, new), before)

    def test_boundary_can_supply_bracket_but_cannot_erase_gap(self):
        old, new = evidence()
        for d in (old, new):
            d.update(bracketed=False, continuity_checked=False)
        self.assertEqual(Q.decision(old, new)['action'], 'quarantine')
        boundary = dict(t=0, bracketed=True, continuity_checked=True, extended_id_gaps=[])
        self.assertEqual(Q.decision(old, new, boundary)['action'], 'reconstruct')
        for d in (old, new):
            d['id_gaps'] = [[10, 12]]
        with self.assertRaisesRegex(ValueError, 'erased'):
            Q.decision(old, new, boundary)
        boundary.update(continuity_checked=False, extended_id_gaps=[[10, 12]])
        self.assertEqual(Q.decision(old, new, boundary)['action'], 'quarantine')

    def test_quarantine_missing_union_has_no_double_count(self):
        old, new = evidence()
        old['id_gaps'] = new['id_gaps'] = [[1, 3]]
        old['continuity_checked'] = new['continuity_checked'] = False
        source = rows()[1:]
        result, ledger, c = Q.overlay(source, [Q.decision(old, new)], 0, 3 * Q.BLOCK)
        self.assertEqual(result, source[3:])
        self.assertIsNone(ledger[0]['before'][0])
        self.assertEqual(ledger[0]['after'], [None] * 4)
        self.assertEqual((c['original_missing_hours'], c['quarantined_hours'],
                          c['newly_unavailable_hours'], c['unavailable_union_hours']), (1, 4, 3, 4))

    def test_duplicate_masks_and_missing_replacement_rejected(self):
        d = Q.decision(*evidence())
        with self.assertRaisesRegex(ValueError, 'overlapping'):
            Q.overlay(rows(), [d, d], 0, 3 * Q.BLOCK)
        with self.assertRaisesRegex(ValueError, 'incomplete'):
            Q.overlay(rows()[1:], [d], 0, 3 * Q.BLOCK)
        d['replacement_rows'].pop()
        with self.assertRaises(ValueError):
            Q.overlay(rows(), [d], 0, 3 * Q.BLOCK)

    def test_conflicts_and_forged_flags_fail_closed(self):
        for mutation in ('identity', 'continuity', 'aggregate', 'price', 'volume', 'count', 'observed', 'nan'):
            old, new = evidence()
            if mutation == 'identity': new['t'] = Q.BLOCK
            if mutation == 'continuity': new['continuity_checked'] = False
            if mutation == 'aggregate': new['product_aggregate_matches'] = False
            if mutation == 'price': old['conflicts'] = [dict(field='o')]
            if mutation == 'volume': new['volume_comparisons'].pop()
            if mutation == 'count': new['hours'][0]['trades'] = 0
            if mutation == 'observed': new['hours'][0]['observed'] = False
            if mutation == 'nan': new['hours'][0]['product_qv'] = 'NaN'
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                Q.decision(old, new)

    def test_aggregate_disagreement_quarantines_even_if_continuous(self):
        old, new = evidence()
        new['volume_comparisons'][0]['product_matches'] = False
        new['product_aggregate_matches'] = False
        self.assertEqual(Q.decision(old, new)['action'], 'quarantine')

    def test_ranking_half_open_endpoints(self):
        day = 10 * Q.DAY
        self.assertEqual(Q.embargo_days([day], [day]), [])
        self.assertEqual(Q.embargo_days([day], [day - 7 * Q.DAY - Q.BLOCK]), [])
        self.assertEqual(Q.embargo_days([day], [day - 7 * Q.DAY]), [day])
        self.assertEqual(Q.embargo_days([day], [day - Q.BLOCK]), [day])
        self.assertEqual(Q.embargo_days(range(Q.DAY, 10 * Q.DAY, Q.DAY), [0, 0]),
                         list(range(Q.DAY, 8 * Q.DAY, Q.DAY)))

    def test_schedule_keeps_empty_days_order_and_no_backfill(self):
        schedule = [dict(known_at=Q.DAY, members=['B', 'A']), dict(known_at=2 * Q.DAY, members=[]),
                    dict(known_at=9 * Q.DAY, members=['C'])]
        result = Q.schedule_overlay(schedule, [0])
        self.assertEqual([r['schedule'] for r in result], schedule)
        self.assertEqual([r['new_entries_allowed'] for r in result], [False, False, True])
        result[0]['schedule']['members'].append('D')
        self.assertEqual(schedule[0]['members'], ['B', 'A'])
        with self.assertRaises(ValueError):
            Q.schedule_overlay(schedule[::-1], [])

    def test_evidence_corruption_missing_files_and_unsafe_paths(self):
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder) / 'record.json'
            raw = json.dumps(dict(schema='synthetic/1', accepted_dataset=False)).encode()
            p.write_bytes(raw)
            digest = hashlib.sha256(raw).hexdigest()
            self.assertEqual(Q.bound_json(p, digest, 'synthetic/1')['schema'], 'synthetic/1')
            Q.verify_artifacts(folder, {'record.json': digest})
            with self.assertRaises(ValueError):
                Q.bound_json(p, digest, 'wrong/1')
            for name in ('../record.json', '/record.json', 'C:/record.json', 'a\\b'):
                with self.assertRaises(ValueError):
                    Q.verify_artifacts(folder, {name: digest})
            p.write_bytes(raw + b' ')
            with self.assertRaises(ValueError):
                Q.bound_json(p, digest, 'synthetic/1')
            with self.assertRaises(ValueError):
                Q.verify_artifacts(folder, {'record.json': digest})
            with self.assertRaises(FileNotFoundError):
                Q.verify_artifacts(folder, {'missing': digest})

    def test_invalid_source_grid_and_bounds(self):
        for source in (rows()[::-1], rows() + rows()[:1], [dict(rows()[0], qv='NaN')],
                       [dict(rows()[0], t='1')], [dict(rows()[0], h='1')]):
            with self.assertRaises(ValueError):
                Q.overlay(source, [], 0, 3 * Q.BLOCK)


if __name__ == '__main__':
    unittest.main()
