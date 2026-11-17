"""Synthetic global reconstruction from verified units; no market activation."""
import hashlib
from pathlib import Path
from tools.v9 import control_outcomes as O, control_partition_execute as E, control_partition_plan as P
from tools.v9 import verify_control_partitions as V


def merge(source,out,plan,units,context,input_hash,*,max_rows=25000):
    O.V.check(input_hash!=P.INPUT_SHA and context.get('provenance',{}).get('synthetic') is True,
              'registered market reconciliation remains disabled')
    source,out=Path(source).resolve(),Path(out).resolve()
    for directory in [source,*[Path(p).resolve() for p in units]]:
        O.V.check(out!=directory and out not in directory.parents and directory not in out.parents,'merge overlaps inputs')
    O.V.check(not out.exists(),'preserve previous merge')
    expected={p.name:O.X.sha(p) for p in (Path(E.__file__),Path(P.__file__),Path(E.A.__file__),
              Path(E.A.P.__file__),Path(E.A.E.__file__),Path(E.W.__file__))}
    # Verify before opening the destination. Incomplete units never produce a success manifest.
    verified=V.verify(source,plan,units,input_hash,expected,O.X.sha(O.ROOT/'docs/v9/phase-a6-execution-inference.md'))
    sequence=iter(V.pairs(verified))
    class Replay:
        def close(self):sequence.close()
        def match(self,signal):
            pair=next(sequence)
            O.V.check((pair['trial_id'],pair['signal_id'],pair['source_ordinal'])==
                      (signal['trial_id'],signal['signal_id'],signal['source_ordinal']),'global source order mismatch')
            return pair
    result=O.run(source,out,lambda:(context,Replay()),input_hash,max_rows=max_rows)
    result['implementation_sha256']={**result.get('implementation_sha256',{}),**expected,
        Path(__file__).name:O.X.sha(Path(__file__)),Path(V.__file__).name:O.X.sha(Path(V.__file__))}
    result['partition_transport']=dict(schema='v9.a6-synthetic-partition-transport/1',synthetic_only=True,
        plan_sha256=hashlib.sha256(E.canonical(plan)).hexdigest(),
        receipts=[dict(unit_id=v['receipt']['unit_id'],sha256=v['receipt_sha256']) for v in verified],
        resource_qualified=False,execution_authorized=False)
    O.X.write_json(out/'manifest.json',result)
    return result
