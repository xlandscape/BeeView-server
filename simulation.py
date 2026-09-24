"""Simulation job manager for xPollinator.

Manages lifecycle of xPollinator simulations: start, monitor, cancel, auto-import results.
Jobs are stored in-memory (lost on server restart). Only completed runs persist in the DB.
"""
import asyncio
import logging
import os
import signal
import subprocess
import threading
import time
import uuid
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

logger = logging.getLogger("simulation")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

XPOLLINATOR_PATH = Path(os.getenv("XPOLLINATOR_PATH", os.path.join(os.path.dirname(__file__), "..", "xPollinator"))).resolve()
XPOLLINATOR_PYTHON = XPOLLINATOR_PATH / "model" / "core" / "bin" / "python-3.9.7-amd64" / "python.exe"
XPOLLINATOR_INIT = XPOLLINATOR_PATH / "model" / "core" / "init.py"
MAX_CONCURRENT_JOBS = int(os.getenv("MAX_CONCURRENT_JOBS", "1"))


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    IMPORTING = "importing"
    DONE = "done"
    ERROR = "error"
    CANCELLED = "cancelled"


@dataclass
class SimulationJob:
    job_id: str
    sim_id: str
    params: dict
    status: JobStatus = JobStatus.QUEUED
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    error_message: Optional[str] = None
    run_ids: list[int] = field(default_factory=list)
    xrun_path: Optional[str] = None
    _process: Optional[subprocess.Popen] = field(default=None, repr=False)

    def to_dict(self) -> dict:
        d = {
            "job_id": self.job_id,
            "sim_id": self.sim_id,
            "status": self.status.value,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "error_message": self.error_message,
            "run_ids": self.run_ids,
            "params": self.params,
        }
        if self.status == JobStatus.DONE and self.run_ids:
            d["beeview_url"] = f"http://localhost:5173?runs={','.join(str(r) for r in self.run_ids)}"
        return d


# ---------------------------------------------------------------------------
# Job Registry
# ---------------------------------------------------------------------------

_jobs: dict[str, SimulationJob] = {}
_lock = threading.Lock()


def _generate_xrun_xml(params: dict) -> str:
    """Generate .xrun XML content from parameter dict."""
    root = ET.Element("Parameters")
    param_order = [
        "SimID", "Project", "SimulationStart", "SimulationEnd",
        "NumberBeeHaveTimesteps", "BeeHaveMapCenterPointX", "BeeHaveMapCenterPointY",
        "NumberBeeHaveReplicates", "BeeHaveRandomSeed", "BeeHaveWeather",
        "BeeHaveWeatherFile", "MinNumberApplications", "MaxNumberApplications",
        "RunLabel", "HiveGroupId", "NumberMC",
    ]
    for key in param_order:
        value = params.get(key)
        if value is not None and str(value).strip():
            el = ET.SubElement(root, key)
            el.text = str(value)

    ET.indent(root, space="  ")
    return '<?xml version="1.0" encoding="utf-8"?>\n' + ET.tostring(root, encoding="unicode")


def _validate_params(params: dict) -> Optional[str]:
    """Validate simulation parameters. Returns error message or None if valid."""
    required = ["SimID", "Project", "SimulationStart", "SimulationEnd",
                "NumberBeeHaveTimesteps", "BeeHaveMapCenterPointX", "BeeHaveMapCenterPointY"]
    for key in required:
        if not params.get(key):
            return f"Missing required parameter: {key}"

    # Check SimID doesn't contain path separators
    sim_id = params["SimID"]
    if "/" in sim_id or "\\" in sim_id:
        return "SimID must not contain path separators"

    # Check run folder doesn't already exist
    run_folder = XPOLLINATOR_PATH / "run" / sim_id
    if run_folder.exists():
        return f"Run folder already exists: run/{sim_id}. Choose a different SimID."

    # Validate min <= max applications
    min_apps = int(params.get("MinNumberApplications", 0))
    max_apps = int(params.get("MaxNumberApplications", 0))
    if min_apps > max_apps:
        return "MinNumberApplications must be <= MaxNumberApplications"

    # Validate scenario exists
    project = params["Project"]
    scenario_path = XPOLLINATOR_PATH / project
    if not scenario_path.is_dir():
        return f"Scenario folder not found: {project}"

    return None


