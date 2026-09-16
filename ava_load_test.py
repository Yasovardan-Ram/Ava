"""Lightweight concurrency smoke test for a running AVA server.

Usage:
    py ava_load_test.py
    py ava_load_test.py --base http://127.0.0.1:5000 --users 25 --requests 100

This intentionally uses only the Python standard library so it can be run on
Windows without installing a separate load-testing framework.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import statistics
import time
from urllib.request import Request, urlopen


def request_once(base: str, path: str, method: str = "GET", body: dict | None = None):
    payload = json.dumps(body).encode() if body is not None else None
    req = Request(
        base.rstrip("/") + path,
        data=payload,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    started = time.perf_counter()
    try:
        with urlopen(req, timeout=15) as response:
            response.read()
            return response.status, (time.perf_counter() - started) * 1000, None
    except Exception as exc:
        return 0, (time.perf_counter() - started) * 1000, str(exc)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:5000")
    parser.add_argument("--users", type=int, default=25)
    parser.add_argument("--requests", type=int, default=100)
    args = parser.parse_args()

    paths = [
        "/",
        "/assistant",
        "/building",
        "/custom-building",
        "/api/dashboard",
        "/api/building",
        "/api/metrics",
        "/api/events",
        "/api/custom-building",
        "/api/ava/status",
        "/api/autonomy/status",
    ]

    jobs = [(paths[i % len(paths)], "GET", None) for i in range(args.requests)]
    started = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.users)) as pool:
        results = list(pool.map(lambda job: request_once(args.base, *job), jobs))
    elapsed = time.perf_counter() - started

    statuses = [r[0] for r in results]
    latencies = [r[1] for r in results]
    failures = [r for r in results if r[0] != 200]
    successful = len(results) - len(failures)
    rps = successful / elapsed if elapsed else 0.0

    print(f"AVA concurrency smoke test: {args.requests} requests / {args.users} workers")
    print(f"Success: {successful}/{len(results)}")
    print(f"Elapsed: {elapsed:.2f}s | throughput: {rps:.1f} req/s")
    if latencies:
        ordered = sorted(latencies)
        p95 = ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))]
        print(f"Latency: avg {statistics.mean(latencies):.1f} ms | p95 {p95:.1f} ms | max {max(latencies):.1f} ms")
    if failures:
        print("Failures:")
        for status, _, error in failures[:10]:
            print(f"  {status}: {error}")
        raise SystemExit(1)
    print("PASS: no HTTP failures in this smoke test.")


if __name__ == "__main__":
    main()
