"""Lossless A6 pair packing for version-two outcome packages."""
import copy
import json


def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False)


def table(rows):
    if not rows:return dict(shared={},columns=[],rows=[])
    keys=sorted(rows[0])
    if any(set(row)!=set(keys) for row in rows):raise ValueError('inconsistent table fields')
    shared={}
    remaining=rows[1:]
    for k in keys:
        reference=canonical(rows[0][k])
        if all(canonical(row[k])==reference for row in remaining):
            shared[k]=copy.deepcopy(rows[0][k])
    columns=[k for k in keys if k not in shared]
    return dict(shared=shared,columns=columns,rows=[[copy.deepcopy(row[k]) for k in columns] for row in rows])


def pack(pair):
    # JSON normalization prevents aliased output and rejects nonfinite values.
    base=json.loads(canonical(pair))
    outcomes=[base.pop('candidate')]+[row.pop('outcome') for row in base['controls']]
    features=[row.pop('features') for row in base['cohort']['controls']]
    return dict(schema='v9.a6-packed-pair/1',base=base,outcomes=table(outcomes),features=table(features))
