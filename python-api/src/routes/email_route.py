from fastapi import APIRouter
from fastapi.responses import JSONResponse

from .requests_scheme.email import SendEmailRequest
from ..shared import email_service

email_router = APIRouter(prefix="/api/email", tags=["email"])


@email_router.post("/send")
async def send_application_email(request: SendEmailRequest):
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
        print(f"Email send failed: {e}", flush=True)
        return JSONResponse({"error": "Email send failed", "details": str(e)}, status_code=500)
