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

from gaps import GAP_PARAM_KEYS, expand_gap

# BEEHAVE weather/season parameters introduced for SETAC 2026. mc.xml requires all
# of them in every .xrun; when the client does not send them we copy the defaults
# from xPollinator's template.xrun (Rothamsted 2009 sunshine hours, HoPoMo season).
WEATHER_PARAM_KEYS = [
    "SunshineHours",
    "SeasonHoPoMoRepX1", "SeasonHoPoMoRepX2", "SeasonHoPoMoRepX3",
    "SeasonHoPoMoRepX4", "SeasonHoPoMoRepX5",
]

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
        "BeeHaveWeatherFile", *WEATHER_PARAM_KEYS,
        "MinNumberApplications", "MaxNumberApplications",
        "RunLabel", "HiveGroupId", "NumberMC", "GAP", *GAP_PARAM_KEYS,
    ]
    for key in param_order:
        value = params.get(key)
        if value is not None and str(value).strip():
            el = ET.SubElement(root, key)
            el.text = str(value)

    ET.indent(root, space="  ")
    return '<?xml version="1.0" encoding="utf-8"?>\n' + ET.tostring(root, encoding="unicode")


_weather_defaults_cache: Optional[dict] = None


def _template_weather_defaults() -> dict:
    """Weather/season defaults read once from xPollinator/template.xrun."""
    global _weather_defaults_cache
    if _weather_defaults_cache is None:
        defaults = {}
        template = XPOLLINATOR_PATH / "template.xrun"
        try:
            root = ET.parse(template).getroot()
            for key in WEATHER_PARAM_KEYS:
                el = root.find(key)
                if el is not None and el.text and el.text.strip():
                    defaults[key] = " ".join(el.text.split())
        except (OSError, ET.ParseError) as exc:
            logger.warning("Could not read weather defaults from %s: %s", template, exc)
        _weather_defaults_cache = defaults
    return _weather_defaults_cache


SCENARIO_SUNSHINE_FILE = Path("weather") / "sunshine_hours.txt"


def scenario_sunshine_hours(project: Optional[str]) -> Optional[str]:
    """Sunshine series shipped with a scenario (<Project>/weather/sunshine_hours.txt), or None.

    The file holds 365 numbers separated by whitespace/commas; '#' starts a comment.
    """
    if not project:
        return None
    folder = Path(project)
    if not folder.is_absolute():
        folder = XPOLLINATOR_PATH / folder
    path = folder / SCENARIO_SUNSHINE_FILE
    if not path.is_file():
        return None
    values = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.split("#", 1)[0].replace("[", " ").replace("]", " ").replace(",", " ")
            values.extend(line.split())
        [float(v) for v in values]
    except (OSError, ValueError) as exc:
        logger.warning("Ignoring unreadable sunshine file %s: %s", path, exc)
        return None
    if len(values) != 365:
        logger.warning("Ignoring %s: expected 365 sunshine values, found %d", path, len(values))
        return None
    return " ".join(values)


def apply_weather_defaults(params: dict) -> tuple[dict, Optional[str]]:
    """Fill missing SunshineHours / SeasonHoPoMoRepX* defaults.

    SunshineHours defaults to the scenario's weather/sunshine_hours.txt when the
    scenario ships one, otherwise to template.xrun; the season parameters default to
    template.xrun. Returns (params, error). SunshineHours, if given, must hold
    exactly 365 numbers.
    """
    merged = dict(params)
    defaults = dict(_template_weather_defaults())
    scenario_series = scenario_sunshine_hours(merged.get("Project"))
    if scenario_series:
        defaults["SunshineHours"] = scenario_series
    for key in WEATHER_PARAM_KEYS:
        value = merged.get(key)
        if value is None or not str(value).strip():
            if key in defaults:
                merged[key] = defaults[key]
    sunshine = merged.get("SunshineHours")
    if sunshine is not None:
        if isinstance(sunshine, (list, tuple)):
            sunshine = " ".join(str(v) for v in sunshine)
        values = str(sunshine).split()
        try:
            [float(v) for v in values]
        except ValueError:
            return merged, "SunshineHours must contain only numbers"
        if len(values) != 365:
            return merged, f"SunshineHours must contain 365 daily values, got {len(values)}"
        merged["SunshineHours"] = " ".join(values)
    missing = [key for key in WEATHER_PARAM_KEYS if merged.get(key) is None]
    if missing:
        return merged, (
            "Missing weather parameters and no defaults in xPollinator/template.xrun: " + ", ".join(missing)
        )
    return merged, None


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

    # Validate exposure window
    first_day = int(params.get("FirstDayOfYearApplications", 1))
    last_day = int(params.get("LastDayOfYearApplications", 365))
    if not 1 <= first_day <= last_day <= 366:
        return "FirstDayOfYearApplications must be <= LastDayOfYearApplications, both within 1..366"

    return None


def _run_simulation(job: SimulationJob) -> None:
    """Execute simulation subprocess and auto-import results. Runs in a thread.

    The job is already marked RUNNING by _start_queued_jobs (under the lock), which
    prevents a second thread from picking it up while this one is starting.
    """
    if job.status == JobStatus.CANCELLED:
        return
    try:
        # Write .xrun file in project root (same location as template.xrun)
        xrun_content = _generate_xrun_xml(job.params)
        xrun_filename = f"_job_{job.job_id}.xrun"
        xrun_path = XPOLLINATOR_PATH / xrun_filename
        xrun_path.write_text(xrun_content, encoding="utf-8")
        job.xrun_path = str(xrun_path)

        # Start subprocess with relative path (how xPollinator expects it)
        if job.status == JobStatus.CANCELLED:
            return
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
                # Claim the job before the thread runs: a second call (another job queued
                # right after) must not start the same job twice.
                job.status = JobStatus.RUNNING
                thread = threading.Thread(target=_run_simulation, args=(job,), daemon=True)
                thread.start()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def prepare_simulation(params: dict) -> tuple[dict, Optional[str]]:
    """Expand the GAP preset, fill weather defaults and validate; returns (params, error).

    Does not queue anything, so a set of runs can be validated completely before the
    first job starts.
    """
    params, error = expand_gap(params)
    if error:
        return params, error
    params, error = apply_weather_defaults(params)
    if error:
        return params, error
    return params, _validate_params(params)


def queue_simulation(params: dict) -> str:
    """Queue an already prepared parameter set and return the job id."""
    job_id = str(uuid.uuid4())[:8]
    job = SimulationJob(job_id=job_id, sim_id=params["SimID"], params=params)
    with _lock:
        _jobs[job_id] = job
    _start_queued_jobs()
    return job_id


def start_simulation(params: dict) -> tuple[Optional[str], Optional[str]]:
    """Prepare and queue a simulation job.

    Returns (job_id, None) on success or (None, error_message) on validation failure.
    """
    params, error = prepare_simulation(params)
    if error:
        return None, error
    return queue_simulation(params), None


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
