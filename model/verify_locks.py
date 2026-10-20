"""Check every locked match file against locks.json: recomputes the sha256 (model/lockutil.py) and compares it with the file and with locks.json.
Exit code 1 on any mismatch. Run it before every deploy:  make verify"""
import json, os, sys
from lockutil import sha256_of

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
lk = json.load(open(os.path.join(ROOT, "site", "data", "locks.json")))
bad = 0
for m in lk["matches"]:
    o = json.load(open(os.path.join(ROOT, m["file"])))
    got = sha256_of(o)
    ok = got == o["sha256"] == m["sha256"]
    bad += not ok
    print(("OK       " if ok else "MISMATCH ") + m["match_id"], got[:16])
sys.exit(1 if bad else 0)
