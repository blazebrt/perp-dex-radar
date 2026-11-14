"""Local synthetic selector comparison; no market inputs or qualification."""
import hashlib,json,platform,statistics,subprocess,sys,time,types
from pathlib import Path
root=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(root))
from tests.test_v9_control_cohort import row
from tools.v9 import control_cohort as candidate
baseline_commit='c10d458b1ed44b78d67dfe483413ac319cf33cf2'
raw=subprocess.check_output(['git','-c','safe.directory=*','-C',str(root),'show',baseline_commit+':tools/v9/control_cohort.py'])
baseline=types.ModuleType('baseline_cohort');exec(compile(raw,'baseline_cohort.py','exec'),baseline.__dict__)
population=[row(str(i)) for i in range(781)];signal=row()
rounds=[]
for repeat in range(5):
    observations={};results={}
    for name,module in ([('baseline',baseline),('candidate',candidate)] if repeat%2==0 else [('candidate',candidate),('baseline',baseline)]):
        start=time.perf_counter()
        results[name]=[module.select(format(i,'064x'),signal,population) for i in range(100)]
        observations[name+'_seconds']=time.perf_counter()-start
    before=json.dumps(results['baseline'],sort_keys=True,separators=(',',':'))
    after=json.dumps(results['candidate'],sort_keys=True,separators=(',',':'))
    assert before==after
    rounds.append(dict(round=repeat,**observations,output_sha256=hashlib.sha256(before.encode()).hexdigest()))
report=dict(schema='v9.a6-selection-timing/1',baseline_commit=baseline_commit,
    baseline_source_sha256=hashlib.sha256(raw).hexdigest(),candidate_source_sha256=hashlib.sha256(Path(candidate.__file__).read_bytes()).hexdigest(),
    recipe_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),python=sys.version,platform=platform.platform(),
    candidates=781,selections_per_round=100,rounds=rounds,exact_canonical_outputs_equal=True,
    baseline_median_seconds=statistics.median(r['baseline_seconds'] for r in rounds),
    candidate_median_seconds=statistics.median(r['candidate_seconds'] for r in rounds),
    synthetic_only=True,market_data_loaded=False,resource_qualified=False,promotion_authority=False,
    limitations=['Isolated local selector timing, not a complete-pipeline or hosted benchmark.','Alternating order reduces but does not eliminate timing noise.','Synthetic features do not establish real-population runtime or history coverage.','No full-volume resource bound or independent qualification follows.'])
output=Path(__file__).with_name('comparison.json')
with output.open('x',encoding='utf8',newline='\n') as f:json.dump(report,f,sort_keys=True,indent=2);f.write('\n')
print(json.dumps({k:report[k] for k in ('baseline_median_seconds','candidate_median_seconds','exact_canonical_outputs_equal')}))
