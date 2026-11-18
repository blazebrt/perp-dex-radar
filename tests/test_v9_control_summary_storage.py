"""Logical parity against the original reuse-table storage, independently audited."""
import copy
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest

from tests import test_v9_control_pairs as fixtures
from tools.v9 import control_summary as S, control_pairs as P
from tools.v9 import verify_control_statistics as V


class ReuseStorage(unittest.TestCase):
    def test_original_layout_parity_repeated_uses_and_reopened_counts(self):
        fixture=fixtures.Pairs();fixture.setUp()
        full=fixture.matched()
        sparse=P.match(fixture.signal,fixture.candidates[:2],fixture.execute)
        trials=[dict(trial_id='trial',archive_requirement='4h'),
                dict(trial_id='hour',archive_requirement='hourly')]
        rows=[]
        for i in range(40):
            row=copy.deepcopy(sparse if i%3==0 else full)
            row.update(signal_id='signal-'+str(i),source_ordinal=i,
                       decision_time=row['decision_time']+(i//10)*86400,
                       direction=1 if i%2 else -1)
            rows.append(row)
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);results=[]
            for original in (True,False):
                path=root/('original.db' if original else 'compact.db')
                summary=S.Summary(path,trials)
                try:
                    if original:
                        summary.db.executescript('''DROP TABLE reuse;
                          CREATE TABLE reuse(trial TEXT,direction INTEGER,asset TEXT,time INTEGER,n INTEGER,
                            PRIMARY KEY(trial,direction,asset,time));''')
                    for row in rows:summary.add(row)
                    before=summary.db.execute('SELECT sum(n) FROM reuse').fetchone()
                    counts=copy.deepcopy(summary.counts)
                    with self.assertRaises(sqlite3.IntegrityError):summary.add(rows[0])
                    self.assertEqual(summary.db.execute('SELECT sum(n) FROM reuse').fetchone(),before)
                    self.assertEqual(summary.counts,counts)
                    days=[];reuse=[];sides=summary.finish(days.append,reuse.append)
                finally:summary.close()
                with closing(sqlite3.connect(path)) as reopened:
                    retained=reopened.execute('SELECT trial,direction,asset,time,n FROM reuse ORDER BY trial,direction,asset,time').fetchall()
                self.assertEqual(retained,[tuple(r[k] for k in ('trial_id','direction','asset','decision_time','uses')) for r in reuse])
                V.verify(iter(rows),trials,sides,iter(days),iter(reuse),root/('audit-old.db' if original else 'audit-new.db'))
                results.append((sides,days,reuse))
            self.assertEqual(results[0],results[1])
            self.assertEqual(sum(r['uses'] for r in results[1][2]),sum(len(r['controls']) for r in rows))
