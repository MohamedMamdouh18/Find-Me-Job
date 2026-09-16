import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from ..schemas.email import SendEmailRequest
from ..shared import get_email_service

logger = logging.getLogger(__name__)

email_router = APIRouter(prefix="/api/email", tags=["email"])


@email_router.post("/send")
def send_application_email(request: SendEmailRequest):
    email_service = get_email_service()
    if not email_service:
        return JSONResponse(
            {"error": "SMTP credentials are not configured by the server."}, status_code=500
        )
    try:
        response_str = email_service.send_application_email(
            recipient=request.recipient,
            subject=request.subject,
            body=request.body,
        )
        return {"status": "success", "response": response_str}
    except Exception as e:
        logger.exception(f"Email send failed: {e}")
        return JSONResponse({"error": "Email send failed", "details": str(e)}, status_code=500)
