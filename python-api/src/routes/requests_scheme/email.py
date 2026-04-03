from pydantic import BaseModel


class SendEmailRequest(BaseModel):
    recipient: str
    subject: str
    body: str
