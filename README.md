
## Performance hardening

The multi-zone HVAC optimizer uses deterministic coarse-to-fine search rather than a dense Cartesian grid. It keeps the comfort objective exact/discrete while reducing candidate evaluations substantially as room count grows. Candidate PMV calculations are memoized within an optimization run.

State JSON writes are atomic, preventing readers from observing partially-written files during concurrent requests.

For a local concurrency smoke test, run the server and then:

```powershell
py ava_load_test.py --users 25 --requests 100
```

This is a smoke test, not a production capacity guarantee. Before public multi-user deployment, persistent per-user/per-building storage should replace the current demo JSON state layer.

## Production-readiness improvements (v12)

- Per-browser building/profile/custom-twin state is stored in SQLite (`data/ava_runtime.sqlite3`) instead of one shared mutable JSON state. SQLite WAL mode and a busy timeout improve concurrent access.
- Heavy occupant-feedback, what-if, baseline-comparison, and scenario operations run through a bounded two-worker background job queue. The UI polls `/api/jobs/<job_id>` instead of holding a request open for tens of seconds.
- Background jobs are isolated by session namespace and exceptions are captured as job failures rather than killing the Flask worker.
- Server request IDs, structured request logging, and `data/ava_server.log` / `data/ava_crash.log` make unexplained process exits diagnosable.
- `main.py` disables Flask's development reloader and enables threaded serving for local testing, avoiding duplicate/reloader-related process behavior.
- The optimizer retains the v11 coarse-to-fine search and memoization improvements.

### Load test

Run the server with `py main.py`, then in a second terminal run `py ava_load_test.py --users 25 --requests 100`. For heavier endpoint testing, send several What-If/scenario requests and confirm they queue rather than creating an unbounded number of CPU-heavy simulations.