def _run_simulation(job: SimulationJob) -> None:
    """Execute simulation subprocess and auto-import results. Runs in a thread."""
    try:
        # Write .xrun file in project root (same location as template.xrun)
        xrun_content = _generate_xrun_xml(job.params)
        xrun_filename = f"_job_{job.job_id}.xrun"
        xrun_path = XPOLLINATOR_PATH / xrun_filename
        xrun_path.write_text(xrun_content, encoding="utf-8")
        job.xrun_path = str(xrun_path)

        # Start subprocess with relative path (how xPollinator expects it)
        job.status = JobStatus.RUNNING
        job.started_at = time.time()

        cmd = [str(XPOLLINATOR_PYTHON), "-u", str(XPOLLINATOR_INIT), xrun_filename]
        logger.info(f"[{job.job_id}] Starting in {XPOLLINATOR_PATH}: {' '.join(cmd)}")

        process = subprocess.Popen(
            cmd,
            cwd=str(XPOLLINATOR_PATH),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
        )
        job._process = process

        # Wait for completion
        stdout, _ = process.communicate()
        job._process = None

        if job.status == JobStatus.CANCELLED:
            return

        if process.returncode != 0:
            job.status = JobStatus.ERROR
            job.finished_at = time.time()
            # Capture last 2000 chars of output for error message
            job.error_message = (stdout or "")[-2000:] if stdout else f"Process exited with code {process.returncode}"
            logger.error(f"[{job.job_id}] Simulation failed (rc={process.returncode})")
            return

        job.status = JobStatus.COMPLETED
        logger.info(f"[{job.job_id}] Simulation completed (rc=0), stdout tail: {(stdout or '')[-500:]}")

        # Auto-import into BeeView database
        job.status = JobStatus.IMPORTING
        run_folder = XPOLLINATOR_PATH / "run" / job.sim_id
        if not run_folder.is_dir():
            # Also check if xPollinator logged why it didn't create the folder
            job.status = JobStatus.ERROR
            job.error_message = (
                f"Run folder not found: {run_folder}\n\n"
                f"Simulation output (last 1500 chars):\n{(stdout or '')[-1500:]}"
            )
            job.finished_at = time.time()
            return

        from import_run import import_run
        run_ids = import_run(run_folder, force=True)
        job.run_ids = run_ids
        job.status = JobStatus.DONE
        job.finished_at = time.time()
        logger.info(f"[{job.job_id}] Import complete. Run IDs: {run_ids}")

    except Exception as exc:
        job.status = JobStatus.ERROR
        job.finished_at = time.time()
        job.error_message = str(exc)
        logger.exception(f"[{job.job_id}] Job failed with exception")
    finally:
        # Clean up .xrun temp file
        try:
            if job.xrun_path and Path(job.xrun_path).exists():
                Path(job.xrun_path).unlink()
        except OSError:
            pass


def _count_active() -> int:
    """Count currently running jobs."""
    return sum(1 for j in _jobs.values() if j.status in (JobStatus.RUNNING, JobStatus.IMPORTING))


def _start_queued_jobs() -> None:
    """Start queued jobs if capacity allows."""
    with _lock:
        for job in _jobs.values():
            if job.status == JobStatus.QUEUED and _count_active() < MAX_CONCURRENT_JOBS:
                thread = threading.Thread(target=_run_simulation, args=(job,), daemon=True)
                thread.start()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def start_simulation(params: dict) -> tuple[Optional[str], Optional[str]]:
    """Start a new simulation job.
    
    Returns (job_id, None) on success or (None, error_message) on validation failure.
    """
    error = _validate_params(params)
    if error:
        return None, error

    job_id = str(uuid.uuid4())[:8]
    sim_id = params["SimID"]

    job = SimulationJob(job_id=job_id, sim_id=sim_id, params=params)

    with _lock:
        _jobs[job_id] = job

    _start_queued_jobs()
    return job_id, None


def get_job(job_id: str) -> Optional[SimulationJob]:
    """Get a job by ID."""
    return _jobs.get(job_id)


def list_jobs() -> list[dict]:
    """List all jobs."""
    return [job.to_dict() for job in sorted(_jobs.values(), key=lambda j: j.created_at, reverse=True)]


def cancel_job(job_id: str) -> Optional[str]:
    """Cancel a running or queued job. Returns error message or None on success."""
    job = _jobs.get(job_id)
    if not job:
        return "Job not found"
    if job.status not in (JobStatus.QUEUED, JobStatus.RUNNING):
        return f"Cannot cancel job in '{job.status.value}' state"

    job.status = JobStatus.CANCELLED
    job.finished_at = time.time()

    if job._process and job._process.poll() is None:
        try:
            if os.name == "nt":
                job._process.send_signal(signal.CTRL_BREAK_EVENT)
            else:
                job._process.terminate()
        except OSError:
            pass

    return None
