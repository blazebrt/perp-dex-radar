"""Local stand-in for numba, for smoke tests in sandboxes that cannot install packages (pypi blocked).

    PYTHONPATH=tools/v9/devstub python tools/v9/evidence.py --md <small md> --out /tmp/ev --replications 50

njit/jit become no-op decorators, so the research simulator runs as plain Python: correct but slow. Use it only on
small synthetic data; real runs happen in GitHub Actions with the real numba."""


def njit(*args, **kwargs):
    if len(args) == 1 and callable(args[0]) and not kwargs:
        return args[0]

    def deco(f):
        return f
    return deco


jit = njit
