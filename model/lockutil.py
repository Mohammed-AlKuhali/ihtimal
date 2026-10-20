"""Canonical hashing for locked prediction files.

sha256 covers the canonical JSON of the file WITHOUT: top-level `sha256`, `locked_at`, `benchmarks`, `sanity`, and `elo.clubelo_home` / `elo.clubelo_away`
(those are added AFTER the lock, from Opta / ClubElo, so they can never influence the locked numbers).
Canonical form (language independent): keys sorted, no whitespace, strings as UTF-8 JSON (no \\u escapes for non-ASCII), integers as integers,
floats as fixed 6 decimals with trailing zeros removed ("0.5", "0.123457"; 1.0 -> "1"), true/false/null.
"""
import json, hashlib, copy

EXCLUDE_TOP = {"sha256", "locked_at", "benchmarks", "sanity"}
EXCLUDE_ELO = {"clubelo_home", "clubelo_away"}


def _fmt_float(x):
    s = ("%.6f" % x).rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def canonical(o):
    if o is None:
        return "null"
    if o is True:
        return "true"
    if o is False:
        return "false"
    if isinstance(o, int):
        return str(o)
    if isinstance(o, float):
        return _fmt_float(o)
    if isinstance(o, str):
        return json.dumps(o, ensure_ascii=False)
    if isinstance(o, (list, tuple)):
        return "[" + ",".join(canonical(x) for x in o) + "]"
    if isinstance(o, dict):
        return "{" + ",".join(json.dumps(k, ensure_ascii=False) + ":" + canonical(o[k]) for k in sorted(o)) + "}"
    raise TypeError(type(o))


def hash_payload(match):
    m = copy.deepcopy(match)
    for k in EXCLUDE_TOP:
        m.pop(k, None)
    if isinstance(m.get("elo"), dict):
        for k in EXCLUDE_ELO:
            m["elo"].pop(k, None)
    return m


def sha256_of(match):
    return hashlib.sha256(canonical(hash_payload(match)).encode("utf-8")).hexdigest()


def round_floats(o, nd=6):
    if isinstance(o, float):
        return round(o, nd)
    if isinstance(o, dict):
        return {k: round_floats(v, nd) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [round_floats(v, nd) for v in o]
    return o


if __name__ == "__main__":
    import sys
    m = json.load(open(sys.argv[1]))
    got = sha256_of(m)
    print(got, "OK" if got == m.get("sha256") else "MISMATCH (stored %s)" % m.get("sha256"))
