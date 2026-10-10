"""Sequential background job queue for the web front end.

Packing and extraction are disk-bound, so jobs run one at a time in a single
worker thread, like the desktop Batch queue.
"""
import itertools
import subprocess
import threading
import time
import traceback
import uuid
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field

MAX_LOG_LINES = 5000
MAX_FINISHED_JOBS = 50

PENDING, RUNNING, DONE, FAILED, CANCELLED = "queued", "running", "done", "failed", "cancelled"


@dataclass
class Job:
    kind: str
    title: str
    params: dict
    run: Callable[["Job"], str]
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    state: str = PENDING
    progress: int = 0
    status: str = "Queued…"
    eta: str = ""
    message: str = ""
    created: float = field(default_factory=time.time)
    started: float | None = None
    finished: float | None = None
    cancel_requested: bool = False
    _log: deque = field(default_factory=lambda: deque(maxlen=MAX_LOG_LINES))
    _seq: itertools.count = field(default_factory=itertools.count)
    _process: subprocess.Popen | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock)

    # -- callbacks handed to the core functions --
    def log(self, line: str) -> None:
        with self._lock:
            self._log.append((next(self._seq), str(line)))

    def set_progress(self, value: int) -> None:
        self.progress = max(0, min(100, int(value)))

    def set_status(self, text: str) -> None:
        self.status = str(text)

    def set_eta(self, text: str) -> None:
        self.eta = str(text)

    def is_cancelled(self) -> bool:
        return self.cancel_requested

    def set_process(self, process: subprocess.Popen | None) -> None:
        self._process = process
        if process is not None and self.cancel_requested:
            _terminate(process)

    def cancel(self) -> None:
        self.cancel_requested = True
        process = self._process
        if process is not None:
            _terminate(process)

    def log_since(self, since: int) -> tuple[list[tuple[int, str]], int]:
        with self._lock:
            lines = [(n, text) for n, text in self._log if n >= since]
            cursor = (self._log[-1][0] + 1) if self._log else since
        return lines, cursor

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "kind": self.kind,
            "title": self.title,
            "params": self.params,
            "state": self.state,
            "progress": self.progress,
            "status": self.status,
            "eta": self.eta,
            "message": self.message,
            "created": self.created,
            "started": self.started,
            "finished": self.finished,
        }


def _terminate(process: subprocess.Popen) -> None:
    if process.poll() is None:
        try:
            process.terminate()
        except OSError:
            pass


class JobManager:
    def __init__(self):
        self._jobs: dict[str, Job] = {}
        self._queue: deque[str] = deque()
        self._lock = threading.Lock()
        self._wake = threading.Condition(self._lock)
        self._thread = threading.Thread(target=self._loop, name="lazy-ampr-jobs", daemon=True)
        self._thread.start()

    def submit(self, job: Job) -> Job:
        with self._wake:
            self._jobs[job.id] = job
            self._queue.append(job.id)
            self._wake.notify()
        return job

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def list(self) -> list[Job]:
        with self._lock:
            return sorted(self._jobs.values(), key=lambda job: job.created, reverse=True)

    def active_for(self, kind: str, key: str) -> Job | None:
        for job in self.list():
            if job.kind == kind and job.params.get("key") == key and job.state in (PENDING, RUNNING):
                return job
        return None

    def cancel(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return False
            if job.state == PENDING:
                self._queue.remove(job_id)
                job.state, job.status, job.finished = CANCELLED, "Cancelled", time.time()
                return True
        if job.state == RUNNING:
            job.cancel()
            return True
        return False

    def remove(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.state in (PENDING, RUNNING):
                return False
            del self._jobs[job_id]
            return True

    def clear_finished(self) -> int:
        with self._lock:
            done = [k for k, j in self._jobs.items() if j.state not in (PENDING, RUNNING)]
            for key in done:
                del self._jobs[key]
            return len(done)

    def _prune(self) -> None:
        finished = sorted((j for j in self._jobs.values() if j.state not in (PENDING, RUNNING)),
                          key=lambda job: job.finished or 0)
        for job in finished[:-MAX_FINISHED_JOBS]:
            self._jobs.pop(job.id, None)

    def _loop(self) -> None:
        while True:
            with self._wake:
                while not self._queue:
                    self._wake.wait()
                job = self._jobs[self._queue.popleft()]
                job.state, job.started = RUNNING, time.time()
                job.status = "Starting…"
            try:
                job.message = job.run(job) or "Completed"
                job.state, job.status, job.progress = DONE, "Completed", 100
                job.log(f"[OK] {job.message}")
            except Exception as error:  # noqa: BLE001 - job boundary reports full traceback to UI
                if job.cancel_requested or "cancelled by user" in str(error).lower():
                    job.state, job.status, job.message = CANCELLED, "Cancelled", "Cancelled by user."
                    job.log("[CANCELLED]")
                else:
                    job.state, job.status, job.message = FAILED, "Failed", str(error) or type(error).__name__
                    job.log("[ERROR] " + traceback.format_exc())
            finally:
                job.finished = time.time()
                job.eta = ""
                job.set_process(None)
                with self._lock:
                    self._prune()
