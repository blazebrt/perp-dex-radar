"""HANDOVER G3: the v9 command-line tools that run outside the research job, offline.

- register_forward_test: the committed XSMOM long registration is exactly what the tool computes from today's bound
  evidence and quant.py; an unconfirmed side or an oversized multiplier is refused.
- probe_sources: every source is well-formed, a keyed source is skipped without its key, and a key never reaches
  the record or the sample; payload shapes; HTTP errors.
- probe_report: the data-sources table.

Run from the repository root:  python -m unittest tests.test_v9_tools -v"""
from __future__ import annotations

import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
import urllib.error
import zipfile
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools" / "v9"))
import register_forward_test as RF  # noqa: E402
import probe_sources as PS  # noqa: E402
import probe_report as PR  # noqa: E402
from v8 import shadow_ledger as SL  # noqa: E402

LEDGER_RECORD = ROOT / "research" / "shadow-ledger" / "000002-REGISTRATION-V9-PROBATION-XSMOM-LONG-1.json"


class ForwardTestRegistration(unittest.TestCase):
    def test_the_committed_registration_is_reproduced_exactly(self):
        rec = json.loads(LEDGER_RECORD.read_text())
        again = RF.registration("XSMOM", "long", 0.5, rec["registered_at"], rec["registration_commit"], root=str(ROOT))
        for k, v in again.items():
            self.assertEqual(rec[k], v, k)
        self.assertEqual(rec["params"]["evidence_sha256"],
                         hashlib.sha256((ROOT / RF.EVIDENCE).read_bytes()).hexdigest())
        self.assertEqual(rec["param_hash"], SL.param_hash(rec["params"]))

    def test_evaluation_starts_at_the_next_daily_close(self):
        r = RF.registration("XSMOM", "long", 0.5, 1791978690, "c" * 40, root=str(ROOT))
        self.assertEqual(r["evaluation_start"], 1792022400)                  # 2026-10-15 00:00 UTC
        r = RF.registration("XSMOM", "long", 0.5, 1792022400, "c" * 40, root=str(ROOT))
        self.assertEqual(r["evaluation_start"], 1792022400 + 86400)          # registered at a close: the next one
        self.assertEqual((r["status"], r["experiment_id"]), ("REGISTERED", "V9-PROBATION-XSMOM-LONG-1"))

    def test_unconfirmed_sides_and_oversized_multipliers_are_refused(self):
        with self.assertRaises(SystemExit):
            RF.registration("XSMOM", "short", 0.5, 1791978690, "c" * 40, root=str(ROOT))
        with self.assertRaises(SystemExit):
            RF.main(["--strategy", "XSMOM", "--side", "long", "--risk-multiplier", "0.7", "--commit", "c" * 40])


class FakeResponse(io.BytesIO):
    def __init__(self, body, status=200, headers=None):
        super().__init__(body)
        self.status = status
        self.headers = headers or {"Content-Type": "application/json"}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class Probe(unittest.TestCase):
    def test_every_source_is_well_formed(self):
        srcs = PS.sources()
        ids = [s["id"] for s in srcs]
        self.assertGreaterEqual(len(srcs), 80)
        self.assertEqual(len(ids), len(set(ids)))
        for s in srcs:
            self.assertTrue(s["url"].startswith("https://"), s["id"])
            self.assertTrue(s.get("group"), s["id"])

    def test_a_keyed_source_without_its_key_is_not_called(self):
        with mock.patch.dict(os.environ, {}, clear=True), \
                mock.patch("urllib.request.urlopen", side_effect=AssertionError("called")):
            r = PS.call({"id": "x", "group": "g", "url": "https://example.com/a", "key": "SOME_API_KEY"})
        self.assertEqual((r["status"], r["ok"]), ("NEEDS_KEY", False))

    def test_a_key_never_reaches_the_record_or_the_sample(self):
        seen = []

        def fake(req, timeout):
            seen.append(req.full_url)
            return FakeResponse(b'{"echo": "token=s3cr3t-value", "data": [1, 2]}')

        with mock.patch.dict(os.environ, {"SOME_API_KEY": "s3cr3t-value"}), mock.patch("urllib.request.urlopen", fake):
            r = PS.call({"id": "x", "group": "g", "url": "https://example.com/a?x=1", "key": "SOME_API_KEY",
                         "key_param": "token"})
        self.assertIn("token=s3cr3t-value", seen[0])                        # sent to the source
        self.assertTrue(r["ok"])
        self.assertNotIn("s3cr3t-value", json.dumps(r))                     # never kept
        self.assertIn("***", r["sample"])

    def test_http_errors_and_payload_shapes(self):
        def fail(req, timeout):
            raise urllib.error.HTTPError(req.full_url, 451, "unavailable", {}, io.BytesIO(b"blocked"))

        with mock.patch("urllib.request.urlopen", fail):
            r = PS.call({"id": "x", "group": "g", "url": "https://example.com/a"})
        self.assertEqual((r["status"], r["ok"]), (451, False))
        self.assertEqual(PS.shape(b'{"a": [1, 2]}', "application/json", None),
                         {"dict_keys": ["a"], "first": {"list_len": 2, "first": "int"}})
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("a.csv", "h\n1\n2\n")
        self.assertEqual(PS.shape(buf.getvalue(), "", "zip")["rows"], 3)
        self.assertEqual(PS.shape(gzip.compress(b"a\nb\n"), "", "gz")["rows"], 2)
        s3 = b"<Prefix>root/</Prefix><Prefix>root/A/</Prefix><Prefix>root/B/</Prefix><IsTruncated>false</IsTruncated>"
        self.assertEqual(PS.shape(s3, "", "s3list")["prefixes"], 2)
        page = PS.shape(b"<html><title>Just a moment...</title>cf-chl</html>", "text/html", None)
        self.assertTrue(page["cloudflare"])

    def test_the_report_table(self):
        doc = {"run_at": 1791900000, "results": [
            {"id": "a.ok", "group": "A", "ok": True, "status": 200},
            {"id": "b.key", "group": "B", "ok": False, "status": "NEEDS_KEY"},
            {"id": "c.blocked", "group": "C", "ok": False, "status": 451}],
            "extra": {"binance_archive": {"symbols": 10, "usdt_perpetual": 9},
                      "hyperliquid_delisted": {"total": 5, "delisted": 1, "delisted_candles": {"X": {"n": 30}}}}}
        with tempfile.TemporaryDirectory() as d:
            src, out = os.path.join(d, "s.json"), os.path.join(d, "o.md")
            Path(src).write_text(json.dumps(doc))
            with mock.patch.object(sys, "argv", ["probe_report.py", src, out]):
                PR.main()
            md = Path(out).read_text()
        self.assertIn("| `a.ok` | A | OK |", md)
        self.assertIn("| `b.key` | B | needs key |", md)
        self.assertIn("| `c.blocked` | C | blocked/failed (451) |", md)
        self.assertIn("10 USD-M symbols", md)
        self.assertIn("X 30 days", md)


if __name__ == "__main__":
    unittest.main()
