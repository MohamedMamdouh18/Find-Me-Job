from dataclasses import dataclass
from datetime import datetime, timedelta
import contextvars
import json
import logging
import re
import time
from typing import Any

from sqlmodel import Session

from ..database.models import WorkflowRun
from ..database.repositories import RunEventRepository
from ..shared import now

logger = logging.getLogger(__name__)

# Single-worker assumption: uvicorn runs one worker process, so process-local progress
# is correct and avoids database contention. If multi-worker support is added,
# this state must be backed by a shared cache.
@dataclass(frozen=True)
class Progress:
    run_id: int
    stage: str
    detail: str
    done: int = 0
    total: int = 0
    waiting_until: datetime | None = None


_current: Progress | None = None
run_id_var: contextvars.ContextVar[int | None] = contextvars.ContextVar("run_id", default=None)


class RunIdFilter(logging.Filter):
    """Injects the active pipeline run_id into every log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        rid = run_id_var.get()
        record.run_id = f"[run:{rid}]" if rid is not None else "[run:-]"
        return True


def get_current_progress() -> Progress | None:
    return _current


def set_current_progress(progress: Progress | None):
    global _current
    _current = progress


def redact_secrets(text: str) -> str:
    """Strip bearer tokens, api keys, and passwords before logging or storing context."""
    if not text:
        return text
    # Bearer tokens
    text = re.sub(r"(Bearer\s+)[A-Za-z0-9_\-\.]{8,}", r"\1[REDACTED]", text, flags=re.IGNORECASE)
    # Telegram bot tokens (e.g. bot123456789:ABCdefGHI... or 123456789:ABCdefGHI...)
    text = re.sub(r"(?:bot)?(\d{8,10}:[A-Za-z0-9_\-]{20,})", r"[REDACTED_TELEGRAM_TOKEN]", text)
    # Generic key/password fields in json
    text = re.sub(r'("(?:api_key|password|secret)":\s*")[^"]+(")', r'\1[REDACTED]\2', text, flags=re.IGNORECASE)
    return text


class RunContext:
    """Carries the run id, session, and progress cursor together, so pipeline
    functions take one argument instead of three."""

    def __init__(self, run_id: int, session: Session):
        self.run_id = run_id
        self.session = session
        run_id_var.set(run_id)

    def emit(
        self,
        stage: str,
        message: str,
        *,
        level: str = "info",
        context: Any = None,
        detail: str | None = None,
        done: int = 0,
        total: int = 0,
    ):
        """Single reporting path: writes run_events, updates workflow_runs, updates progress."""
        ctx_str = None
        if context is not None:
            if isinstance(context, str):
                ctx_str = redact_secrets(context)
            else:
                try:
                    ctx_str = redact_secrets(json.dumps(context))
                except Exception:
                    ctx_str = redact_secrets(str(context))

        # 1. Write run_events row
        RunEventRepository(self.session).add(
            run_id=self.run_id,
            stage=stage,
            message=message,
            level=level,
            context=ctx_str,
        )

        # 2. Update workflow_runs stage and stage_detail
        run = self.session.get(WorkflowRun, self.run_id)
        stage_detail_text = detail or message
        if run:
            run.stage = stage
            run.stage_detail = stage_detail_text
            self.session.add(run)

        self.session.commit()

        # 3. Replace in-process Progress
        set_current_progress(
            Progress(
                run_id=self.run_id,
                stage=stage,
                detail=stage_detail_text,
                done=done,
                total=total,
                waiting_until=None,
            )
        )

        # 4. Log to stdout
        log_fn = getattr(logger, level.lower(), logger.info)
        log_fn(f"[{stage}] {message}")

    def wait(self, seconds: int):
        """Sets the deadline on the tracker once, then sleeps.

        No writes are performed during the wait; endpoints derive seconds_remaining
        from waiting_until at read time.
        """
        deadline = now() + timedelta(seconds=seconds)
        curr = get_current_progress()
        if curr:
            set_current_progress(
                Progress(
                    run_id=curr.run_id,
                    stage=curr.stage,
                    detail=curr.detail,
                    done=curr.done,
                    total=curr.total,
                    waiting_until=deadline,
                )
            )

        time.sleep(seconds)

        # Reset waiting_until once wait is over
        curr = get_current_progress()
        if curr:
            set_current_progress(
                Progress(
                    run_id=curr.run_id,
                    stage=curr.stage,
                    detail=curr.detail,
                    done=curr.done,
                    total=curr.total,
                    waiting_until=None,
                )
            )
