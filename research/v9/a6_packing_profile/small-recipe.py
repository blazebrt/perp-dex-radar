import cProfile,pstats
from tools.v9 import control_pipeline_probe as P
p=cProfile.Profile();p.enable();P.scenario('full',8,400,assets=781,definitions=3,unavailable=1,shard_rows=25000,placement='spread',price_profile='diverse');p.disable();pstats.Stats(p).strip_dirs().sort_stats('cumulative').print_stats(30)
