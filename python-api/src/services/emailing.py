import logging
import os
import re

from . import settings
from .llm import call_llm, parse_llm_json
from .run_context import RunContext
from ..database.models import PendingJob
from ..shared import PARAMS_DIR, email_service, send_telegram

logger = logging.getLogger(__name__)

EMAIL_PATTERNS = [
    re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"),
    re.compile(r"send.*?(?:cv|resume|application)", re.IGNORECASE),
    re.compile(r"apply.*?(?:email|mailto)", re.IGNORECASE),
    re.compile(r"email.*?(?:cv|resume|application|us|your)", re.IGNORECASE),
    re.compile(r"careers@|jobs@|hr@|recruitment@|hiring@", re.IGNORECASE),
    re.compile(r"to apply.*?email", re.IGNORECASE),
    re.compile(r"submit.*?(?:cv|resume).*?to", re.IGNORECASE),
]


def has_email_hint(description: str) -> bool:
    """Detects whether a job description hints at email-based application instructions."""
    if not description:
        return False
    return any(p.search(description) is not None for p in EMAIL_PATTERNS)


def process_and_send_email_if_needed(
    ctx: RunContext,
    job: PendingJob,
    cover_letter: str,
) -> bool:
    """If the job contains an email hint, queries the LLM for application details and sends the email.

    Returns True if an email was successfully sent, False otherwise.
    """
    if not has_email_hint(job.description):
        return False

    prompt_file = os.path.join(PARAMS_DIR, "llm_email.txt")
    if not os.path.isfile(prompt_file):
        logger.warning(f"Email prompt template missing at {prompt_file}")
        return False

    with open(prompt_file, "r", encoding="utf-8") as f:
        system_prompt = f.read()

    sender_name = settings.get_sender_name()
    user_content = (
        f"Job Description:\n{job.description}\n\n"
        f"Cover Letter:\n{cover_letter}\n\n"
        f"Job Title: {job.title}\n"
        f"Company: {job.company}\n"
        f"Sender Name: {sender_name}"
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]

    try:
        raw_response = call_llm(messages)
        parsed = parse_llm_json(raw_response)
    except Exception as e:
        logger.warning(f"LLM email extraction failed for job {job.id}: {e}")
        return False

    if not isinstance(parsed, dict) or not parsed.get("hasApplicationEmail"):
        return False

    recipient_email = parsed.get("recipientEmail")
    subject = parsed.get("subject") or f"Application for {job.title} - {sender_name}"
    email_body = parsed.get("emailBody") or cover_letter

    if not recipient_email or "@" not in recipient_email:
        return False

    if email_service:
        try:
            # EmailService attaches the CV itself from its configured cv_path.
            email_service.send_application_email(
                recipient=recipient_email,
                subject=subject,
                body=email_body,
            )
            ctx.emit(
                "email.sent",
                f"Sent application email for {job.title} at {job.company} to {recipient_email}",
                context={"recipient": recipient_email, "subject": subject},
            )
            send_telegram(
                f"Application email sent for *{job.title}* at *{job.company}*\nTo: {recipient_email}"
            )
            return True
        except Exception as e:
            logger.error(f"Failed to send application email: {e}")
            ctx.emit(
                "email.failed",
                f"Failed to send application email to {recipient_email}: {e}",
                level="error",
            )
            return False

    return False
