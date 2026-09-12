import enum


class AiStatus(str, enum.Enum):
    FIT = "fit"
    NOT_FIT = "not_fit"


class RunStatus(str, enum.Enum):
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    # Terminal for the row, not a long-lived state: "the workflow is paused" means
    # the NEWEST run row is paused. Resume opens a new row, so nothing is rewritten.
    PAUSED = "paused"
    # Also terminal, but deliberately not resumable: the job in flight was killed
    # mid-call, so there is no clean cursor to continue from. Starting again is a
    # full fresh run. Like PAUSED, it is never touched by the stale-run sweeps.
    STOPPED = "stopped"


class RunTrigger(str, enum.Enum):
    # Only SCHEDULE defers to a pause; MANUAL and RESUME are the user asking for
    # work now. RESUME additionally skips scraping and drains the leftover queue.
    SCHEDULE = "schedule"
    MANUAL = "manual"
    RESUME = "resume"


class UserStatus(str, enum.Enum):
    NEW = "new"
    APPLIED = "applied"
    EMAIL_SENT = "email_sent"
    REFERRAL = "referral"
    ASSESSMENT = "assessment"
    INTERVIEW = "interview"
    OFFER = "offer"
    REJECTED = "rejected"
    WONT_APPLY = "wont_apply"


APPLIED_BUCKET = {
    UserStatus.APPLIED,
    UserStatus.EMAIL_SENT,
    UserStatus.REFERRAL,
}
