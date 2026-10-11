"""CI guard for the append-only shadow experiment ledger (v8 Phase 8).

    python tools/v8/ledger_guard.py [--base <git ref>]

Fails when any file under research/shadow-ledger/ was modified, deleted, renamed or had its type changed between the
base and HEAD (files may only be added), or when the ledger at HEAD does not validate (v8.shadow_ledger.validate:
the record chain, canonical form, unique experiment ids, forward-only evaluation windows, no FINAL / LIVE status,
authority NONE). The base defaults to the pull request's base branch, else the merge base with origin/main, else
HEAD~1 on main itself."""
from __future__ import annotations

import argparse
import os
import subprocess
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, ROOT)

from v8 import shadow_ledger as SL  # noqa: E402

LEDGER = SL.DIR.replace(os.sep, "/")


def git(*args, check=True):
    r = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)
    if check and r.returncode != 0:
        raise SystemExit(f"git {' '.join(args)}: {r.stderr.strip()}")
    return r.stdout.strip()


def default_base():
    br = os.environ.get("GITHUB_BASE_REF")
    if br:
        return git("merge-base", f"origin/{br}", "HEAD")
    head_branch = os.environ.get("GITHUB_REF_NAME") or git("rev-parse", "--abbrev-ref", "HEAD", check=False)
    if head_branch == "main":
        return git("rev-parse", "HEAD~1", check=False) or None
    mb = git("merge-base", "origin/main", "HEAD", check=False)
    return mb or None


def changes(base):
    out = git("diff", "--name-status", "--no-renames", base, "HEAD", "--", LEDGER)
    return [ln.split("\t") for ln in out.splitlines() if ln.strip()]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=None)
    a = ap.parse_args(argv)
    base = a.base or default_base()
    bad = []
    if base:
        for row in changes(base):
            if row[0] != "A":
                bad.append(f"{row[0]} {row[-1]}: the shadow ledger is append-only (files may only be added)")
    problems = SL.validate(os.path.join(ROOT, SL.DIR))
    bad += [f"invalid ledger: {p}" for p in problems]
    summ = SL.summary(os.path.join(ROOT, SL.DIR))
    print(f"shadow ledger: base {base or '(none)'}; {summ['records']} records, {summ['experiments']} experiments, "
          f"head {summ['head_hash']}")
    for b in bad:
        print("FAIL", b)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
