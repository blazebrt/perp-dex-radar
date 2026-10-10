"""A thread-safe recorder the legacy engines report into through one-line hooks.

The hooks only append what the legacy code already has in hand (a payload it just fetched, a list it just built,
the reason it is about to skip something). Every method swallows its own errors and returns None, so a hook can
never raise into, slow down noticeably, or change the result of the legacy code around it. Nothing in the legacy
engines reads anything back from here.

This module must not import scanner (scanner imports it)."""
from __future__ import annotations

import threading
import time


class Recorder:
    def __init__(self):
        self._lock = threading.Lock()
        self.reset()

    def reset(self):
        self.payloads = {}       # dex -> {key: (receive_ts, payload)}  the raw market lists, as fetched
        self.rows = {}           # dex -> adapter output rows (None when the adapter failed)
        self.events = []         # (code, dict) universe events: price conflicts, fallback
        self.ident = None        # the v8.identity Resolution of the last build_universe() (Phase 2)
        self.exposure = {}       # v8 Phase 5: exposure-metadata source -> {"state": ..., "detail": {...}}
        self.candles = {}        # (coin, tf) -> [(source, outcome), ...] for the last failed candle request
        self.plans = []          # live radar plan rejections: (id(a), spec id, reason inputs)
        self.filters = []        # live radar variant-filter rejections: (id(a), spec id)
        self.live = False        # True only while scanner.run() evaluates this scan's charts
        self.universe_ts = None

    # ---- shared universe (scanner.build_universe and the DEX adapters)
    def begin_universe(self):
        try:
            with self._lock:
                self.payloads, self.rows, self.events, self.candles = {}, {}, [], {}
                self.ident = None
                self.exposure = {}
                self.universe_ts = time.time()
        except Exception:  # noqa: BLE001
            pass

    # ---- the live window of scanner.run(): only this scan's chart evaluation is recorded
    def begin_live(self):
        try:
            with self._lock:
                self.plans, self.filters = [], []
                self.live = True
        except Exception:  # noqa: BLE001
            pass

    def end_live(self):
        self.live = False

    def exposure_meta(self, name, state, detail=None):
        """v8 Phase 5: the health of an economic-exposure metadata source of this universe (OK, FAILED, UNAVAILABLE,
        MALFORMED) with what it returned."""
        try:
            with self._lock:
                self.exposure[name] = {"state": state, "detail": dict(detail or {})}
        except Exception:  # noqa: BLE001
            pass

    def payload(self, dex, key, data):
        try:
            with self._lock:
                self.payloads.setdefault(dex, {})[key] = (time.time(), data)
        except Exception:  # noqa: BLE001
            pass

    def universe_rows(self, results):
        try:
            with self._lock:
                self.rows = {dex: (list(rows) if rows is not None else None) for dex, rows in results.items()}
        except Exception:  # noqa: BLE001
            pass

    def identity(self, res):
        """Keep the identity decision of this universe (v8.identity.resolve) for the audit."""
        try:
            with self._lock:
                self.ident = res
        except Exception:  # noqa: BLE001
            pass

    def event(self, code, **kw):
        try:
            with self._lock:
                self.events.append((code, kw))
        except Exception:  # noqa: BLE001
            pass

    # ---- candles (scanner.get_candles, quant.bars_4h)
    def candle_miss(self, coin, tf, tried):
        try:
            with self._lock:
                self.candles[(coin, tf)] = list(tried)
        except Exception:  # noqa: BLE001
            pass

    # ---- radar plans (scanner.find_signals, only while `live`)
    def plan_reject(self, a, sp, lv, tp_r, sk, px):
        if not self.live:
            return
        try:
            with self._lock:
                self.plans.append((id(a), sp.get("id"), {
                    "lv": list(lv), "tp_r": list(tp_r), "sk": sk, "px": px, "atr": a.get("atr"),
                    "last": a.get("last"), "stop_atr": sp.get("stop_atr"), "max_risk": sp.get("max_risk")}))
        except Exception:  # noqa: BLE001
            pass

    def filter_reject(self, a, sp):
        if not self.live:
            return
        try:
            with self._lock:
                self.filters.append((id(a), sp.get("id")))
        except Exception:  # noqa: BLE001
            pass


TRACE = Recorder()
