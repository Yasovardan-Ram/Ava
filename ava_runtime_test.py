"""AVA runtime smoke test. Start AVA first, then run: py ava_runtime_test.py"""
from __future__ import annotations
import json, sys, time
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:5000").rstrip("/")
LOG = "ava_runtime_test.log"
results=[]

def request(path, method="GET", payload=None):
    data = None if payload is None else json.dumps(payload).encode()
    req = Request(BASE + path, data=data, method=method, headers={"Content-Type":"application/json"})
    started=time.perf_counter()
    try:
        with urlopen(req, timeout=12) as r:
            raw=r.read().decode("utf-8", "replace")
            ms=(time.perf_counter()-started)*1000
            try: body=json.loads(raw)
            except Exception: body=raw
            return r.status, body, ms, ""
    except HTTPError as e:
        raw=e.read().decode("utf-8", "replace")
        try: body=json.loads(raw)
        except Exception: body=raw[:4000]
        return e.code, body, (time.perf_counter()-started)*1000, f"HTTPError {e.code}"
    except (URLError, TimeoutError, OSError) as e:
        return 0, None, (time.perf_counter()-started)*1000, repr(e)

def check(name, path, method="GET", payload=None, kind="json", contains=None):
    status, body, ms, err=request(path, method, payload)
    ok=status == 200
    if ok and kind == "json": ok=isinstance(body, (dict,list))
    if ok and kind == "html":
        ok=isinstance(body,str) and (contains is None or contains.lower() in body.lower())
    results.append((name, ok, status, round(ms,1), err, body))
    detail = f"  {err}" if err else ""
    if not ok and kind == "html" and status == 200:
        detail += "  (HTTP 200 is fine; content marker/type check failed)"
    print(f"{'PASS' if ok else 'FAIL':4} {name:32} HTTP {status:3} {ms:7.1f} ms{detail}")
    return body if ok else None

# Pages return HTML, so they must NOT be treated as JSON APIs.
check("Home", "/", kind="html", contains="AVA")
check("Assistant page", "/assistant", kind="html", contains="Tell AVA")
check("Fixed Digital Twin page", "/building", kind="html", contains="Digital Twin")
check("Custom Twin page", "/custom-building", kind="html", contains="Custom Building")
check("Simulation Lab page", "/simulation", kind="html", contains="Simulation")

check("Dashboard API", "/api/dashboard")
check("Building API", "/api/building")
check("Building profile API", "/api/building-profile")
check("Building capabilities API", "/api/building-capabilities")
check("HVAC integration API", "/api/hvac/integration")
check("Custom Twin API", "/api/custom-building")
check("Legacy Simulation API", "/api/simulation/state")
check("Legacy Zone API", "/api/zone-state")
check("Dashboard informational message", "/api/dashboard/message", "POST", {"message":"What is the current building status?"})
check("Custom Twin reset", "/api/custom-building/reset", "POST", {})
check("Simulation Lab reset", "/api/simulation/reset", "POST", {})
check("Custom Twin tick", "/api/custom-building/tick", "POST", {})

passed=sum(1 for r in results if r[1]); failed=len(results)-passed
with open(LOG,"w",encoding="utf-8") as f:
    f.write(f"AVA runtime smoke test\nBase: {BASE}\nPassed: {passed}\nFailed: {failed}\n\n")
    for name,ok,status,ms,err,body in results:
        f.write(f"[{ 'PASS' if ok else 'FAIL' }] {name} | HTTP {status} | {ms} ms | {err}\n")
        if body is not None:
            try: f.write(json.dumps(body, indent=2, ensure_ascii=False)[:4000]+"\n")
            except Exception: f.write(str(body)[:4000]+"\n")
        f.write("\n")
print(f"\nSaved {LOG} — {passed} passed, {failed} failed.")
print("If the AVA server terminal showed a traceback, save it as ava_server.log and upload it too.")
