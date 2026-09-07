"""Synthetic protocol test fixture. This is NOT a Lean verifier."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import time

p = argparse.ArgumentParser()
p.add_argument("--candidate", required=True)
p.add_argument("--baseline", required=True)
p.add_argument("--output", required=True)
a = p.parse_args()
baseline = json.loads(Path(a.baseline).read_text())
mode = baseline.get("fixture_mode", "passed")
if mode == "slow":
    time.sleep(0.5)
if mode == "timeout":
    time.sleep(10)
if mode == "no_output":
    raise SystemExit(0)
if mode == "malformed":
    Path(a.output).write_text("not json")
    raise SystemExit(0)
items = baseline["items"]
match = hashlib.sha256(Path(a.candidate).read_bytes()).hexdigest() == baseline["source_sha256"]
result = {
    "schema_version": 1,
    "status": "passed" if match and mode != "failed" else "failed",
    "coverage": "incomplete" if mode == "incomplete" else "complete",
    "review_items": [] if mode == "wrong_inventory" else items,
    "verified_item_ids": [] if mode == "missing_ids" else [i["id"] for i in items],
    "checks": [{"name": "synthetic-hash", "status": "passed" if match else "failed"}],
    "fixture_only": True,
    "credentials_present": [k for k in os.environ if k == "FAKE_TEST_API_KEY"],
}
Path(a.output).write_text(json.dumps(result))
raise SystemExit(1 if mode == "nonzero" or not match else 0)
