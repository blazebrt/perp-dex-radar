"""Per-engine audit parts: each engine process writes data/v8/parts/<engine>.json at the end of its run; the
snapshot step (python -m v8.snapshot) assembles them after all engines ran.

safe_audit() is the only entry point the legacy engines call. It never raises: an audit failure is written into
the part (so the snapshot shows the gap) and logged, and the engine's own output is already on disk by then."""
from __future__ import annotations

import json
import os
import sys
import time
import traceback

from . import provenance

PART_DIR = os.path.join("data", "v8", "parts")


def part_path(out_dir, name):
    return os.path.join(out_dir, PART_DIR, f"{name}.json")


def write(out_dir, name, body):
    p = part_path(out_dir, name)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(body, fh, separators=(",", ":"), sort_keys=True, allow_nan=False, default=str)
    os.replace(tmp, p)
    return p


def read(out_dir, name):
    try:
        with open(part_path(out_dir, name)) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def safe_audit(name, out_dir, fn, ts=None, **inputs):
    """Run fn(**inputs) -> dict of part content and write it with the engine header. Never raises."""
    try:
        ts = int(ts if ts is not None else time.time())
        body = {"header": provenance.header(name, ts)}
        try:
            body.update(fn(**inputs) or {})
            body["ok"] = True
        except Exception as e:  # noqa: BLE001 - the audit must never break the scan
            body.update(ok=False, error=f"{type(e).__name__}: {e}"[:500],
                        trace=traceback.format_exc()[-2000:])
            print(f"[v8] {name} audit failed: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
        write(out_dir, name, body)
        return body
    except Exception as e:  # noqa: BLE001
        print(f"[v8] {name} audit part could not be written: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
        return None
