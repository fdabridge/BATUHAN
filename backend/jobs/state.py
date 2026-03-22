"""
BATUHAN — Job State Manager (T29)
Handles all state transitions and timestamp tracking for a processing job.
Reads/writes status.json in the job's artifact store.

State machine:
  QUEUED → PREPROCESSING → STEP_A → STEP_B → STEP_C → ASSEMBLING → COMPLETE
  Any state → FAILED (on unrecoverable error)
"""

from __future__ import annotations
import logging
from datetime import datetime
from schemas.models import JobStatus, JobState
from storage.file_store import save_text_artifact, read_text_artifact

logger = logging.getLogger(__name__)

# Ordered pipeline states for progress tracking
PIPELINE_ORDER = [
    JobState.QUEUED,
    JobState.PREPROCESSING,
    JobState.STEP_A,
    JobState.STEP_B,
    JobState.STEP_C,
    JobState.ASSEMBLING,
    JobState.COMPLETE,
]

# Human-readable labels for each state (used by UI progress bar)
STATE_LABELS: dict[str, str] = {
    JobState.QUEUED.value:        "Queued — waiting to start",
    JobState.PREPROCESSING.value: "Preprocessing — extracting document text",
    JobState.STEP_A.value:        "Step A — extracting audit evidence",
    JobState.STEP_B.value:        "Step B — generating report sections",
    JobState.STEP_C.value:        "Step C — validating and correcting report",
    JobState.ASSEMBLING.value:    "Assembling — building final DOCX report",
    JobState.COMPLETE.value:      "Complete — report ready for download",
    JobState.FAILED.value:        "Failed — see error message",
}


def load_job_status(job_id: str) -> JobStatus:
    """Load the current JobStatus from storage."""
    raw = read_text_artifact(job_id, "status.json")
    return JobStatus.model_validate_json(raw)


def update_job_state(
    job_id: str,
    state: JobState,
    current_step: str | None = None,
    error_message: str | None = None,
) -> JobStatus:
    """
    Transition the job to a new state and persist the updated status.json.
    Records a timestamp for each state transition.

    Args:
        job_id:        The job to update.
        state:         New JobState to transition to.
        current_step:  Optional human-readable step description for the UI.
        error_message: Optional error message (required when state=FAILED).

    Returns:
        The updated JobStatus object.
    """
    try:
        status = load_job_status(job_id)
    except Exception:
        # If status.json doesn't exist yet, create a fresh one
        status = JobStatus(job_id=job_id, state=JobState.QUEUED)

    now = datetime.utcnow()
    status.state = state
    status.current_step = current_step or STATE_LABELS.get(state.value, state.value)

    if error_message:
        status.error_message = error_message

    if state in (JobState.COMPLETE, JobState.FAILED):
        status.completed_at = now

    # Record timestamp for this specific state transition
    status.step_timestamps[state.value] = now

    save_text_artifact(job_id, "status.json", status.model_dump_json(indent=2))
    logger.info(f"[State] Job {job_id} → {state.value}")
    return status


def get_progress_percent(state: JobState) -> int:
    """Return an estimated progress percentage for the given state (for UI display)."""
    progress_map = {
        JobState.QUEUED:        0,
        JobState.PREPROCESSING: 10,
        JobState.STEP_A:        25,
        JobState.STEP_B:        50,
        JobState.STEP_C:        75,
        JobState.ASSEMBLING:    90,
        JobState.COMPLETE:      100,
        JobState.FAILED:        100,
    }
    return progress_map.get(state, 0)

