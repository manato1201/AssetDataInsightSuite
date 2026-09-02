"""In-memory background job tracking for the GUI's scan trigger.

A scan over a large project can take a while; blocking the HTTP request for
its whole duration made the GUI feel frozen (and risked a browser/proxy
timeout). Jobs run on a plain `threading.Thread` — no task queue dependency,
appropriate for a local single-user tool — and their state lives only in
process memory: losing it on restart just means losing progress *display*,
the scan_run itself is already safely committed to insight.db as it goes.
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field

# Bound growth over a long-running GUI session; old entries are pruned, not
# the underlying insight.db data (which is unaffected either way).
MAX_TRACKED_JOBS = 50


@dataclass
class ScanJob:
    job_id: str
    producers: list[str]
    target: str
    since: str | None
    run_checks_after: bool
    status: str = "running"  # running | success | failed
    current_producer: str | None = None
    scan_run_ids: list[int] = field(default_factory=list)
    error: str | None = None

    def to_dict(self) -> dict:
        return {
            "job_id": self.job_id,
            "status": self.status,
            "current_producer": self.current_producer,
            "scan_run_ids": list(self.scan_run_ids),
            "producers_total": len(self.producers),
            "producers_done": len(self.scan_run_ids),
            "error": self.error,
        }


class JobStore:
    def __init__(self) -> None:
        self._jobs: dict[str, ScanJob] = {}
        self._order: list[str] = []
        self._lock = threading.Lock()

    def create(
        self,
        producers: list[str],
        target: str,
        since: str | None,
        run_checks_after: bool,
    ) -> ScanJob:
        job = ScanJob(
            job_id=uuid.uuid4().hex,
            producers=producers,
            target=target,
            since=since,
            run_checks_after=run_checks_after,
        )
        with self._lock:
            self._jobs[job.job_id] = job
            self._order.append(job.job_id)
            while len(self._order) > MAX_TRACKED_JOBS:
                stale_id = self._order.pop(0)
                self._jobs.pop(stale_id, None)
        return job

    def get(self, job_id: str) -> ScanJob | None:
        with self._lock:
            return self._jobs.get(job_id)

    def run(self, job: ScanJob, run_scan_fn, run_checks_fn, db_path: str) -> None:
        """Executes the scan(s) for `job` synchronously in the calling thread.
        Intended to be the target of a background `threading.Thread`."""
        try:
            for producer_id in job.producers:
                job.current_producer = producer_id
                scan_run_id = run_scan_fn(db_path, producer_id, job.target, job.since)
                with self._lock:
                    job.scan_run_ids.append(scan_run_id)
                if job.run_checks_after:
                    run_checks_fn(db_path, job.target, scan_run_id)
            job.status = "success"
        except Exception as exc:  # surfaced to the user via /jobs/<id>
            job.error = str(exc)
            job.status = "failed"
        finally:
            job.current_producer = None
