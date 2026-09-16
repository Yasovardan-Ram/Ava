from __future__ import annotations

import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextvars import ContextVar

_SESSION_OVERRIDE: ContextVar[str | None] = ContextVar("ava_session_override", default=None)
_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="ava-job")
_lock = threading.Lock()
_jobs: dict[str, dict] = {}
_MAX_JOBS = 200
_TTL_SECONDS = 1800


def set_session_override(value: str | None):
    return _SESSION_OVERRIDE.set(value)


def reset_session_override(token):
    _SESSION_OVERRIDE.reset(token)


def current_session_override():
    return _SESSION_OVERRIDE.get()


def submit(fn, *, session_id: str, app):
    job_id = uuid.uuid4().hex[:12]
    now = time.time()
    with _lock:
        _prune_locked(now)
        _jobs[job_id] = {"status": "queued", "created": now, "result": None, "error": None, "session_id": session_id}

    def runner():
        token = set_session_override(session_id)
        try:
            with app.app_context():
                with _lock:
                    _jobs[job_id]["status"] = "running"
                result = fn()
                if hasattr(result, "get_json"):
                    payload = result.get_json(silent=True)
                    status_code = result.status_code
                else:
                    payload = result
                    status_code = 200
                with _lock:
                    _jobs[job_id].update(status="complete", result=payload, status_code=status_code, finished=time.time())
        except Exception as exc:  # never kill the worker or Flask process
            with _lock:
                _jobs[job_id].update(status="error", error=f"{type(exc).__name__}: {exc}", status_code=500, finished=time.time())
        finally:
            reset_session_override(token)

    _executor.submit(runner)
    return job_id


def get(job_id: str, session_id: str | None = None):
    with _lock:
        _prune_locked(time.time())
        job = _jobs.get(job_id)
        if not job or (session_id and job.get("session_id") != session_id):
            return {}
        return dict(job)


def _prune_locked(now):
    stale = [jid for jid, job in _jobs.items() if now - job.get("created", now) > _TTL_SECONDS]
    for jid in stale:
        _jobs.pop(jid, None)
    if len(_jobs) > _MAX_JOBS:
        oldest = sorted(_jobs, key=lambda jid: _jobs[jid].get("created", 0))[: len(_jobs) - _MAX_JOBS]
        for jid in oldest:
            _jobs.pop(jid, None)
