from __future__ import annotations
import time
import httpx


def wait_job_done(client: httpx.Client, job_id: str, timeout: int = 60) -> dict:
    """Polling до status=done|error."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = client.get(f"/ingest/jobs/{job_id}")
        r.raise_for_status()
        job = r.json()
        if job["status"] in ("done", "error"):
            return job
        time.sleep(1)
    raise TimeoutError(f"Job {job_id} did not finish in {timeout}s")
