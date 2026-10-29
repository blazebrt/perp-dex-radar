"""Observed funding events without invented completeness or payment timing."""
import csv
import gzip
import math
from pathlib import Path

HOUR = 3600


def prepare(records):
    """Normalize observations; interval hints never prove absent payments.

    Off-grid events are retained as evidence but cannot enter the opening-time
    execution model. A funding-dependent trial must be unavailable if any occur
    in its requested signal window, rather than silently dropping/rounding them.
    """
    observed = {}
    intervals = {}
    for row in records:
        t, rate, interval = row['t'], row['rate'], row.get('interval_h')
        if (type(t) is not int or t < 0 or isinstance(rate, bool) or
                not isinstance(rate, (int, float)) or not math.isfinite(rate)):
            raise ValueError('invalid funding observation')
        if interval is not None and (type(interval) is not int or interval <= 0):
            raise ValueError('invalid funding interval hint')
        if t in observed:
            raise ValueError('duplicate funding timestamp')
        observed[t] = float(rate)
        intervals[t] = interval
    ordered = dict(sorted(observed.items()))
    return dict(observed_events=ordered,
                hourly_events={t: rate for t, rate in ordered.items() if t % HOUR == 0},
                off_grid_events={t: rate for t, rate in ordered.items() if t % HOUR},
                interval_hints={t: intervals[t] for t in ordered},
                funding_complete={},
                completeness_status='UNAVAILABLE_SOURCE_COVERAGE',
                reason='Observed rows and interval hints do not prove absence of omitted settlements.')


def read(path):
    """Strict parser for the pinned archive schema, including empty files."""
    with gzip.open(Path(path), 'rt', encoding='utf8', newline='') as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames != ['t', 'rate', 'interval_h']:
            raise ValueError('invalid funding schema')
        rows = []
        for row in reader:
            if None in row or any(row[k] is None for k in reader.fieldnames):
                raise ValueError('malformed funding row')
            rows.append(dict(t=int(row['t']), rate=float(row['rate']),
                             interval_h=int(row['interval_h']) if row['interval_h'] else None))
    return prepare(rows)
