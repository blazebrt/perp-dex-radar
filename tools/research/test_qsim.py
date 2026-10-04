import numpy as np
import qsim

def run1(o, h, l, c, d, stop, target=0.0, trail=0.0, be=0.0, hold=100, fund=None, slip=0.0):
    o, h, l, c = (np.array(x, dtype=float).reshape(-1, 1) for x in (o, h, l, c))
    f = np.zeros_like(o) if fund is None else np.array(fund, dtype=float).reshape(-1, 1)
    out = qsim.sim_batch(o, h, l, c, f, np.array([slip]), np.array([0]), np.array([0]), np.array([float(d)]),
                         np.array([stop]), np.array([target]), np.array([trail]), np.array([be]), np.array([hold]),
                         True, 0.0, 0.0)
    return out[0]

# long: entry 100 (open of bar 1), stop 2% -> 98; bar 1 touches both 97 and 104 -> stop first
r = run1([100, 100, 100], [100, 104, 101], [100, 97, 99], [100, 100, 100], 1, 0.02, target=2.0)
assert qsim.REASONS[int(r[qsim.R_REASON])] == "stop" and abs(r[qsim.R_GROSS] + 1.0) < 1e-9, r
# long target 2R = 104 reached at bar 2 without stop
r = run1([100, 100, 101, 102], [100, 101, 104.5, 103], [100, 99, 100, 101], [100, 100.5, 104, 102], 1, 0.02, target=2.0)
assert qsim.REASONS[int(r[qsim.R_REASON])] == "target" and abs(r[qsim.R_GROSS] - 2.0) < 1e-9, r
# short mirror: entry 100, stop 102, target 96
r = run1([100, 100, 99, 98], [100, 101, 100, 99], [100, 99, 95.5, 97], [100, 99.5, 96, 98], -1, 0.02, target=2.0)
assert qsim.REASONS[int(r[qsim.R_REASON])] == "target" and abs(r[qsim.R_GROSS] - 2.0) < 1e-9, r
# gap through the stop: open below the stop -> exit at the open
r = run1([100, 100, 95], [100, 100.5, 96], [100, 99.5, 94], [100, 100, 95], 1, 0.02)
assert qsim.REASONS[int(r[qsim.R_REASON])] == "gap" and abs(r[qsim.R_GROSS] + 2.5) < 1e-9, r
# trailing: trail 3% of entry = 3; closes 100,106 -> stop moves to 103 from the bar after; then low 102 -> exit 103
r = run1([100, 100, 104, 106], [100, 101, 106.5, 106], [100, 99, 103.5, 102], [100, 101, 106, 104], 1, 0.02, trail=0.03)
assert qsim.REASONS[int(r[qsim.R_REASON])] == "trail" and abs(r[qsim.R_GROSS] - 1.5) < 1e-9, r
# time exit after 2 bars at the close
r = run1([100, 100, 100, 100], [100, 101, 101, 101], [100, 99.5, 99.5, 99.5], [100, 100.5, 101, 100], 1, 0.02, hold=2)
assert qsim.REASONS[int(r[qsim.R_REASON])] == "time" and abs(r[qsim.R_GROSS] - 0.5) < 1e-9, r
# funding: long pays 0.1% settled at bar 2 (held), not at bar 1 (entry bar)
r = run1([100, 100, 100, 100], [100, 100.1, 100.1, 100.1], [100, 99.9, 99.9, 99.9], [100, 100, 100, 100], 1, 0.02,
         hold=3, fund=[0, 0.01, 0.001, 0])
assert abs(r[qsim.R_FUND] - 0.001 / 0.02) < 1e-9, r
r = run1([100, 100, 100, 100], [100, 100.1, 100.1, 100.1], [100, 99.9, 99.9, 99.9], [100, 100, 100, 100], -1, 0.02,
         hold=3, fund=[0, 0.01, 0.001, 0])
assert abs(r[qsim.R_FUND] + 0.001 / 0.02) < 1e-9 and r[qsim.R_NET] > 0, r
# one at a time: second signal while busy is skipped
o = np.full((6, 1), 100.0); h = o + 0.5; l = o - 0.5; c = o.copy(); f = np.zeros_like(o)
out = qsim.sim_batch(o, h, l, c, f, np.array([0.0]), np.array([0, 1]), np.array([0, 0]), np.array([1.0, 1.0]),
                     np.array([0.02, 0.02]), np.zeros(2), np.zeros(2), np.zeros(2), np.array([3, 3]), True, 0.0, 0.0)
assert not np.isnan(out[0, 0]) and np.isnan(out[1, 0]), out
print("simulator tests OK")
